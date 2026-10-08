"""Conversations (DESIGN §22): references to subjects, the operator's start records and messages, and runs' reports.

Every channel the operator writes through (`canopy start`, `stop`, `reply`, `forget`, and the web UI) calls the
functions here, so the guards live in one place: the subject is valid and supports the verb, the command does not run
inside one of canopy's own runs, the ticket was started (or, for a reply, is one canopy knows), and the body is within
its bound. Agents never write a
message: `_run` records a run's report and question from its result line (`close_run`), and nothing else a worker can
call does.

A private ticket's start record and its operator messages are canopy's own facts, so the harness checks them in code
without reading the tracker (D003, D072). The overseer records the one other kind of message, a tracker comment it
mirrors (`mirror`), which authorizes nothing.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from canopy.core import contract, db, outbox
from canopy.core.config import CHORE_NAME_RE, REPO_NAME_RE
from canopy.infra import lock

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.core.config import Config

# A ticket key reaches branch names, lease holders, paths, and argv (DESIGN §17). It has no `:`, `#`, or `/`, so no
# other kind of reference can be read as one.
KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
MAX_KEY = 100
# Set for the agents of canopy's own runs, as CANOPY_TICK_ID is for the overseer: the operator's commands refuse in
# either, so an agent that follows injected text naively cannot reply or start a ticket as the operator (TRUST_MODEL
# T1).
TICK_ID_ENV = "CANOPY_TICK_ID"
RUN_ID_ENV = "CANOPY_RUN_ID"
MAX_OPERATOR = 4000
MAX_PR_URL = 300
# A submission id a channel's form draws when it is rendered (DESIGN §22).
SUBMISSION_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")
# A mirrored tracker comment's body is cut to this, and marked truncated (DESIGN §22).
MAX_MIRRORED = 2000
# How many `canopy mirror` calls one tick may make: a ticket's first mirror covers its whole history, and this spreads
# a long one over several ticks.
MIRRORS_PER_TICK = 100
MIRROR_ACTION = "mirror"
# A tracker's comment id, as a cursor id is: plain and short. An author is the tracker's account id: printable, no
# whitespace.
_COMMENT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}")
MAX_AUTHOR = 200
MAX_TIME = 64
# How much of a ticket's conversation a private worker's prompt carries: its latest messages, oldest first.
PROMPT_MESSAGES = 20
PROMPT_CHARS = 30_000

TICKET = db.SUBJECT_TICKET
PR = "pr"
CHORE = "chore"
RUN = "run"
# The verbs each kind of subject takes. A PR takes all of them once PR-scoped work exists (ROADMAP M14).
# `mirror` is the overseer's, not the operator's (DESIGN §22).
VERBS: Mapping[str, tuple[str, ...]] = {
    TICKET: ("start", "stop", "reply", "forget", "show", MIRROR_ACTION),
    PR: (),
    CHORE: ("show",),
    RUN: ("show",),
}
_PR_SHORT_RE = re.compile(rf"({REPO_NAME_RE.pattern})#([1-9][0-9]{{0,9}})")
_PR_URL_RE = re.compile(r"https://[^\s/]+/[^\s/]+/[^\s/]+/pull/[1-9][0-9]{0,9}/?")


class Refused(Exception):  # noqa: N818  (an outcome the operator is told about, not an error)
    """A guard refused the operator's command. `guard` names it."""

    def __init__(self, guard: str, reason: str) -> None:
        """Name the guard and say why it refused."""
        super().__init__(f"{guard}: {reason}")
        self.guard = guard
        self.reason = reason


@dataclass(frozen=True)
class Ref:
    """A subject, named by a reference whose shape says its kind (DESIGN §22, D075)."""

    kind: str
    id: str

    def __str__(self) -> str:
        """The reference as the operator writes it."""
        return self.id if self.kind in (TICKET, PR) else f"{self.kind}:{self.id}"


