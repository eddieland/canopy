"""Conversations (DESIGN §22): references to subjects, the operator's start records and messages, and runs' reports.

Every channel the operator writes through (`canopy start`, `stop`, `reply`, `forget`, `dismiss`, `send`, and the web UI)
calls the functions here, so the guards live in one place: the subject is valid and supports the verb, the command does
not run inside one of canopy's own runs, the ticket was started (or, for a reply, is one canopy knows), and the body is
within its bound. Agents never write a message: `_run` records a run's report and question from its result line
(`close_run`), and nothing else a worker can call does.

A private ticket's start record and its operator messages are canopy's own facts, so the harness checks them in code
without reading the tracker (D003, D072). The overseer records one other kind of message, a tracker comment it
mirrors (`mirror`), which authorizes nothing. The last is canopy's own: a tick's note of what it did about the
operator's messages (`note`), which no agent writes and no agent's prompt carries.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import secrets
import sqlite3
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypedDict

from canopy.core import chore_view, contract, db, memory, outbox, records, review_drafts, review_result, sql
from canopy.core.chore_result import FINDING_ID_RE, MAX_ID
from canopy.core.config import CHORE_NAME_RE, REPO_NAME_RE
from canopy.core.vocab import PlanSetting, ReviewRunStatus, RunKind, RunStatus, SeenKind, StartStatus
from canopy.infra import lock
from canopy.infra.text import printable

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.core.config import Chore, Config

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
# The channel of a start record the loop wrote: with `tracker.private` set, a labeled ticket's first dispatch starts
# it privately, as if the operator had (DESIGN §22).
LABEL = "label"
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
COMMENT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}")
MAX_AUTHOR = 200
MAX_TIME = 64
# How much of a ticket's conversation a private worker's prompt carries: its latest messages, oldest first.
PROMPT_MESSAGES = 20
PROMPT_CHARS = 30_000
# How many of a ticket's latest runs a public worker's prompt reports (`prompt_previous_runs`).
PREVIOUS_RUNS = 3
# How many of the operator's notes to a chore its prompt carries: the latest, oldest first (DESIGN §19).
CHORE_NOTES = 10
#: Who wrote a tick's note on a ticket: canopy, from what the tick recorded (`loop/acknowledge.py`).
CANOPY = "canopy"
#: What a tick's note is: canopy's word on the operator's messages, never an instruction or a report of work.
NOTE = "note"

TICKET = db.SUBJECT_TICKET
PR = "pr"
CHORE = "chore"
RUN = "run"
REVIEW = "review"
# The verbs each kind of subject takes. A PR takes `grant` (more reviews, DESIGN §21), `start --review`, `stop`, and
# `persona` (a review request and its persona, `core/review_requests.py`), and `show`; working one is PR-scoped work
# (ROADMAP M14). `mirror` is the overseer's, not the operator's (DESIGN §22).
VERBS: Mapping[str, tuple[str, ...]] = {
    TICKET: ("start", "stop", "reply", "forget", "grant", "show", "plan", "persona", MIRROR_ACTION),
    PR: ("grant", "start", "stop", "show", "persona"),
    CHORE: ("reply", "dismiss", "show"),
    RUN: ("show",),
    # `canopy review show ID` shows one; a reference to it serves to dismiss its findings, or send some to a worker
    # (DESIGN §21), and to mark it seen, as that show and its page do (§22).
    REVIEW: ("dismiss", "send", "seen"),
}
# What a PR refuses beyond reviews: canopy works only tickets until PR-scoped work exists.
_PR_WORK = (
    "{ref} is a PR; canopy only reviews PRs it does not own, and works them once PR-scoped work exists (ROADMAP M14)"
)
_PR_SHORT_RE = re.compile(rf"({REPO_NAME_RE.pattern})#([1-9][0-9]{{0,9}})")
PR_URL_RE = re.compile(r"https://[^\s/]+/[^\s/]+/[^\s/]+/pull/[1-9][0-9]{0,9}/?")


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
        """The reference as the operator writes it.

        Returns:
            A ticket's key or a PR's reference as is, any other kind as `kind:id`.
        """
        return self.id if self.kind in (TICKET, PR) else f"{self.kind}:{self.id}"


def parse_ref(text: str) -> Ref:
    """Read a reference: a ticket key, `repo#N` or a PR's URL, `chore:NAME`, `run:ID`, or `review:ID`.

    Returns:
        The subject, its kind read from the reference's shape. A run id is normalized to plain digits.

    Raises:
        Refused: (`bad_ref`) it is none of them.
    """
    if text.startswith(("run:", "review:")):
        kind, run_id = text.split(":", 1)
        if run_id.isascii() and run_id.isdigit() and 0 < len(run_id) <= 18 and int(run_id) > 0:  # noqa: PLR2004
            return Ref(kind, str(int(run_id)))
    elif text.startswith("chore:"):
        name = text.removeprefix("chore:")
        if CHORE_NAME_RE.fullmatch(name):
            return Ref(CHORE, name)
    elif text.startswith("https://"):
        if contract.plain_url(text, MAX_PR_URL) and PR_URL_RE.fullmatch(text):
            return Ref(PR, text)
    elif "#" in text:
        if _PR_SHORT_RE.fullmatch(text):
            return Ref(PR, text)
    elif len(text) <= MAX_KEY and KEY_RE.fullmatch(text):
        return Ref(TICKET, text)
    raise Refused(
        "bad_ref",
        f"{text[:MAX_KEY]!r} is not a reference: a ticket key, REPO#N or a PR's URL, chore:NAME, run:ID, or review:ID",
    )


def check_verb(ref: Ref, verb: str) -> None:
    """Refuse a verb `ref`'s kind does not take (`unsupported`), naming the verbs it does.

    Raises:
        Refused: (`unsupported`) `ref`'s kind does not take `verb`.
    """
    verbs = VERBS[ref.kind]
    if verb in verbs:
        return
    if ref.kind == PR:
        raise Refused("unsupported", _PR_WORK.format(ref=ref))
    raise Refused("unsupported", f"{ref} is a {ref.kind}, which takes only {', '.join(verbs)}")


def check_operator(environ: Mapping[str, str] | None = None) -> None:
    """Refuse when run inside one of canopy's own ticks or runs (`inside_run`): only the operator starts or replies.

    `canopy pause` and `canopy resume` check it too: an agent that could pause the loop could hold off every tick
    after its own, and one that could resume it could undo the operator's pause.

    Raises:
        Refused: (`inside_run`) CANOPY_TICK_ID or CANOPY_RUN_ID is set in `environ`, or in the process's environment
            when `environ` is None.
    """
    env = os.environ if environ is None else environ
    for name in (TICK_ID_ENV, RUN_ID_ENV):
        if env.get(name):
            raise Refused(
                "inside_run",
                f"{name} is set: this runs inside one of canopy's own ticks or runs, and only the operator starts, "
                "stops, replies, forgets, grants attempts, plans, chooses personas, dismisses or sends findings, marks "
                "reviews seen, edits or sends drafts, pauses, resumes, collects garbage, or reads the commands agents "
                "start with",
            )


def start_of(conn: sqlite3.Connection, key: str) -> records.Start | None:
    """Return a ticket's start record, or None if it is public: the operator never started it."""
    return db.get_start(conn, TICKET, key)


