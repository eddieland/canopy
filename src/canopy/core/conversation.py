"""Conversations (DESIGN §22): references to subjects, the operator's start records and messages, and runs' reports.

Every channel the operator writes through (`canopy start`, `stop`, `reply`, and later the web UI) calls the functions
here, so the guards live in one place: the subject is valid and supports the verb, the command does not run inside one
of canopy's own runs, the ticket was started, and the body is within its bound. Agents never write a message: `_run`
records a run's report and question from its result line (`close_run`), and nothing else a worker can call does.

A private ticket's start record and its operator messages are canopy's own facts, so the harness checks them in code
without reading the tracker (D003, D072).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import contract, db, outbox
from canopy.core.config import CHORE_NAME_RE, REPO_NAME_RE

if TYPE_CHECKING:
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
# How much of a ticket's conversation a private worker's prompt carries: its latest messages, oldest first.
PROMPT_MESSAGES = 20
PROMPT_CHARS = 30_000

TICKET = db.SUBJECT_TICKET
PR = "pr"
CHORE = "chore"
RUN = "run"
# The verbs each kind of subject takes. A PR takes all of them once PR-scoped work exists (ROADMAP M14).
VERBS: Mapping[str, tuple[str, ...]] = {
    TICKET: ("start", "stop", "reply", "show"),
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
                "stops, or replies",
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


def reply(conn: sqlite3.Connection, ref: Ref, body: str, *, channel: str) -> Replied:
    """Record the operator's reply to a started ticket (DESIGN §22).

    It answers the ticket's latest question when there is one. Its submission id is derived from the subject, the
    message it answers, and the body, so the same reply sent again after an uncertain result records nothing new.

    Raises:
        Refused: `unsupported` for a subject that is not a ticket, `not_started` for a public ticket, `bad_body` for an
            empty body or one over 4000 characters.
    """
    check_verb(ref, "reply")
    text = body.strip()
    if not text:
        raise Refused("bad_body", "the reply is empty")
    if len(text) > MAX_OPERATOR:
        raise Refused("bad_body", f"the reply is {len(text)} characters; the most is {MAX_OPERATOR}")
    with db.transaction(conn):
        if db.get_start(conn, TICKET, ref.id) is None:
            raise Refused("not_started", f"{ref} was not started in canopy; a public ticket's replies go on the ticket")
        question = latest_question(conn, ref.id)
        answers = int(question["id"]) if question is not None else None
        submission = hashlib.sha256(f"{ref.kind}\0{ref.id}\0{answers or ''}\0{text}".encode()).hexdigest()[:32]
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
            submission=submission,
        )
    return Replied(message_id=message_id, answers=answers, new=message_id > before)


# What the harness reads


def latest_question(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    """Return a ticket's latest question if no operator message came after it, else None."""
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM messages WHERE subject_kind = ? AND subject_id = ? AND kind = 'question' "
        "ORDER BY id DESC LIMIT 1",
        (TICKET, key),
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
    """
    key = str(ticket["key"])
    record = start_of(conn, key)
    if record is None:
        return None
    cursor = int(ticket["last_message_id"] or 0)
    question = latest_question(conn, key)
    return {
        "status": record["status"],
        "started_at": record["started_at"],
        "message_cursor": cursor or None,
        "new_operator_messages": [
            {"id": m["id"], "at": m["at"], "answers": m["answers"], "body": m["body"]}
            for m in operator_messages_after(conn, key, cursor)
        ],
        "awaiting_reply": None
        if question is None
        else {"message_id": question["id"], "run_id": question["run_id"], "at": question["at"]},
    }


def prompt_conversation(conn: sqlite3.Connection, key: str) -> str:
    """Return a private worker prompt's `{{CONVERSATION}}`: the ticket's latest messages, oldest first, bounded."""
    rows = db.messages_of(conn, TICKET, key, PROMPT_MESSAGES)
    blocks = [_prompt_message(m) for m in rows]
    total = 0
    kept: list[str] = []
    for block in reversed(blocks):
        total += len(block)
        if total > PROMPT_CHARS:
            break
        kept.append(block)
    kept.reverse()
    if not kept:
        return "No messages yet."
    left_out = len(blocks) - len(kept)
    note = [f"[{left_out} older messages are left out.]"] if left_out else []
    return "\n\n".join([*note, *kept])


def _prompt_message(m: sqlite3.Row) -> str:
    if m["source"] == "operator":
        what = "the operator's reply" + (f" to message {m['answers']}" if m["answers"] else "")
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
    result = _object(result_json)
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


def _object(result_json: str | None) -> dict[str, object]:
    if not result_json:
        return {}
    try:
        parsed: object = json.loads(result_json)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k): v for k, v in parsed.items()}