def parse_ref(text: str) -> Ref:
    """Read a reference: a ticket key, `repo#N` or a PR's URL, `chore:NAME`, or `run:ID`.

    Raises:
        Refused: (`bad_ref`) it is none of them.
    """
    if text.startswith("run:"):
        run_id = text.removeprefix("run:")
        if run_id.isascii() and run_id.isdigit() and 0 < len(run_id) <= 18 and int(run_id) > 0:  # noqa: PLR2004
            return Ref(RUN, str(int(run_id)))
    elif text.startswith("chore:"):
        name = text.removeprefix("chore:")
        if CHORE_NAME_RE.fullmatch(name):
            return Ref(CHORE, name)
    elif text.startswith("https://"):
        if contract.plain_url(text, MAX_PR_URL) and _PR_URL_RE.fullmatch(text):
            return Ref(PR, text)
    elif "#" in text:
        if _PR_SHORT_RE.fullmatch(text):
            return Ref(PR, text)
    elif len(text) <= MAX_KEY and KEY_RE.fullmatch(text):
        return Ref(TICKET, text)
    raise Refused(
        "bad_ref",
        f"{text[:MAX_KEY]!r} is not a reference: a ticket key, REPO#N or a PR's URL, chore:NAME, or run:ID",
    )


def check_verb(ref: Ref, verb: str) -> None:
    """Refuse a verb `ref`'s kind does not take (`unsupported`), naming the verbs it does."""
    verbs = VERBS[ref.kind]
    if verb in verbs:
        return
    if ref.kind == PR:
        raise Refused("unsupported", f"{ref} is a PR; canopy works PRs only once PR-scoped work exists (ROADMAP M14)")
    raise Refused("unsupported", f"{ref} is a {ref.kind}, which takes only {', '.join(verbs)}")


def check_operator(environ: Mapping[str, str] | None = None) -> None:
    """Refuse when run inside one of canopy's own ticks or runs (`inside_run`): only the operator starts or replies."""
    env = os.environ if environ is None else environ
    for name in (TICK_ID_ENV, RUN_ID_ENV):
        if env.get(name):
            raise Refused(
                "inside_run",
                f"{name} is set: this runs inside one of canopy's own ticks or runs, and only the operator starts, "
                "stops, replies, or forgets",
            )