def is_started(record: records.Start | None) -> bool:
    """Whether a start record says the ticket is being worked: started and not stopped.

    Returns:
        True for a record whose status is `started`; False for a stopped one or None.
    """
    return record is not None and record.status is StartStatus.STARTED


# The operator's commands


@dataclass(frozen=True)
class Started:
    """What `start` did: whether the ticket was already started, and a run already working it."""

    already: bool
    running: records.Run | None


def start(
    conn: sqlite3.Connection,
    config: Config,
    ref: Ref,
    *,
    repo: str,
    channel: str,
    plan_lock: Path | None = None,
) -> Started:
    """Start a ticket privately (DESIGN §22): write its start record, or mark a stopped one started again.

    With `plan_lock`, the dispatch lock, the ticket's own plan setting asks for a plan, whatever `policy.plan` says, so
    its implement waits on one the operator approved (DESIGN §25). A plan it already has, waiting or approved, stands.
    The lock is held as the other plan verbs hold it, so a dispatch reads the setting before the start or after it.

    Returns:
        Whether the ticket was already started, and the run working it, if one is.

    Raises:
        Refused: `unsupported` for a subject that is not a ticket, `no_read_tools` when no tracker tools are known for
            a private worker to read the ticket with, and with `plan_lock`, `bad_plan` for a ticket that has a branch,
            since a plan then would describe work already started, or while a plan run for it is running.
    """
    _check_ticket(ref, "start")
    if config.tracker.tools() is None:
        raise Refused(
            "no_read_tools",
            f"no tracker tools are known for provider {config.tracker.provider!r}: set tracker.mcp_server and "
            "tracker.read_tools in your user config, so a private worker can read the ticket and write nothing to it",
        )
    held = lock.hold(plan_lock, wait=True) if plan_lock is not None else contextlib.nullcontext()
    with held, db.transaction(conn):
        record = db.get_start(conn, TICKET, ref.id)
        ticket = db.get_ticket(conn, ref.id)
        running = db.running_run_of(conn, ref.id)
        if plan_lock is not None and ticket is not None and ticket.branch:
            raise Refused("bad_plan", f"{ref} already has work on {ticket.branch}; a started ticket is not planned")
        if plan_lock is not None and running is not None and running.kind == RunKind.PLAN:
            raise Refused("bad_plan", f"plan run {running.id} for {ref} is running; wait for it to end")
        db.touch_ticket(conn, ref.id, repo)
        if plan_lock is not None:
            db.change_ticket(conn, ref.id, "plan_setting", PlanSetting.PLAN)
        # A ticket the overseer marked done is worked again: the operator asked for it.
        db.change_ticket(conn, ref.id, "done", 0)
        db.set_start(conn, TICKET, ref.id, status=StartStatus.STARTED, channel=channel)
    return Started(already=is_started(record), running=running)