def start_of(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    """Return a ticket's start record, or None if it is public: the operator never started it."""
    return db.get_start(conn, TICKET, key)


def is_started(record: sqlite3.Row | None) -> bool:
    """Whether a start record says the ticket is being worked: started and not stopped."""
    return record is not None and record["status"] == "started"


# The operator's commands


@dataclass(frozen=True)
class Started:
    """What `start` did: whether the ticket was already started, and a run already working it."""

    already: bool
    running: sqlite3.Row | None


def start(conn: sqlite3.Connection, config: Config, ref: Ref, *, repo: str, channel: str) -> Started:
    """Start a ticket privately (DESIGN §22): write its start record, or mark a stopped one started again.

    Raises:
        Refused: `unsupported` for a subject that is not a ticket, `no_read_tools` when no tracker tools are known for
            a private worker to read the ticket with.
    """
    check_verb(ref, "start")
    if config.tracker.tools() is None:
        raise Refused(
            "no_read_tools",
            f"no tracker tools are known for provider {config.tracker.provider!r}: set tracker.mcp_server and "
            "tracker.read_tools in your user config, so a private worker can read the ticket and write nothing to it",
        )
    with db.transaction(conn):
        record = db.get_start(conn, TICKET, ref.id)
        db.touch_ticket(conn, ref.id, repo)
        # A ticket the overseer marked done is worked again: the operator asked for it.
        conn.execute("UPDATE tickets SET done = 0 WHERE key = ?", (ref.id,))
        db.set_start(conn, TICKET, ref.id, status="started", channel=channel)
        running = db.running_run_of(conn, ref.id)
    return Started(already=is_started(record), running=running)


@dataclass(frozen=True)
class Stopped:
    """What `stop` did: whether the ticket was already stopped, and the run still working it, if one is."""

    already: bool
    running: sqlite3.Row | None


def stop(conn: sqlite3.Connection, ref: Ref, *, channel: str) -> Stopped:
    """Mark a started ticket stopped, in one transaction with reading the run working it (DESIGN §22).

    A dispatch checks the record and inserts its run in one transaction too, so whichever commits first wins, and the
    run returned here is any run a dispatch committed first.

    Raises:
        Refused: `unsupported` for a subject that is not a ticket, `not_started` for a public ticket.
    """
    check_verb(ref, "stop")
    with db.transaction(conn):
        record = db.get_start(conn, TICKET, ref.id)
        if record is None:
            raise Refused(
                "not_started",
                f"{ref} was not started in canopy; a public ticket stops when its queue label is removed",
            )
        db.set_start(conn, TICKET, ref.id, status="stopped", channel=channel)
        running = db.running_run_of(conn, ref.id)
    return Stopped(already=record["status"] == "stopped", running=running)


@dataclass(frozen=True)
class Replied:
    """What `reply` recorded: the message's id, the message it answers, and whether it was new."""

    message_id: int
    answers: int | None
    new: bool


def reply(conn: sqlite3.Connection, ref: Ref, body: str, *, channel: str, submission: str | None = None) -> Replied:
    """Record the operator's reply to a ticket canopy knows (DESIGN §22).

    A started ticket's reply is its conversation. A public ticket's is the operator's word to the loop, beside its
    authorized repliers' comments on the ticket, and how the operator answers an untrusted reviewer's feedback (DESIGN
    §7, D089). It answers the ticket's latest question when there is one. A channel whose form draws a submission id
    passes it, and it is stored as `<channel>:<id>`; without one the id is derived from the subject, the message it
    answers, and the body. Either way the same reply sent again after an uncertain result records nothing new.

    Raises:
        Refused: `unsupported` for a subject that is not a ticket, `unknown` for a ticket that was neither started nor
            seen by a tick, `bad_body` for an empty body or one over 4000 characters, `bad_submission` for a submission
            id that is not 8 to 64 letters, digits, `-`, or `_`.
    """
    check_verb(ref, "reply")
    if submission is not None and not SUBMISSION_RE.fullmatch(submission):
        raise Refused("bad_submission", f"a submission id is {SUBMISSION_RE.pattern}")
    text = body.strip()
    if not text:
        raise Refused("bad_body", "the reply is empty")
    if len(text) > MAX_OPERATOR:
        raise Refused("bad_body", f"the reply is {len(text)} characters; the most is {MAX_OPERATOR}")
    with db.transaction(conn):
        if db.get_start(conn, TICKET, ref.id) is None and db.get_ticket(conn, ref.id) is None:
            raise Refused(
                "unknown",
                f"canopy has no record of {ref}: start it, or label it and let a tick see it, before replying",
            )
        question = latest_question(conn, ref.id)
        answers = int(question["id"]) if question is not None else None
        if submission is None:
            stored = hashlib.sha256(f"{ref.kind}\0{ref.id}\0{answers or ''}\0{text}".encode()).hexdigest()[:32]
        else:
            stored = f"{channel}:{submission}"
        before = db.latest_message_id(conn)
        message_id = db.insert_message(
            conn,
            TICKET,
            ref.id,
            source="operator",
            kind="reply",
            channel=channel,
            body=text,
            answers=answers,
            submission=stored,
        )
    new = message_id > before
    if not new:
        # The same submission again: what it answered then, whatever is waiting now.
        recorded = db.get_message(conn, message_id)
        answers = int(recorded["answers"]) if recorded is not None and recorded["answers"] is not None else None
    return Replied(message_id=message_id, answers=answers, new=new)


@dataclass(frozen=True)
class Forgot:
    """What `forget` cleared: the ticket's branch and its units' PRs, as the journal had them."""

    branch: str | None
    prs: list[str]


def forget(conn: sqlite3.Connection, ref: Ref, *, dispatch_lock: Path) -> Forgot:
    """Forget a ticket's work, so its next `implement` starts over on a new branch (DESIGN §22).

    Clears its branch, units, phases, and done flag, and marks where the loop's view of it begins: the overseer's state
    block and the attention list skip its earlier runs, and its waiting question, new operator messages, and a private
    worker's conversation skip its earlier messages. The runs stay, so attempt limits still count them (D030), and the
    cursors stay, so what was handled stays handled. It holds the dispatch lock, so a dispatch that read the old branch
    cannot record it again afterwards.

    Raises:
        Refused: `unsupported` for a subject that is not a ticket, `unknown` for a ticket canopy has no record of,
            `running` while a run works it, `split` for a ticket a split made children of.
    """
    check_verb(ref, "forget")
    with lock.hold(dispatch_lock, wait=True), db.transaction(conn):
        ticket = db.get_ticket(conn, ref.id)
        if ticket is None:
            raise Refused("unknown", f"canopy has no record of {ref}, so there is nothing to forget")
        running = db.running_run_of(conn, ref.id)
        if running is not None:
            raise Refused(
                "running",
                f"run {running['id']} ({running['kind']}) is working {ref}; wait for it to end, or on a started "
                f"ticket end it with `canopy stop {ref} --now`",
            )
        children = db.children_of(conn, ref.id)
        if children:
            raise Refused(
                "split",
                f"a split made {', '.join(children)} from {ref}; they are tickets of their own, and forgetting {ref} "
                "would not undo them",
            )
        prs = [str(u["pr_url"]) for u in db.units(conn, ref.id) if u["pr_url"]]
        db.forget_ticket(conn, ref.id)
    return Forgot(branch=ticket["branch"], prs=prs)


# The overseer's mirror of tracker comments


@dataclass(frozen=True)
class Mirrored:
    """What `mirror` recorded: the message, whether it was new, its source, and whether its body was cut."""

    message_id: int
    new: bool
    source: str
    truncated: bool


def mirror(
    conn: sqlite3.Connection,
    config: Config,
    ref: Ref,
    *,
    tick_id: int,
    dry_run: bool,
    repo: str,
    comment_id: str,
    author: str,
    at: str,
    body: str,
) -> Mirrored:
    """Record a tracker comment the overseer read in the subject's journal conversation (DESIGN §22, M19).

    Idempotent on the subject and comment id. A comment carrying the workers' marks (D069) is recorded with source
    `worker`, any other with source `tracker`; either way it authorizes nothing. A live tick moves the subject's mirror
    cursor to the comment; a dry run records the comment and moves no cursor. Records a `mirror` decision in the same
    transaction, which is what the per-tick bound counts.

    Raises:
        Refused: `unsupported` for a subject that is not a ticket, `bad_comment` for a malformed comment id,
            `bad_author` for a malformed account id, `bad_time` for a time that is not ISO 8601, `bad_body` for an empty
            body, and `mirror_limit` once the tick has mirrored its most.
    """
    check_verb(ref, MIRROR_ACTION)
    if not _COMMENT_ID_RE.fullmatch(comment_id):
        raise Refused("bad_comment", f"{comment_id[:MAX_KEY]!r} is not a comment id: {_COMMENT_ID_RE.pattern}")
    if not author or len(author) > MAX_AUTHOR or not author.isprintable() or any(c.isspace() for c in author):
        raise Refused(
            "bad_author", f"the author is the tracker's account id, at most {MAX_AUTHOR} characters, no spaces"
        )
    commented_at = _comment_time(at)
    text = body.strip()
    if not text:
        raise Refused("bad_body", "the comment's body is empty; mirror a comment with no text as `(no text)`")
    truncated = len(text) > MAX_MIRRORED
    if truncated:
        text = text[:MAX_MIRRORED]
    source = "worker" if worker_marked(body, config.trust.comment_prefix, config.trust.comment_suffix) else "tracker"
    comment = db.Comment(id=comment_id, author=author, at=commented_at, truncated=truncated)
    with db.transaction(conn):
        if db.count_decisions(conn, tick_id, MIRROR_ACTION) >= MIRRORS_PER_TICK:
            raise Refused(
                "mirror_limit",
                f"this tick mirrored {MIRRORS_PER_TICK} comments, its most; the rest wait for the next tick",
            )
        db.touch_ticket(conn, ref.id, repo)
        before = db.mirrored_comment(conn, TICKET, ref.id, comment_id)
        message_id = db.insert_message(
            conn, TICKET, ref.id, source=source, kind="comment", channel="tracker", body=text, comment=comment
        )
        if not dry_run:
            db.set_mirror_cursor(conn, ref.id, comment_id)
        if before is None:
            cut = ", truncated" if truncated else ""
            rationale = f"comment {comment_id} by {author} at {commented_at}: message {message_id}, {source}{cut}"
        else:
            rationale = f"comment {comment_id}: already message {message_id}"
        if dry_run:
            rationale += "; dry run, mirror cursor not advanced"
        db.record_decision(conn, tick_id, ref.id, MIRROR_ACTION, rationale)
    return Mirrored(
        message_id=message_id,
        new=before is None,
        source=str(before["source"]) if before is not None else source,
        truncated=bool(before["truncated"]) if before is not None else truncated,
    )


def worker_marked(body: str, prefix: str, suffix: str) -> bool:
    """Whether a comment carries every mark workers put on theirs (D069).

    It starts with the prefix and ends with the suffix, whichever are set, and its last line is not a quote.
    """
    text = body.strip()
    if not text or (not prefix and not suffix):
        return False
    if prefix and not text.startswith(prefix):
        return False
    return not suffix or (text.endswith(suffix) and not text.splitlines()[-1].lstrip().startswith(">"))


def body_delimiter() -> str:
    """Return a heredoc delimiter for this tick's `canopy mirror` bodies that no comment's author can predict.

    The overseer passes a comment's body on stdin through a quoted heredoc, which bash never expands. A body holding the
    delimiter on a line of its own would end the heredoc early and run the rest as commands; a fresh random delimiter
    each tick means no comment can be written to do that.
    """
    return f"CANOPY_BODY_{secrets.token_hex(8)}"


def _comment_time(text: str) -> str:
    try:
        moment = datetime.fromisoformat(text) if len(text) <= MAX_TIME else None
    except ValueError:
        moment = None
    if moment is None:
        raise Refused("bad_time", f"{text[:MAX_TIME]!r} is not an ISO 8601 time")
    # A time with no offset is the tracker's UTC.
    return db.format_time(moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC))