def _check_ticket(ref: Ref, verb: str) -> None:
    """Refuse `verb` on anything but a ticket: on a PR, `start` and `stop` are a review request's (review_requests.py).

    Raises:
        Refused: (`unsupported`) `ref` is not a ticket.
    """
    check_verb(ref, verb)
    if ref.kind == PR:
        raise Refused("unsupported", f"{_PR_WORK.format(ref=ref)}; `canopy start {ref} --review` asks for a review")
    if ref.kind != TICKET:
        raise Refused("unsupported", f"{ref} is a {ref.kind}, which takes only {', '.join(VERBS[ref.kind])}")


@dataclass(frozen=True)
class Stopped:
    """What `stop` did: whether the ticket was already stopped, and the run still working it, if one is."""

    already: bool
    running: records.Run | None


def stop(conn: sqlite3.Connection, ref: Ref, *, channel: str) -> Stopped:
    """Mark a started ticket stopped, in one transaction with reading the run working it (DESIGN §22).

    A dispatch checks the record and inserts its run in one transaction too, so whichever commits first wins, and the
    run returned here is any run a dispatch committed first.

    Returns:
        Whether the ticket was already stopped, and the run still working it, if one is.

    Raises:
        Refused: `unsupported` for a subject that is not a ticket, `not_started` for a public ticket.
    """
    _check_ticket(ref, "stop")
    with db.transaction(conn):
        record = db.get_start(conn, TICKET, ref.id)
        if record is None:
            raise Refused(
                "not_started",
                f"{ref} was not started in canopy; a public ticket stops when its queue label is removed",
            )
        db.set_start(conn, TICKET, ref.id, status=StartStatus.STOPPED, channel=channel)
        running = db.running_run_of(conn, ref.id)
    return Stopped(already=record.status is StartStatus.STOPPED, running=running)


@dataclass(frozen=True)
class Replied:
    """What `reply` recorded: the message's id, the message it answers, and whether it was new."""

    message_id: int
    answers: int | None
    new: bool


def reply(
    conn: sqlite3.Connection,
    ref: Ref,
    body: str,
    *,
    channel: str,
    submission: str | None = None,
    chores: Collection[str] = (),
) -> Replied:
    """Record the operator's reply to a ticket canopy knows, or a note to a chore in `chores` (DESIGN §19, §22).

    A started ticket's reply is its conversation. A public ticket's is the operator's word to the loop, beside its
    authorized repliers' comments on the ticket, and how the operator answers an untrusted reviewer's feedback (DESIGN
    §7, D089). It answers the ticket's latest question when there is one. A chore's is a note its next runs read. A
    channel whose form draws a submission id passes it, and it is stored as `<channel>:<id>`; without one the id is
    derived from the subject, the message it answers, and the body. Either way the same reply sent again after an
    uncertain result records nothing new.

    Returns:
        The message's id, the question it answers, if any, and whether it was new. A repeated submission returns the
        message it recorded first, with what that answered.

    Raises:
        Refused: `unsupported` for a subject that is not a ticket or a chore, `unknown` for a ticket that was neither
            started nor seen by a tick or a chore not in `chores`, `bad_body` for an empty body or one over 4000
            characters, `bad_submission` for a submission id that is not 8 to 64 letters, digits, `-`, or `_`.
    """
    check_verb(ref, "reply")
    if submission is not None and not SUBMISSION_RE.fullmatch(submission):
        raise Refused("bad_submission", f"a submission id is {SUBMISSION_RE.pattern}")
    text = body.strip()
    if not text:
        raise Refused("bad_body", "the reply is empty")
    if len(text) > MAX_OPERATOR:
        raise Refused("bad_body", f"the reply is {len(text)} characters; the most is {MAX_OPERATOR}")
    if ref.kind == CHORE and ref.id not in chores:
        raise Refused("unknown", f"no chore {ref.id!r} is defined for this workspace")
    with db.transaction(conn):
        if ref.kind == TICKET and db.get_start(conn, TICKET, ref.id) is None and db.get_ticket(conn, ref.id) is None:
            raise Refused(
                "unknown",
                f"canopy has no record of {ref}: start it, or label it and let a tick see it, before replying",
            )
        question = latest_question(conn, ref.id) if ref.kind == TICKET else None
        answers = question.id if question is not None else None
        if submission is None:
            stored = hashlib.sha256(f"{ref.kind}\0{ref.id}\0{answers or ''}\0{text}".encode()).hexdigest()[:32]
        else:
            stored = f"{channel}:{submission}"
        before = db.latest_message_id(conn)
        message_id = db.insert_message(
            conn,
            ref.kind,
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
        answers = recorded.answers if recorded is not None else None
    return Replied(message_id=message_id, answers=answers, new=new)


def dismiss(
    conn: sqlite3.Connection,
    ref: Ref,
    findings: Collection[str],
    *,
    channel: str,
    chores: Mapping[str, Chore],
    undo: bool = False,
) -> None:
    """Dismiss findings: a chore's, named by their ids (DESIGN §19), or a review run's, by their numbers (§21).

    A chore's open finding is kept off the attention list until it clears: the chore's runs still report it and its
    page still shows it, marked dismissed, and once an `ok` run leaves it out the dismissal is spent, so the finding is
    listed again if it comes back. A review's finding stays on the review's page, marked, and is left out of what a
    `resume` hands a worker and of the overseer's state block; on a review of a PR the loop does not own, what it made
    of the review's draft is dropped, and taking the dismissal back restores it (DESIGN §34). Dismissing one again
    records the time anew; `undo` takes a dismissal back. The findings are dismissed together or not at all: one
    refused leaves every other as it was.

    Raises:
        Refused: `unsupported` for a subject that is not a chore or a review, `unknown` for a chore not in `chores`, a
            review run that does not exist or found nothing, or a finding the subject does not have (with `undo`, one
            not dismissed), and `bad_finding` for no findings, or an id or number no finding can have.
    """
    check_verb(ref, "dismiss")
    if not findings:
        raise Refused("bad_finding", "name one or more findings")
    if ref.kind == REVIEW:
        _dismiss_review(conn, ref, findings, channel=channel, undo=undo)
        return
    if ref.id not in chores:
        raise Refused("unknown", f"no chore {ref.id!r} is defined for this workspace")
    if any(len(f) > MAX_ID or not FINDING_ID_RE.fullmatch(f) for f in findings):
        raise Refused("bad_finding", f"a finding id matches {FINDING_ID_RE.pattern}, at most {MAX_ID} characters")
    ids = list(dict.fromkeys(findings))
    with db.transaction(conn):
        if undo:
            for finding in ids:
                if not db.delete_dismissal(conn, ref.id, finding):
                    raise Refused("unknown", f"{ref} has no dismissed finding {finding!r}")
            return
        state = chore_view.state_of(conn, ref.id, chores[ref.id])
        open_ids = {f.finding.id for f in state.findings()}
        for finding in ids:
            if finding not in open_ids:
                raise Refused("unknown", f"{ref} has no open finding {finding!r}")
            db.set_dismissal(conn, ref.id, finding, channel=channel)


def _dismiss_review(conn: sqlite3.Connection, ref: Ref, findings: Collection[str], *, channel: str, undo: bool) -> None:
    if not all(f.isascii() and f.isdigit() and 0 < len(f) <= 2 and int(f) > 0 for f in findings):  # noqa: PLR2004
        raise Refused("bad_finding", f"a review's finding is its number, from 1 to {review_result.MAX_FINDINGS}")
    numbers, run_id = sorted({int(f) for f in findings}), int(ref.id)
    with db.transaction(conn):
        if undo:
            for number in numbers:
                if not db.delete_review_dismissal(conn, run_id, number):
                    raise Refused("unknown", f"{ref} has no dismissed finding {number}")
        else:
            run = db.get_review_run(conn, run_id)
            if run is None:
                raise Refused("unknown", f"there is no review run {run_id}")
            stored = review_result.stored(run.result_json)
            found = len(stored.findings) if stored is not None and run.status is ReviewRunStatus.DONE else 0
            if numbers[-1] > found:
                raise Refused("unknown", f"{ref} has no finding {numbers[-1]}: it reported {found}")
            for number in numbers:
                db.set_review_dismissal(conn, run_id, number, channel=channel)
        # A review of a PR the loop does not own drafts a review on it: a dismissal drops what the finding made of the
        # draft, and taking it back restores it (DESIGN §34).
        review_drafts.dismissed(conn, run_id, numbers, undo=undo, channel=channel)


def see(conn: sqlite3.Connection, refs: Sequence[Ref], *, channel: str) -> list[Ref]:
    """Mark each subject seen by the operator (DESIGN §22): a review run's result, once the run has ended.

    A subject is new to the operator until they see it, on its page or in the CLI; a mark authorizes nothing and no
    agent reads it. Seeing one again records nothing new. All of `refs` are marked, or none.

    Returns:
        The subjects not seen before, in the order given.

    Raises:
        Refused: `unsupported` for a subject whose kind takes no `seen`, `unknown` for a review run that does not exist,
            and `running` for one that has not ended, which has no result to see yet.
    """
    for ref in refs:
        check_verb(ref, "seen")
    unique = list(dict.fromkeys(refs))
    with db.transaction(conn):
        for ref in unique:
            run = db.get_review_run(conn, int(ref.id))
            if run is None:
                raise Refused("unknown", f"there is no review run {ref.id}")
            if run.ended_at is None:
                raise Refused("running", f"{ref} is still running: it has no result to see yet")
        new = set(db.set_seen(conn, SeenKind.REVIEW, [ref.id for ref in unique], channel=channel))
    return [ref for ref in unique if ref.id in new]


@dataclass(frozen=True)
class Sent:
    """What `send` recorded: the ticket the message went to, and the reply it is."""

    ticket: str
    replied: Replied


def send(
    conn: sqlite3.Connection,
    ref: Ref,
    findings: Collection[int],
    *,
    channel: str,
    submission: str | None = None,
) -> Sent:
    """Send some of a review run's findings to a worker: the operator's go-ahead on them, as a reply (DESIGN §21).

    It records an operator message on the review's ticket that names the findings by number and the run by id, and
    the ones it leaves alone. The message is the instruction, as any reply is: the next tick reads it as the operator's
    go-ahead (DESIGN §7, D089) and resumes a worker with the run's findings, which addresses the ones it names. It names
    them and never quotes them, since a finding is the reviewer's text and the message is the operator's.

    Returns:
        The ticket, and the reply it recorded.

    Raises:
        Refused: `unsupported` for a subject that is not a review, `bad_finding` for no findings or a number no
            finding can have, `unknown` for a review run that does not exist or did not end `done` with findings, or a
            finding it does not have, `dismissed` for a finding the operator dismissed, and `not_ours` for a review of
            a PR that is not one of the loop's own (`own_pr`), which no worker pushes to. As `reply`:
            `bad_submission`, and `unknown` for a ticket canopy has no record of.
    """
    check_verb(ref, "send")
    numbers = sorted(set(findings))
    if not numbers or any(not 0 < n <= review_result.MAX_FINDINGS for n in numbers):
        raise Refused("bad_finding", f"name one or more findings by number, from 1 to {review_result.MAX_FINDINGS}")
    run_id = int(ref.id)
    run = db.get_review_run(conn, run_id)
    if run is None:
        raise Refused("unknown", f"there is no review run {run_id}")
    stored = review_result.stored(run.result_json)
    found = len(stored.findings) if stored is not None and run.status is ReviewRunStatus.DONE else 0
    if numbers[-1] > found:
        raise Refused("unknown", f"{ref} has no finding {numbers[-1]}: it reported {found}")
    dismissed = db.review_dismissals(conn, run_id)
    if held := [n for n in numbers if n in dismissed]:
        raise Refused("dismissed", f"{ref} {_numbered(held)} dismissed; undo the dismissal to send it")
    key = run.ticket_key
    if key is None or not own_pr(conn, run):
        raise Refused("not_ours", f"{ref} is of a PR the loop did not open, which no worker pushes to")
    left = tuple(n for n in range(1, found + 1) if n not in numbers and n not in dismissed)
    body = f"Address {_numbered(numbers, verb=False)} of canopy's review run {run_id}, of commit {run.sha[:12]}."
    if left:
        body += f" Leave its {_numbered(left, verb=False)} alone."
    replied = reply(conn, Ref(TICKET, key), body, channel=channel, submission=submission)
    return Sent(ticket=key, replied=replied)


def own_pr(conn: sqlite3.Connection, run: records.ReviewRun) -> bool:
    """Whether review run `run` is of one of the loop's own PRs, and its ticket's unit still has that PR.

    Only such a review's findings can be sent to a worker (DESIGN §21). Its purpose was checked when it started; the
    unit is checked again because `canopy forget` clears it, and a forgotten ticket's next PR is another PR.

    Returns:
        True when the run's purpose is `own` and its ticket's unit in its repository has the run's PR.
    """
    return (
        run.purpose == "own"
        and run.ticket_key is not None
        and db.is_unit_pr(conn, run.ticket_key, run.pr_url, repo=run.repo)
    )


def _numbered(numbers: Collection[int], *, verb: bool = True) -> str:
    # `finding 2 is`, `findings 1 and 3 are`, `findings 1, 3, and 5`.
    words = [str(n) for n in numbers]
    if len(words) == 1:
        return f"finding {words[0]}{' is' if verb else ''}"
    listed = f"{words[0]} and {words[1]}" if len(words) == 2 else f"{', '.join(words[:-1])}, and {words[-1]}"  # noqa: PLR2004
    return f"findings {listed}{' are' if verb else ''}"


@dataclass(frozen=True)
class Forgot:
    """What `forget` cleared: the ticket's branch and its units' PRs, as the journal had them."""

    branch: str | None
    prs: Sequence[str]


def forget(conn: sqlite3.Connection, ref: Ref, *, channel: str, dispatch_lock: Path) -> Forgot:
    """Forget a ticket's work, so its next `implement` starts over on a new branch (DESIGN §22).

    Clears its branch, units, phases, and done flag, and marks where the loop's view of it begins: the overseer's state
    block and the attention list skip its earlier runs, and its waiting question, new operator messages, and a private
    worker's conversation skip its earlier messages. The runs stay, so attempt limits still count them (D030), and the
    cursors stay, so what was handled stays handled. Each forget is recorded, from `channel`, with what it dropped. It
    holds the dispatch lock, so a dispatch that read the old branch cannot record it again afterwards.

    Returns:
        The ticket's branch and its units' PRs, as the journal had them before they were cleared.

    Raises:
        Refused: `unsupported` for a subject that is not a ticket, `unknown` for a ticket canopy has no record of,
            `running` while a run works it, `already_forgotten` for one with nothing new since its last forget.
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
                f"run {running.id} ({running.kind}) is working {ref}; wait for it to end, or on a started "
                f"ticket end it with `canopy stop {ref} --now`",
            )
        if not db.worked_since_forget(conn, ticket):
            raise Refused(
                "already_forgotten",
                f"{ref} has had no run, message, branch, or PR since you forgot it, so there is nothing new to forget",
            )
        prs = [str(u.pr_url) for u in db.units(conn, ref.id) if u.pr_url]
        db.forget_ticket(conn, ref.id, channel=channel, branch=ticket.branch, prs=prs)
        # Its notes are about work that is gone, as its earlier runs' reports are (DESIGN §28, Retention).
        memory.end_ticket_notes(conn, ref.id, "forgotten work")
    return Forgot(branch=ticket.branch, prs=prs)


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

    Returns:
        The message's id, whether it was new, and its source and truncation. A comment mirrored before keeps the source
        and truncation it was recorded with.

    Raises:
        Refused: `unsupported` for a subject that is not a ticket, `bad_comment` for a malformed comment id,
            `bad_author` for a malformed account id, `bad_time` for a time that is not ISO 8601, `bad_body` for an empty
            body, and `mirror_limit` once the tick has mirrored its most.
    """
    check_verb(ref, MIRROR_ACTION)
    if not COMMENT_ID_RE.fullmatch(comment_id):
        raise Refused("bad_comment", f"{comment_id[:MAX_KEY]!r} is not a comment id: {COMMENT_ID_RE.pattern}")
    if not author or len(author) > MAX_AUTHOR or not author.isprintable() or any(c.isspace() for c in author):
        raise Refused(
            "bad_author",
            f"the author is the tracker's account id, at most {MAX_AUTHOR} characters, no spaces",
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
            conn,
            TICKET,
            ref.id,
            source=source,
            kind="comment",
            channel="tracker",
            body=text,
            comment=comment,
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
        source=before.source if before is not None else source,
        truncated=before.truncated if before is not None else truncated,
    )


def worker_marked(body: str, prefix: str, suffix: str) -> bool:
    """Whether a comment carries every mark workers put on theirs (D069).

    It starts with the prefix and ends with the suffix, whichever are set, and its last line is not a quote.

    Returns:
        True if it carries them all; False for an empty body, or when neither prefix nor suffix is set.
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


def latest_question(conn: sqlite3.Connection, key: str) -> records.Message | None:
    """Return a ticket's latest question if no operator message came after it, else None.

    A question asked before the operator forgot the ticket's work waits on nothing.
    """
    row = records.fetch_one(
        conn,
        records.Message,
        sql.select("*")
        .from_("messages")
        .where("subject_kind = ? AND subject_id = ?", TICKET, key)
        .where("kind = 'question' AND id > ?", db.forgotten_message_id(conn, key))
        .order_by("id DESC")
        .limit(1),
    )
    if row is None or operator_messages_after(conn, key, row.id):
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
    started = (
        sql.select("s.subject_id")
        .from_("starts s")
        .left_join("tickets t ON t.key = s.subject_id")
        .where("s.subject_kind = ? AND s.status = 'started' AND coalesce(t.done, 0) = 0", TICKET)
        .order_by("s.subject_id")
    )
    rows = sql.execute(conn, started).fetchall()
    for row in rows:
        key = str(row[0])
        question = latest_question(conn, key)
        if question is not None:
            found.append(Awaiting(key, question.id, question.body))
    return found


def stopped(conn: sqlite3.Connection) -> list[str]:
    """Return every ticket the operator stopped, by key: what the overseer decides nothing about (DESIGN §22)."""
    stops = (
        sql.select("subject_id")
        .from_("starts")
        .where("subject_kind = ? AND status = 'stopped'", TICKET)
        .order_by("subject_id")
    )
    rows = sql.execute(conn, stops).fetchall()
    return [str(row[0]) for row in rows]


def operator_messages_after(conn: sqlite3.Connection, key: str, after: int) -> list[records.Message]:
    """Return a ticket's operator messages newer than message id `after`, oldest first."""
    return records.fetch_all(
        conn,
        records.Message,
        sql.select("*")
        .from_("messages")
        .where("subject_kind = ? AND subject_id = ? AND source = 'operator' AND id > ?", TICKET, key, after)
        .order_by("id"),
    )


class OperatorMessage(TypedDict):
    """One of the operator's messages as the overseer's state block carries it."""

    id: int
    at: str
    # The message it replies to, when the channel knew it.
    answers: int | None
    body: str


class AwaitingReply(TypedDict):
    """The question a private ticket's worker asked that no operator message has followed."""

    message_id: int
    run_id: int | None
    at: str


class PrivateSection(TypedDict):
    """A started ticket's `private` key in the overseer's state block (DESIGN §22)."""

    started_at: str
    message_cursor: int | None
    new_operator_messages: list[OperatorMessage]
    awaiting_reply: AwaitingReply | None


class OperatorSection(TypedDict):
    """A public ticket's `operator` key in the overseer's state block (DESIGN §7, D089)."""

    message_cursor: int | None
    new_operator_messages: list[OperatorMessage]


def state_section(conn: sqlite3.Connection, ticket: records.Ticket) -> PrivateSection | None:
    """Return a started ticket's part of the overseer's state block, or None for a public ticket (DESIGN §22).

    It carries the operator's messages newer than the ticket's message cursor, and the question waiting on a reply.
    Messages from before the operator forgot the ticket's work are not new, whatever the cursor says. A stopped ticket
    is not asked for: the block names it only by key (`stopped`).
    """
    key = ticket.key
    record = start_of(conn, key)
    if record is None:
        return None
    cursor = ticket.last_message_id or 0
    forgotten = ticket.forgotten_message_id or 0
    question = latest_question(conn, key)
    return {
        "started_at": record.started_at,
        "message_cursor": cursor or None,
        "new_operator_messages": [
            _operator_message(m) for m in operator_messages_after(conn, key, max(cursor, forgotten))
        ],
        "awaiting_reply": None
        if question is None
        else {"message_id": question.id, "run_id": question.run_id, "at": question.at},
    }


def operator_section(conn: sqlite3.Connection, ticket: records.Ticket) -> OperatorSection | None:
    """Return a public ticket's operator messages for the overseer's state block, or None when it has no new ones.

    They are the operator's replies (DESIGN §22) newer than the ticket's message cursor, and after any forget. The
    overseer reads them as instructions, as it reads an authorized reply on the ticket (DESIGN §7). A private ticket's
    are in its own section (`state_section`).
    """
    key = ticket.key
    if start_of(conn, key) is not None:
        return None
    cursor = ticket.last_message_id or 0
    forgotten = ticket.forgotten_message_id or 0
    messages = operator_messages_after(conn, key, max(cursor, forgotten))
    if not messages:
        return None
    return {
        "message_cursor": cursor or None,
        "new_operator_messages": [_operator_message(m) for m in messages],
    }


def _operator_message(row: records.Message) -> OperatorMessage:
    return {"id": row.id, "at": row.at, "answers": row.answers, "body": row.body}


def has_operator_messages(conn: sqlite3.Connection, key: str) -> bool:
    """Whether the operator has written to a ticket in canopy since any forget: what its worker must hear (D093).

    Returns:
        True if the ticket has an operator message newer than its last forget.
    """
    return bool(operator_messages_after(conn, key, db.forgotten_message_id(conn, key)))


def prompt_operator_messages(conn: sqlite3.Connection, key: str) -> str | None:
    """Return a public worker's `{{OPERATOR_MESSAGES}}`: the operator's latest replies, oldest first, bounded.

    A public ticket's worker hears the operator here rather than on the ticket (DESIGN §22, D089). The questions
    workers reported come with them, so a reply to message N names something the worker can read (D093); the rest of
    the conversation is on the tracker. Messages from before the operator forgot the ticket's work are left out.

    Returns:
        The messages; None, which leaves the prompt's section out, when there are none.
    """
    if not has_operator_messages(conn, key):
        return None
    rows = records.fetch_all(
        conn,
        records.Message,
        sql.select("*")
        .from_("messages")
        .where("subject_kind = ? AND subject_id = ? AND id > ?", TICKET, key, db.forgotten_message_id(conn, key))
        .where("source = 'operator' OR kind = 'question'")
        .order_by("id DESC")
        .limit(PROMPT_MESSAGES),
    )
    return _bounded([_prompt_message(m) for m in reversed(rows)])


def prompt_conversation(conn: sqlite3.Connection, key: str) -> str | None:
    """Return a private worker prompt's `{{CONVERSATION}}`: the ticket's latest messages, oldest first, bounded.

    Messages from before the operator forgot the ticket's work are left out: they are about work that is gone. So is a
    an old triage's report: model text written from the ticket, which no other run hears (M55).
    So are canopy's notes: they say what the loop did, which the worker knows, and quote the overseer's reasons.

    Returns:
        The messages; None, which leaves the prompt's section out, when there are none.
    """
    rows = records.fetch_all(
        conn,
        records.Message,
        sql.select("*")
        .from_("messages")
        .where("subject_kind = ? AND subject_id = ? AND id > ?", TICKET, key, db.forgotten_message_id(conn, key))
        .where("source != ?", CANOPY)
        .where("run_id IS NULL OR run_id NOT IN (SELECT id FROM runs WHERE kind = ?)", RunKind.NEEDS_PLAN)
        .order_by("id DESC")
        .limit(PROMPT_MESSAGES),
    )
    return _bounded([_prompt_message(m) for m in reversed(rows)])


def prompt_previous_runs(conn: sqlite3.Connection, key: str) -> str | None:
    """Return a public worker's `{{PREVIOUS_RUNS}}`: what the ticket's latest runs reported, oldest first.

    Each run's kind, how it ended, its report, and a `blocked` run's question, as the run recorded them
    (`run_messages`). Every run starts a fresh session, so this is how a worker learns what the runs before it
    concluded (DESIGN §8). A private worker reads the same reports in its conversation. Runs from before the operator
    forgot the ticket's work are left out, and so are old triages, whose reason no worker hears (M55). A summary and
    a question are each at most 2000 characters (`worker.MAX_TEXT`), so the section is bounded.

    Returns:
        The reports; None, which leaves the prompt's section out, when no earlier run has ended.
    """
    blocks: list[str] = []
    for run in db.ended_runs_of(conn, key, PREVIOUS_RUNS, skip_kind=RunKind.NEEDS_PLAN):
        ended = f" at {run['ended_at']}" if run["ended_at"] else ""
        lines = [f"Run {run['id']}, `{run['kind']}`, ended `{run['status']}`{ended}."]
        for m in db.run_messages(conn, int(run["id"])):
            lines += [f"Its {m.kind}:", _quoted(m.body)]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) or None