# What the harness reads


def latest_question(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    """Return a ticket's latest question if no operator message came after it, else None.

    A question asked before the operator forgot the ticket's work waits on nothing.
    """
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM messages WHERE subject_kind = ? AND subject_id = ? AND kind = 'question' AND id > ? "
        "ORDER BY id DESC LIMIT 1",
        (TICKET, key, db.forgotten_message_id(conn, key)),
    ).fetchone()
    if row is None or operator_messages_after(conn, key, int(row["id"])):
        return None
    return row


@dataclass(frozen=True)
class Awaiting:
    """A started ticket waiting on the operator: its latest question, which no operator message came after."""

    key: str
    message_id: int
    question: str


def awaiting(conn: sqlite3.Connection) -> list[Awaiting]:
    """Return every started, open ticket whose latest question has no operator message after it, by key."""
    found: list[Awaiting] = []
    rows = conn.execute(
        "SELECT s.subject_id FROM starts s LEFT JOIN tickets t ON t.key = s.subject_id "
        "WHERE s.subject_kind = ? AND s.status = 'started' AND coalesce(t.done, 0) = 0 ORDER BY s.subject_id",
        (TICKET,),
    ).fetchall()
    for row in rows:
        key = str(row[0])
        question = latest_question(conn, key)
        if question is not None:
            found.append(Awaiting(key, int(question["id"]), str(question["body"])))
    return found