class ChoreNote(TypedDict):
    """One of the operator's notes to a chore, as its prompt carries it (DESIGN §19)."""

    id: int
    at: str
    note: str


def chore_notes(conn: sqlite3.Connection, name: str) -> list[ChoreNote]:
    """Return what a chore's prompt carries of the operator's notes to it: the latest, oldest first (DESIGN §19)."""
    return [{"id": m.id, "at": m.at, "note": printable(m.body)} for m in db.messages_of(conn, CHORE, name, CHORE_NOTES)]


def _bounded(blocks: Sequence[str]) -> str | None:
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
        return None
    left_out = len(blocks) - len(kept)
    note = [f"[{left_out} older messages are left out.]"] if left_out else []
    return "\n\n".join([*note, *kept])


def _prompt_message(m: records.Message) -> str:
    if m.source == "operator":
        what = "the operator's reply" + (f" to message {m.answers}" if m.answers else "")
    elif m.comment_id is not None:
        # A tracker comment the overseer mirrored: data, whoever wrote it (DESIGN §22).
        whose = "an earlier worker's" if m.source == "worker" else f"account {m.author}'s"
        what = f"{whose} tracker comment {m.comment_id}, data"
    else:
        what = f"an earlier worker's {m.kind}" + (f", run {m.run_id}" if m.run_id else "")
    return f"Message {m.id}, {what}, at {m.at}:\n{_quoted(m.body)}"