def operator_messages_after(conn: sqlite3.Connection, key: str, after: int) -> list[sqlite3.Row]:
    """Return a ticket's operator messages newer than message id `after`, oldest first."""
    return conn.execute(
        "SELECT * FROM messages WHERE subject_kind = ? AND subject_id = ? AND source = 'operator' AND id > ? "
        "ORDER BY id",
        (TICKET, key, after),
    ).fetchall()


def state_section(conn: sqlite3.Connection, ticket: sqlite3.Row) -> dict[str, object] | None:
    """Return a private ticket's part of the overseer's state block, or None for a public ticket (DESIGN §22).

    It carries the operator's messages newer than the ticket's message cursor, and the question waiting on a reply.
    Messages from before the operator forgot the ticket's work are not new, whatever the cursor says.
    """
    key = str(ticket["key"])
    record = start_of(conn, key)
    if record is None:
        return None
    cursor = int(ticket["last_message_id"] or 0)
    forgotten = int(ticket["forgotten_message_id"] or 0)
    question = latest_question(conn, key)
    return {
        "status": record["status"],
        "started_at": record["started_at"],
        "message_cursor": cursor or None,
        "new_operator_messages": [
            {"id": m["id"], "at": m["at"], "answers": m["answers"], "body": m["body"]}
            for m in operator_messages_after(conn, key, max(cursor, forgotten))
        ],
        "awaiting_reply": None
        if question is None
        else {"message_id": question["id"], "run_id": question["run_id"], "at": question["at"]},
    }


def operator_section(conn: sqlite3.Connection, ticket: sqlite3.Row) -> dict[str, object] | None:
    """Return a public ticket's operator messages for the overseer's state block, or None when it has no new ones.

    They are the operator's replies (DESIGN §22) newer than the ticket's message cursor, and after any forget. The
    overseer reads them as instructions, as it reads an authorized reply on the ticket (DESIGN §7). A private ticket's
    are in its own section (`state_section`).
    """
    key = str(ticket["key"])
    if start_of(conn, key) is not None:
        return None
    cursor = int(ticket["last_message_id"] or 0)
    forgotten = int(ticket["forgotten_message_id"] or 0)
    messages = operator_messages_after(conn, key, max(cursor, forgotten))
    if not messages:
        return None
    return {
        "message_cursor": cursor or None,
        "new_operator_messages": [
            {"id": m["id"], "at": m["at"], "answers": m["answers"], "body": m["body"]} for m in messages
        ],
    }


def prompt_operator_messages(conn: sqlite3.Connection, key: str) -> str:
    """Return a public resume worker's `{{OPERATOR_MESSAGES}}`: the operator's latest replies, oldest first, bounded.

    A public ticket's worker hears the operator here rather than on the ticket (DESIGN §22, D089). Replies from before
    the operator forgot the ticket's work are left out.
    """
    rows = conn.execute(
        "SELECT * FROM messages WHERE subject_kind = ? AND subject_id = ? AND source = 'operator' AND id > ? "
        "ORDER BY id DESC LIMIT ?",
        (TICKET, key, db.forgotten_message_id(conn, key), PROMPT_MESSAGES),
    ).fetchall()
    return _bounded([_prompt_message(m) for m in reversed(rows)], "No messages from the operator.")


def prompt_conversation(conn: sqlite3.Connection, key: str) -> str:
    """Return a private worker prompt's `{{CONVERSATION}}`: the ticket's latest messages, oldest first, bounded.

    Messages from before the operator forgot the ticket's work are left out: they are about work that is gone.
    """
    rows = db.messages_of(conn, TICKET, key, PROMPT_MESSAGES, after=db.forgotten_message_id(conn, key))
    return _bounded([_prompt_message(m) for m in rows], "No messages yet.")


def _bounded(blocks: list[str], empty: str) -> str:
    # The newest blocks that fit in PROMPT_CHARS, oldest first, with a note of how many older ones were left out.
    total = 0
    kept: list[str] = []
    for block in reversed(blocks):
        total += len(block)
        if total > PROMPT_CHARS:
            break
        kept.append(block)
    kept.reverse()
    if not kept:
        return empty
    left_out = len(blocks) - len(kept)
    note = [f"[{left_out} older messages are left out.]"] if left_out else []
    return "\n\n".join([*note, *kept])


def _prompt_message(m: sqlite3.Row) -> str:
    if m["source"] == "operator":
        what = "the operator's reply" + (f" to message {m['answers']}" if m["answers"] else "")
    elif m["comment_id"] is not None:
        # A tracker comment the overseer mirrored: data, whoever wrote it (DESIGN §22).
        whose = "an earlier worker's" if m["source"] == "worker" else f"account {m['author']}'s"
        what = f"{whose} tracker comment {m['comment_id']}, data"
    else:
        what = f"an earlier worker's {m['kind']}" + (f", run {m['run_id']}" if m["run_id"] else "")
    body = "\n".join(f"> {line}" for line in printable(str(m["body"])).splitlines() or [""])
    return f"Message {m['id']}, {what}, at {m['at']}:\n{body}"


# A run's messages


def run_messages(status: str, result_json: str | None) -> list[tuple[str, str]]:
    """Return the `(kind, body)` messages a run that closed as `status` reports.

    That is a report, and for a `blocked` run its question. The report is the worker's summary, or the harness's note,
    or the status, then each PR on a line of its own.
    """
    result = contract.stored_object(result_json)
    summary = _text(result.get("summary")) or _text(result.get("harness")) or f"ended {status}"
    prs = result.get("prs")
    urls = [str(u) for u in prs.values() if isinstance(u, str) and u] if isinstance(prs, dict) else []
    found = [("report", "\n".join([summary, *urls]))]
    question = _text(result.get("question"))
    if status == "blocked" and question:
        found.append(("question", question))
    return found


def close_run(conn: sqlite3.Connection, config: Config, run: sqlite3.Row, status: str, result_json: str | None) -> bool:
    """Close a running run as `status`, recording its messages and its `run.ended` event with it, in one transaction.

    Returns False if it was already closed: nothing is recorded.
    """
    return db.finish_run(
        conn,
        int(run["id"]),
        status,
        result_json,
        messages=run_messages(status, result_json),
        event=outbox.run_ended(config, run, status, result_json),
    )


def printable(text: str) -> str:
    """`text` without control characters, line breaks kept: a message shown on a terminal cannot move the cursor."""
    return "".join(c if c.isprintable() or c == "\n" else " " for c in text.replace("\r\n", "\n"))


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