def _quoted(text: str) -> str:
    # A message's body as a quote, one `> ` line per line, without control characters.
    return "\n".join(f"> {line}" for line in printable(text).splitlines() or [""])


# A tick's note


def note(conn: sqlite3.Connection, key: str, body: str, *, answers: int) -> int:
    """Record canopy's note on ticket `key`: what a tick did about the operator's messages, the newest `answers`.

    Returns:
        The note's id.
    """
    return db.insert_message(conn, TICKET, key, source=CANOPY, kind=NOTE, channel="tick", body=body, answers=answers)


# A run's messages


def run_messages(status: RunStatus, result_json: str | None) -> list[tuple[str, str]]:
    """Return the `(kind, body)` messages a run that closed as `status` reports.

    That is a report, and for a `blocked` run its question. The report is the worker's summary, an old triage's reason,
    or the harness's note, or the status, then each PR on a line of its own.
    """
    result = contract.stored_object(result_json)
    # An old triage's report is its reason (M55).
    summary = (
        _text(result.get("summary")) or _text(result.get("reason")) or _text(result.get("harness")) or f"ended {status}"
    )
    prs = result.get("prs")
    urls = [str(u) for u in prs.values() if isinstance(u, str) and u] if isinstance(prs, dict) else []
    found = [("report", "\n".join([summary, *urls]))]
    question = _text(result.get("question"))
    if status == RunStatus.BLOCKED and question:
        found.append(("question", question))
    return found


def close_run(
    conn: sqlite3.Connection,
    config: Config,
    run: sqlite3.Row,
    status: RunStatus,
    result_json: str | None,
    *,
    then: Callable[[], object] | None = None,
) -> bool:
    """Close a running run as `status`, recording its messages and its `run.ended` event with it, in one transaction.

    `then` writes what else the run reported in the same transaction, such as its memory (DESIGN §28).

    Returns:
        True if this closed the run. False if it was already closed: nothing is recorded.
    """
    return db.finish_ticket_run(
        conn,
        int(run["id"]),
        status,
        result_json,
        messages=run_messages(status, result_json),
        event=outbox.run_ended(config, run, status, result_json),
        then=then,
    )


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
