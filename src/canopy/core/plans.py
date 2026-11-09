"""Plans before implementing (DESIGN §25, ROADMAP M44): each plan's file on disk, and its row in the journal.

A plan's text is a markdown file of its own, `<state_dir>/plans/<KEY>/<run>.md`, named for the plan run that wrote it,
so the operator reads, greps, and edits it with their own tools. The journal's `plans` row holds what canopy decides
by: the plan's status, the file's hash as written, and the hash the operator approved, with the hashes of the ticket's
title and description as the tracker connector observed them then. A ticket has at most one plan that is not
superseded, its current plan, waiting (`proposed`) or `approved`.

Whether a ticket needs a plan is its own setting, set only by the operator (`ask`, `skip`), or with none
`policy.plan` (`needed`). The operator's verbs here, asking for a plan, skipping it, and approving one, are every
channel's: each refuses inside one of canopy's own runs, and holds the dispatch lock, so a dispatch reads a ticket's
plans either before the verb or after it.

A file is written once and never deleted: under a temporary name in the ticket's directory, then linked to its own,
which fails if the name is taken. The operator's edits replace it (`save`, or their own editor), so beside it goes a
copy under a second name, `<run>.original.md`, never written again, that keeps the plan as its planner wrote it.
`plans/` and each ticket's directory are operator-only, and one that is not, or a symlink, refuses the write. Every read
opens a regular file without following a link and takes at most `MAX_CHARS` of UTF-8; its hash is of the whole file, so
a file over the bound is not a plan and never matches a hash.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import secrets
import stat
from dataclasses import dataclass
from typing import IO, TYPE_CHECKING, Literal, Protocol, TypedDict, assert_never

from canopy.core import conversation, db, epic_changes, records, sql
from canopy.core.conversation import KEY_RE, MAX_KEY, Refused
from canopy.core.vocab import PlanEffort, PlanSetting, PlanStatus, RunKind, RunStatus
from canopy.infra import lock

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from canopy.core.config import Policy

# What a planner can write in one message and an operator can read before approving (DESIGN §25, The prompt).
MAX_CHARS = 100_000
DIR_NAME = "plans"
# A copy of a plan in a run's working directory: in a worker's, the approved plan it follows, and in a plan run's desk,
# the plan it replaces (DESIGN §25, Workers follow the plan). Written fresh for each run and removed before its slots
# go back.
COPY = ".canopy-plan.md"
REPLACED = COPY
# The file a planner writes its plan to in its desk, the one file its definition lets it edit (DESIGN §25). A revision
# starts with it holding the plan it replaces, as `REPLACED` does, so the planner edits that plan rather than writing it
# again. `.agents/agents/canopy-planner.md` names it too.
WRITTEN = ".canopy-new-plan.md"
#: Why a revision's plan was not recorded when its planner left `WRITTEN` as canopy seeded it (`unrevised`).
UNREVISED = (
    f"the planner reported done, but left its {WRITTEN} as the plan it replaces, though the operator asked for "
    "changes; no plan was recorded"
)
# A plan's outline in a worker's prompt: its markdown headings outside fenced code, at most this many, each cut at
# `MAX_HEADING` characters (DESIGN §25, Workers follow the plan).
MAX_OUTLINE = 200
MAX_HEADING = 200
# The most bytes `MAX_CHARS` characters of UTF-8 can take: one more and the file is over the bound however it decodes.
_MAX_BYTES = 4 * MAX_CHARS
_CHUNK = 64 * 1024

# CommonMark's: an ATX heading, and a fence's opening or closing marker, each indented at most three spaces.
_HEADING_RE = re.compile(r"#{1,6}(?:[ \t]|$)")
_FENCE_RE = re.compile(r"(`{3,}|~{3,})")
_MAX_INDENT = 3

#: The most characters of the operator's note an approval carries to the plan's implement, within an operator message's
#: bound after the sentence that names the plan (DESIGN §25, Approving a plan).
MAX_NOTE = conversation.MAX_OPERATOR - 200

#: The channel a plan's approval names when the harness approved it on its planner's word that it needs no review,
#: under `policy.planner_may_approve`: the planner's approval, never the operator's (DESIGN §25).
PLANNER = "planner"

#: What of a ticket's text can change since its plan was approved, as the harness's warning names it (`ticket_changed`).
type TicketPart = Literal["title", "description"]

# Why a file is not a plan, as `canopy show` and the refusals say it.
type Problem = Literal["missing", "not a regular file", "unreadable", "not UTF-8", "empty", "over the bound"]


class Replaced(Protocol):
    """A plan a planner's run replaces, of a ticket or an epic: when it was made, and when it was approved."""

    @property
    def created_at(self) -> str:
        """When the plan was recorded, as the journal holds it."""
        ...

    @property
    def approved_at(self) -> str | None:
        """When the plan was last approved, as the run started, or None if it was not."""
        ...


class PlanFileError(Exception):
    """A plan's file could not be written: a directory is not the operator's own, or the name is taken."""


@dataclass(frozen=True)
class Written:
    """A plan's file as written: its SHA-256, hex, and its size in bytes, which its row records."""

    sha256: str
    size: int


@dataclass(frozen=True)
class Reading:
    """A plan's file as read: its text when it is a plan, else why not; its hash and size whenever it could be read."""

    text: str | None
    sha256: str | None
    size: int | None
    problem: Problem | None


def needed(policy: str, setting: PlanSetting | None) -> bool:
    """Whether a ticket waits on an approved plan before its implement (DESIGN §25, Which tickets are planned).

    Returns:
        True when its own setting asks for a plan, or it has none and `policy`, `policy.plan`, is `"approve"`.
    """
    return setting is PlanSetting.PLAN or (setting is None and policy == "approve")


@dataclass(frozen=True)
class Asked:
    """What `ask` or `skip` did: the plan it superseded, if any, and whether the ticket's setting was already so."""

    superseded: int | None
    already: bool


def ask(conn: sqlite3.Connection, key: str, *, dispatch_lock: Path) -> Asked:
    """Ask for a plan for `key`, whatever the policy: set its own setting to `plan` and supersede its current plan.

    So the ticket needs a plan and has none, and the next tick dispatches one (DESIGN §25).

    Returns:
        The plan it superseded, if the ticket had one waiting or approved, and whether it already asked for a plan
        and had none.

    Raises:
        Refused: `inside_run` inside one of canopy's own ticks or runs; `unknown` for a ticket canopy has no record
            of; `bad_plan` while a plan run for it is running, or once it has a branch, since a plan then would
            describe work already started.
    """
    conversation.check_operator()
    with lock.hold(dispatch_lock, wait=True), db.transaction(conn):
        ticket = _ticket(conn, key)
        _not_planning(conn, key)
        if ticket.branch:
            raise Refused(
                "bad_plan",
                f"{key} already has work on {ticket.branch}; a started ticket is not planned, but --skip drops its "
                "plan",
            )
        superseded = supersede(conn, key)
        already = ticket.plan_setting is PlanSetting.PLAN and superseded is None
        db.change_ticket(conn, key, "plan_setting", PlanSetting.PLAN)
    return Asked(superseded=superseded, already=already)


def skip(conn: sqlite3.Connection, key: str, *, dispatch_lock: Path) -> Asked:
    """Waive `key`'s plan, whatever the policy: set its own setting to `skip` and supersede its current plan.

    So no plan waits on the operator, and no later run carries one: the way past an approved plan whose file is gone,
    on a ticket with a branch (DESIGN §25).

    Returns:
        The plan it superseded, if any, and whether the ticket's plan was already skipped.

    Raises:
        Refused: `inside_run` inside one of canopy's own ticks or runs; `unknown` for a ticket canopy has no record
            of; `bad_plan` while a plan run for it is running.
    """
    conversation.check_operator()
    with lock.hold(dispatch_lock, wait=True), db.transaction(conn):
        ticket = _ticket(conn, key)
        _not_planning(conn, key)
        superseded = supersede(conn, key)
        already = ticket.plan_setting is PlanSetting.SKIP and superseded is None
        db.change_ticket(conn, key, "plan_setting", PlanSetting.SKIP)
    return Asked(superseded=superseded, already=already)


def start_setting(conn: sqlite3.Connection, key: str, setting: PlanSetting) -> None:
    """Set a ticket's own plan setting as the operator starts it (DESIGN §25), whatever the policy.

    `plan` is `canopy start --plan`'s: its implement waits on a plan the operator approved, and a plan it already has,
    waiting or approved, stands. `skip` waives its plan, superseding a current one, as `skip` does. Call inside the
    start's transaction, after `conversation.start`, with the dispatch lock held, so a dispatch reads the setting
    before the start or after it.

    Raises:
        Refused: `inside_run` inside one of canopy's own ticks or runs; `bad_plan` while a plan run for it is running,
            or for `plan` once it has a branch, since a plan then would describe work already started.
    """
    conversation.check_operator()
    ticket = _ticket(conn, key)
    _not_planning(conn, key)
    match setting:
        case PlanSetting.PLAN:
            if ticket.branch:
                raise Refused("bad_plan", f"{key} already has work on {ticket.branch}; a started ticket is not planned")
        case PlanSetting.SKIP:
            supersede(conn, key)
        case _:
            assert_never(setting)
    db.change_ticket(conn, key, "plan_setting", setting)


def _ticket(conn: sqlite3.Connection, key: str) -> records.Ticket:
    """The ticket the operator names, which canopy must know: its setting is a column of its row.

    Returns:
        The ticket's row.

    Raises:
        Refused: (`unknown`) canopy has no record of it.
    """
    ticket = db.get_ticket(conn, key)
    if ticket is None:
        raise Refused(
            "unknown",
            f"canopy has no record of {key}: start it, or label it and let a tick see it, before planning it",
        )
    return ticket


def _not_planning(conn: sqlite3.Connection, key: str) -> None:
    """Refuse while a plan run for `key` is running: its plan would land after the operator's word.

    Raises:
        Refused: (`bad_plan`) a plan run for `key` is running.
    """
    running = db.running_run_of(conn, key)
    if running is not None and running.kind == RunKind.PLAN:
        raise Refused(
            "bad_plan",
            f"plan run {running.id} for {key} is running; wait for it to end, then decide on its plan",
        )


class NewestPlan(TypedDict):
    """A ticket's newest plan as the overseer's state block carries it: never its text (DESIGN §25)."""

    id: int
    status: str
    created_at: str


class PlanState(TypedDict):
    """A ticket's `plan` key in the overseer's state block (DESIGN §25, Phases and the overseer's part).

    `changes_asked` is an operator message newer than the newest plan and than the latest plan run's start, while that
    plan is not approved: a reply the planner has not read. `blocked` is the latest plan run ending `blocked` with no
    operator message since.
    """

    needed: bool
    attempts: int
    limit: int
    newest: NewestPlan | None
    changes_asked: bool
    blocked: bool


def state_section(
    conn: sqlite3.Connection,
    policy: Policy,
    ticket: records.Ticket,
    *,
    attempts: int,
    limit: int,
) -> PlanState | None:
    """Return a ticket's plan for the overseer's state block, or None when plans do not touch it.

    A ticket that needs no plan, has none, and had no plan run has no `plan` key, so with `policy.plan` off the block
    is as it was before plans (DESIGN §25). Nor has a ticket with a branch, which is never planned (`ask`): its plan,
    approved or never wanted, decides nothing the overseer does.
    """
    if ticket.branch:
        return None
    key = ticket.key
    needed_now = needed(policy.plan, ticket.plan_setting)
    newest = records.select(records.Plan).where("ticket_key = ?", key).order_by("id DESC").limit(1).one(conn)
    run = (
        records.select(records.Run)
        .where("ticket_key = ? AND kind = ? AND id > ?", key, RunKind.PLAN, ticket.forgotten_run_id or 0)
        .order_by("id DESC")
        .limit(1)
        .one(conn)
    )
    if not needed_now and newest is None and run is None and attempts == 0:
        return None
    replied = sql.execute(conn, _replied(ticket)).fetchone()[0]
    blocked = (
        run is not None
        and run.status is RunStatus.BLOCKED
        and (replied is None or run.ended_at is None or replied <= run.ended_at)
    )
    section: PlanState = {
        "needed": needed_now,
        "attempts": attempts,
        "limit": limit,
        "newest": None
        if newest is None
        else {"id": newest.id, "status": newest.status, "created_at": newest.created_at},
        "changes_asked": changes_asked(conn, ticket) is not None,
        "blocked": blocked,
    }
    return section


def waits(conn: sqlite3.Connection, ticket: records.Ticket) -> bool:
    """Return whether the ticket's newest plan waits on the operator: proposed, no planner at work, no changes asked.

    A `plan_review` item stays on the attention list until the next tick, so the web UI reads this to tell one the
    operator has answered since, by approving, skipping, or asking for changes.

    Returns:
        True while the newest plan waits on the operator's word.
    """
    newest = records.select(records.Plan).where("ticket_key = ?", ticket.key).order_by("id DESC").limit(1).one(conn)
    if newest is None or newest.status is not PlanStatus.PROPOSED:
        return False
    running = db.running_run_of(conn, ticket.key)
    if running is not None and running.kind == RunKind.PLAN:
        return False
    return changes_asked(conn, ticket) is None


def changes_asked(conn: sqlite3.Connection, ticket: records.Ticket) -> str | None:
    """Return when the operator asked for changes no planner has read, or None if they have not.

    That is their latest message on the ticket when it is newer than its current plan and than its latest plan run's
    start, as the overseer's state block reads it (`state_section`), so the web UI says what the overseer will act on.
    A message after an approval asks for none: it rides the `implement` (DESIGN §25).

    Returns:
        The message's time as the journal holds it, or None.
    """
    key = ticket.key
    newest = records.select(records.Plan).where("ticket_key = ?", key).order_by("id DESC").limit(1).one(conn)
    if newest is not None and newest.status is PlanStatus.APPROVED:
        return None
    latest_run = (
        sql.select("max(started_at)")
        .from_("runs")
        .where("ticket_key = ? AND kind = ? AND id > ?", key, RunKind.PLAN, ticket.forgotten_run_id or 0)
    )
    started = sql.execute(conn, latest_run).fetchone()[0]
    replied = sql.execute(conn, _replied(ticket)).fetchone()[0]
    since = max(
        newest.created_at if newest is not None and newest.status is not PlanStatus.SUPERSEDED else "",
        str(started) if started is not None else "",
    )
    return replied if replied is not None and since and replied > since else None


def _replied(ticket: records.Ticket) -> sql.Select:
    # When the operator last wrote on the ticket since its last forget, but for a verb's instruction, such as a feedback
    # plan's approval, which answers no question and asks for no change: one row, None when they have not.
    return (
        sql.select("max(at)")
        .from_("messages")
        .where("subject_kind = ? AND subject_id = ?", conversation.TICKET, ticket.key)
        .where("source = 'operator' AND id > ?", ticket.forgotten_message_id or 0)
        .where("coalesce(submission, '') NOT GLOB ?", f"{conversation.INSTRUCTION}*")
    )


def awaiting(conn: sqlite3.Connection) -> list[conversation.Awaiting]:
    """Return every public, open ticket whose latest plan run ended `blocked` and whose question waits on a reply.

    The planner cannot comment on the ticket or label it, so its question is a worker message on a public ticket too,
    and the harness raises it as a started ticket's (DESIGN §25). A started ticket's are `conversation.awaiting`'s.

    Returns:
        Each ticket's question, by key.
    """
    found: list[conversation.Awaiting] = []
    blocked = (
        sql.select("r.ticket_key, r.id")
        .from_("runs r")
        .join("tickets t ON t.key = r.ticket_key")
        .where("t.done = 0 AND r.id > coalesce(t.forgotten_run_id, 0) AND r.status = 'blocked'")
        .where("r.id = (SELECT max(id) FROM runs WHERE ticket_key = r.ticket_key AND kind = ?)", RunKind.PLAN)
        .where(
            "NOT EXISTS (SELECT 1 FROM starts s WHERE s.subject_kind = ? AND s.subject_id = r.ticket_key)",
            conversation.TICKET,
        )
        .order_by("r.ticket_key")
    )
    rows = sql.execute(conn, blocked).fetchall()
    for row in rows:
        key = str(row[0])
        asked = question(conn, key)
        if asked is not None and asked.run_id == row[1]:
            found.append(conversation.Awaiting(key, asked.id, asked.body))
    return found


def question(conn: sqlite3.Connection, key: str) -> records.Message | None:
    """Return a ticket's latest question when a plan run asked it and no operator message came after it.

    On a public ticket this is the one question canopy holds rather than the tracker (DESIGN §25).

    Returns:
        The question's message, or None.
    """
    found = conversation.latest_question(conn, key)
    if found is None or found.run_id is None:
        return None
    run = db.get_run(conn, found.run_id)
    return found if run is not None and run["kind"] == RunKind.PLAN else None


def path_for(state_dir: Path, key: str, run_id: int) -> Path:
    """Where the plan the run `run_id` wrote for `key` is kept. Built from the key and the id, never read from a row.

    Returns:
        `<state_dir>/plans/<key>/<run_id>.md`. The file may not exist.

    Raises:
        ValueError: `key` is not a ticket key, so it might hold a path separator or `..`.
    """
    return dir_for(state_dir, key) / file_name(run_id)


def dir_for(state_dir: Path, key: str) -> Path:
    """Where the plans written for `key` are kept. Built from the key, never read from a row.

    Returns:
        `<state_dir>/plans/<key>`. The directory may not exist.

    Raises:
        ValueError: `key` is not a ticket key, so it might hold a path separator or `..`.
    """
    if len(key) > MAX_KEY or KEY_RE.fullmatch(key) is None:
        raise ValueError(f"{key[:MAX_KEY]!r} is not a ticket key")
    return state_dir / DIR_NAME / key


def file_name(run_id: int) -> str:
    """The name of the plan the run `run_id` wrote, in its ticket's directory.

    Returns:
        `<run_id>.md`.
    """
    return f"{run_id}.md"


def original_name(run_id: int) -> str:
    """The name of the copy of the plan the run `run_id` wrote, as its planner wrote it, in its ticket's directory.

    Returns:
        `<run_id>.original.md`.
    """
    return f"{run_id}.original.md"


def write(state_dir: Path, key: str, run_id: int, text: str) -> Written:
    """Write the plan the run `run_id` wrote for `key` to its file, and its original beside it, operator-only.

    Either file left by a write that failed has no row, so is never read.

    Returns:
        The file's hash and size, for its row.

    Raises:
        PlanFileError: `plans/` or the ticket's directory is a symlink, not a directory, or not the operator's alone; or
            either file's name is taken, by an earlier file or anything else, which is left as it is.
    """
    path = path_for(state_dir, key, run_id)
    written = write_new(state_dir / DIR_NAME, key, path.name, text)
    write_new(state_dir / DIR_NAME, key, original_name(run_id), text)
    return written


def write_new(top: Path, sub: str, name: str, text: str, *, what: str = "plan") -> Written:
    """Write `text` to a new file `<top>/<sub>/<name>`, readable only by the operator, as a plan's file is written.

    A task's report is kept the same way (DESIGN §36). `what` names the file in what it raises.

    Returns:
        The file's hash and size.

    Raises:
        PlanFileError: `top` or `<top>/<sub>` is a symlink, not a directory, or not the operator's alone; or the file's
            name is taken, by an earlier file or anything else, which is left as it is.
    """
    data = text.encode("utf-8")
    top_fd = _private_dir(None, top, what=what)
    try:
        sub_fd = _private_dir(top_fd, sub, what=what)
    finally:
        os.close(top_fd)
    try:
        _link_new(sub_fd, name, data, what=what)
    finally:
        os.close(sub_fd)
    return Written(sha256=hashlib.sha256(data).hexdigest(), size=len(data))


def read(path: Path) -> Reading:
    """Read the plan at `path`, bounded, without following a link at it.

    Returns:
        Its text when the file is a regular file of non-blank UTF-8 within `MAX_CHARS`; else why it is not. The hash
        and size are of the whole file, set whenever it could be read.
    """
    try:
        # Non-blocking, so a FIFO in the plan's place cannot hold the read open; it is refused below.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return Reading(None, None, None, "missing")
    except OSError:
        # A symlink at `path` fails with ELOOP; anything else is unreadable.
        kind: Problem = "not a regular file" if path.is_symlink() else "unreadable"
        return Reading(None, None, None, kind)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        return Reading(None, None, None, "not a regular file")
    with os.fdopen(fd, "rb") as f:
        try:
            head, digest, size = _hashed(f)
        except OSError:
            return Reading(None, None, None, "unreadable")
    problem: Problem | None = None
    text: str | None = None
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError:
        # A file cut at the bound may end mid-character; it is over the bound either way.
        problem = "over the bound" if size > _MAX_BYTES else "not UTF-8"
    if text is not None and (size > _MAX_BYTES or len(text) > MAX_CHARS):
        problem = "over the bound"
    elif text is not None and not text.strip():
        problem = "empty"
    return Reading(text if problem is None else None, digest, size, problem)


def record(
    conn: sqlite3.Connection,
    key: str,
    run_id: int,
    written: Written,
    *,
    event: Callable[[int, str | None], db.Event | None] | None = None,
    no_review: str | None = None,
    effort: PlanEffort | None = None,
    epic_plan_id: int | None = None,
) -> records.Plan:
    """Record the plan the run `run_id` wrote for `key`, after its file, as `proposed`. It supersedes the current one.

    `no_review` is its planner's reason for saying the plan needs no review, under `policy.planner_may_approve`: the
    plan is then recorded `approved` as the planner wrote it, the planner's approval (`PLANNER`), not the operator's
    (DESIGN §25). Unless the operator has had a word on the ticket's plan: it replaces a current plan, which they were
    asked to approve or approved, or the ticket's own setting asks for a plan. Then it waits on them, as any plan does.
    `event` builds the plan's event from its id and that reason when it held, recorded in the same transaction (§20).
    `effort` is its planner's estimate of how much work the plan is, kept to show beside it. `epic_plan_id` is the
    approved epic plan its planner read, when its ticket is a member of an epic (DESIGN §43).

    Returns:
        The plan's row.
    """
    with db.transaction(conn):
        reason = no_review if planner_may_approve(conn, key) else None
        supersede(conn, key)
        approved = reason is not None
        now = db.now()
        seen = ticket_text(conn, key) if approved else None
        [plan] = records.insert(
            records.Plan,
            ticket_key=key,
            run_id=run_id,
            created_at=now,
            status=PlanStatus.APPROVED if approved else PlanStatus.PROPOSED,
            sha256=written.sha256,
            size=written.size,
            approved_sha256=written.sha256 if approved else None,
            approved_at=now if approved else None,
            approved_channel=PLANNER if approved else None,
            approved_reason=reason,
            effort=effort,
            approved_title_sha256=seen.title_sha256 if seen is not None else None,
            approved_body_sha256=seen.body_sha256 if seen is not None else None,
            epic_plan_id=epic_plan_id,
        ).returned(conn)
        built = event(plan.id, reason) if event is not None else None
        if built is not None:
            db.record_event(conn, built)
    return plan


def planner_may_approve(conn: sqlite3.Connection, key: str) -> bool:
    """Whether `key`'s next plan may be approved on its planner's word: the operator has had none on its plan yet.

    Returns:
        False when the ticket has a current plan, which they were asked to approve or approved, or its own setting
        asks for a plan (`ask`).
    """
    ticket = db.get_ticket(conn, key)
    return current(conn, key) is None and (ticket is None or ticket.plan_setting is not PlanSetting.PLAN)


def current(conn: sqlite3.Connection, key: str) -> records.Plan | None:
    """The ticket's current plan: the one not superseded, waiting or approved.

    Returns:
        The plan's row, or None when the ticket has none.
    """
    return records.select(records.Plan).where("ticket_key = ? AND status != ?", key, PlanStatus.SUPERSEDED).one(conn)


def history(conn: sqlite3.Connection, key: str) -> list[records.Plan]:
    """Every plan of the ticket, superseded ones included.

    Returns:
        The plans' rows, oldest first.
    """
    return records.select(records.Plan).where("ticket_key = ?", key).order_by("id").all(conn)


def unrevised(
    conn: sqlite3.Connection,
    subject: conversation.Ref,
    replaced: Replaced,
    *,
    seed: str,
    text: str,
    started_at: str,
) -> bool:
    """Whether a revision's planner left its seeded file as it was, though the operator asked for changes (DESIGN §25).

    A planner that replaces a plan starts with its file holding that plan's text, `seed`, and edits it. Left as it was,
    the file still reads as a plan, so it is no revision when the operator wrote on `subject` after the plan it replaces
    was made, or last approved, and by the time the run started: the messages the planner was given. An epic's reply
    after its plan's approval asks for a new one, so it counts as any other.

    Returns:
        True when `text` is `seed` and the operator wrote since, but for a verb's instruction.
    """
    if text != seed:
        return False
    since = max(replaced.created_at, replaced.approved_at or "")
    wrote = (
        sql.select("1")
        .from_("messages")
        .where("subject_kind = ? AND subject_id = ? AND source = 'operator'", subject.kind, subject.id)
        .where("at > ? AND at <= ?", since, started_at)
        .where("coalesce(submission, '') NOT GLOB ?", f"{conversation.INSTRUCTION}*")
        .limit(1)
    )
    return sql.execute(conn, wrote).fetchone() is not None


def approve(
    conn: sqlite3.Connection,
    state_dir: Path,
    key: str,
    *,
    channel: str,
    dispatch_lock: Path,
    note: str | None = None,
) -> records.Plan:
    """Approve the ticket's current plan as its file stands now, the operator's edits included, recording its hash.

    Beside it goes the hash of the ticket's title and of its description as last observed, so the harness warns while
    either differs (`ticket_changed`), and approving again is how the operator says the plan still fits. So it is for a
    member whose epic's plan changed since (DESIGN §43): approving again clears its notice, and with it `epic_changed`.

    An operator message newer than the plan, asking for changes, does not stop it: an approval before the new plan run
    starts is the operator's later word (DESIGN §25, Approving a plan). With a `note`, the approval writes it on the
    ticket as an operator message, in the same transaction, after a sentence naming the plan: the message is the
    operator's instruction, which the `implement` reads beside the plan, so a small point needs no new plan. Written
    after the approval, it asks for no changes (`changes_asked`), and it answers no question a run asked.

    Returns:
        The approved plan's row.

    Raises:
        Refused: `inside_run` inside one of canopy's own ticks or runs; `bad_plan` while a plan run for the ticket is
            running, when it has no current plan, when that plan is approved and neither its file, the ticket's
            text, nor its epic's plan has changed since, or when its file is missing, not a regular file, unreadable,
            or no longer a plan;
            `bad_body` for a `note` empty or over `MAX_NOTE`.
    """
    conversation.check_operator()
    said = _note(note)
    with lock.hold(dispatch_lock, wait=True), db.transaction(conn):
        _not_planning(conn, key)
        plan = current(conn, key)
        if plan is None:
            raise Refused("bad_plan", f"{key} has no plan waiting to be approved")
        path = path_for(state_dir, key, plan.run_id)
        reading = read(path)
        if (
            plan.status is PlanStatus.APPROVED
            and reading.sha256 == plan.approved_sha256
            and not ticket_changed(conn, plan)
            and epic_changes.pending(conn, key) is None
        ):
            raise Refused(
                "bad_plan",
                f"plan {plan.id} of {key} is approved, and neither its file nor the ticket's text has changed since",
            )
        if reading.problem is not None:
            raise Refused("bad_plan", f"plan {plan.id}'s file {path} is {reading.problem}, so it cannot be approved")
        seen = ticket_text(conn, key)
        [approved] = (
            records.update(records.Plan)
            .set(
                status=PlanStatus.APPROVED,
                approved_sha256=reading.sha256,
                approved_at=db.now(),
                approved_channel=channel,
                approved_reason=None,
                approved_title_sha256=seen.title_sha256 if seen is not None else None,
                approved_body_sha256=seen.body_sha256 if seen is not None else None,
            )
            .where("id = ?", plan.id)
            .returned(conn)
        )
        epic_changes.approved(conn, key)
        if said is not None:
            conversation.write_reply(
                conn,
                conversation.Ref(conversation.TICKET, key),
                approval_note(plan.id, said),
                channel=channel,
                # Distinct for each note: a plan approved again after an edit may carry a note of its own.
                submission=f"plan/{plan.id}/after/{db.latest_message_id(conn)}",
                answers=False,
            )
    return approved


def approval_note(plan_id: int, note: str) -> str:
    """Return the operator message an approval with a note writes: a sentence naming the plan, then the note.

    The plan is named, never quoted: its text is data, and this message is the instruction (TRUST_MODEL T1).

    Returns:
        The message.
    """
    lead = f"Plan {plan_id} is approved. Follow it with these notes, which come first where the two differ:"
    return f"{lead}\n\n{note}"


def _note(note: str | None) -> str | None:
    """The operator's note for an approval, stripped, or None when they gave none.

    Returns:
        The note.

    Raises:
        Refused: (`bad_body`) for a note that is empty or over `MAX_NOTE`.
    """
    if note is None:
        return None
    text = note.strip()
    if not text:
        raise Refused("bad_body", "the note is empty; leave it out to approve with none")
    if len(text) > MAX_NOTE:
        raise Refused("bad_body", f"the note is {len(text)} characters; the most is {MAX_NOTE}")
    return text


def save(
    conn: sqlite3.Connection,
    state_dir: Path,
    key: str,
    plan_id: int,
    text: str,
    *,
    read_sha256: str,
    dispatch_lock: Path,
) -> Written:
    """Write the operator's edit of the ticket's current plan over its file, as the operator's own editor would.

    The web UI's plan editor saves through this (DESIGN §25, Commenting on a plan): under a temporary name renamed into
    place, so a reader never sees half a file, readable only by the operator, refusing a file that is not regular. An
    approved plan whose file is saved needs approving again (`plan_changed`).

    Returns:
        The file's hash and size as saved.

    Raises:
        Refused: `inside_run` inside one of canopy's own runs; `bad_plan` while a plan run for the ticket is running,
            when `plan_id` is not its current plan, when the file is missing or not a regular file, when it changed
            since the editor read it, by `read_sha256`, or when `text` is not a plan: empty or over `MAX_CHARS`.
    """
    conversation.check_operator()
    if not text.strip() or len(text) > MAX_CHARS:
        raise Refused("bad_plan", f"a plan is 1 to {MAX_CHARS:,} characters, not all whitespace")
    with lock.hold(dispatch_lock, wait=True), db.transaction(conn):
        _not_planning(conn, key)
        plan = current(conn, key)
        if plan is None or plan.id != plan_id:
            raise Refused("bad_plan", f"plan {plan_id} is not {key}'s current plan, so it is not edited")
        path = path_for(state_dir, key, plan.run_id)
        reading = read(path)
        if reading.problem in ("missing", "not a regular file", "unreadable"):
            raise Refused("bad_plan", f"plan {plan.id}'s file {path} is {reading.problem}, so it is not saved over")
        if reading.sha256 != read_sha256:
            raise Refused(
                "bad_plan",
                f"plan {plan.id}'s file {path} changed since it was read; read it again before saving",
            )
        try:
            return _replace(state_dir, key, path.name, text)
        except PlanFileError as e:
            raise Refused("bad_plan", str(e)) from None


def approved_text(state_dir: Path, plan: records.Plan) -> str | None:
    """The text of an approved plan, if its file still has the hash the operator approved.

    Returns:
        The text, or None when the plan is not approved or its file is missing, unreadable, or no longer as approved:
        what `implement` and `resume` refuse as `plan_changed`.
    """
    if plan.status is not PlanStatus.APPROVED:
        return None
    reading = read(path_for(state_dir, plan.ticket_key, plan.run_id))
    return reading.text if reading.sha256 == plan.approved_sha256 else None


def approved_of(conn: sqlite3.Connection, key: str) -> records.Plan | None:
    """The ticket's approved plan, the one a worker follows, if it has one.

    Returns:
        The plan's row, or None when the ticket's current plan is waiting, or it has none.
    """
    plan = current(conn, key)
    return plan if plan is not None and plan.status is PlanStatus.APPROVED else None


@dataclass(frozen=True)
class TicketText:
    """A ticket's text as the tracker connector last observed it, hashed, as an approval records it (DESIGN §25)."""

    #: The SHA-256, hex, of its title, stripped.
    title_sha256: str
    #: The same of its description, the body the tracker gives it, acceptance criteria and all.
    body_sha256: str


def ticket_text(conn: sqlite3.Connection, key: str) -> TicketText | None:
    """The ticket's title and description as the tracker connector last observed them, hashed.

    Returns:
        Their hashes, or None when no source has observed the ticket.
    """
    seen = records.select(records.ObservedTicket).where("key = ?", key).one(conn)
    if seen is None:
        return None
    return TicketText(title_sha256=_text_digest(seen.title), body_sha256=_text_digest(seen.body))


def ticket_changed(conn: sqlite3.Connection, plan: records.Plan) -> list[TicketPart]:
    """What of the ticket's text differs, as last observed, from what it was when its approved plan was approved.

    An approval that recorded no text, from before canopy recorded it or of a ticket not observed then, is never
    stale, nor is one whose ticket is not observed now: only two observations that differ say the ticket changed. The
    harness raises `ticket_changed` while it has, warning the operator that the plan was written for a ticket that no
    longer reads so, until they approve it again, plan anew, or skip it (DESIGN §25, Approving a plan). Nothing is
    refused on it: the `implement` goes ahead on the plan they approved.

    Returns:
        `title`, `description`, or both, in that order, as the warning names them; empty when neither changed, or the
        plan is not approved.
    """
    if plan.status is not PlanStatus.APPROVED or plan.approved_title_sha256 is None:
        return []
    seen = ticket_text(conn, plan.ticket_key)
    if seen is None:
        return []
    changed: list[TicketPart] = []
    if seen.title_sha256 != plan.approved_title_sha256:
        changed.append("title")
    if seen.body_sha256 != plan.approved_body_sha256:
        changed.append("description")
    return changed


def _text_digest(text: str) -> str:
    # Stripped, so a connector that trims what another keeps, or a trailing newline, is no change of the ticket's.
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def outline(text: str) -> list[str]:
    """A plan's outline: its markdown headings, outside fenced code blocks, as written, in order.

    Returns:
        At most `MAX_OUTLINE` heading lines, each cut at `MAX_HEADING` characters, without control characters.
    """
    found: list[str] = []
    for line in unfenced(text):
        heading = heading_of(line)
        if heading is not None:
            found.append(heading[:MAX_HEADING])
            if len(found) == MAX_OUTLINE:
                break
    return found


def unfenced(text: str) -> Iterator[str]:
    """Yield a plan's lines outside fenced code blocks, as written, the fences' own lines left out too.

    Yields:
        Each line that is not in a fenced code block, nor opens or closes one, in order.
    """
    fence = ""
    for line in text.splitlines():
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        marker = _FENCE_RE.match(stripped) if indent <= _MAX_INDENT else None
        if fence:
            if marker is not None and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence):
                fence = ""
            continue
        if marker is not None:
            fence = marker.group(1)
            continue
        yield line


def heading_of(line: str) -> str | None:
    """Return a line outside fenced code as a markdown heading, if it is one.

    Returns:
        The heading, its `#`s included, its indent and trailing spaces dropped and every control character a space;
        None when the line is no heading.
    """
    stripped = line.lstrip(" ")
    if len(line) - len(stripped) > _MAX_INDENT or not _HEADING_RE.match(stripped):
        return None
    return "".join(c if c.isprintable() else " " for c in stripped.rstrip())


def supersede(conn: sqlite3.Connection, key: str) -> int | None:
    """Supersede the ticket's current plan, waiting or approved, if it has one. Call inside a transaction.

    Returns:
        The superseded plan's id, or None when the ticket had no current plan.
    """
    superseding = (
        records.update(records.Plan)
        .set(status=PlanStatus.SUPERSEDED)
        .where("ticket_key = ? AND status != ?", key, PlanStatus.SUPERSEDED)
        .returning("id")
    )
    row = superseding.run(conn).fetchone()
    return int(row[0]) if row is not None else None


def _private_dir(parent_fd: int | None, path: Path | str, *, what: str = "plan") -> int:
    """Open the directory `path`, made operator-only if it is missing, refusing one that is not the operator's alone.

    With `parent_fd`, `path` is a name in that directory, so a directory swapped for a link after its parent was checked
    is never followed.

    Returns:
        A descriptor of the directory, which the caller closes.

    Raises:
        PlanFileError: `path` is a symlink, not a directory, or not private to the operator (`logs.private_dir`).
    """
    with contextlib.suppress(FileExistsError):
        os.mkdir(path, 0o700, dir_fd=parent_fd)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    except OSError as e:
        raise PlanFileError(f"{path} is not a directory canopy made: {e.strerror}") from None
    st = os.fstat(fd)
    if st.st_uid != os.getuid() or st.st_mode & 0o077:
        os.close(fd)
        raise PlanFileError(f"{path} is not private to you, so canopy writes no {what} in it")
    return fd


def _link_new(dir_fd: int, name: str, data: bytes, *, what: str = "plan") -> None:
    """Write `data` to a new file `name` in the directory `dir_fd`: no reader sees half of it, and nothing is replaced.

    Raises:
        PlanFileError: `name` is taken.
    """
    temporary = f".{name}.{secrets.token_hex(8)}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dir_fd)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        # A link, not a rename: a rename would replace a file already at `name`.
        os.link(temporary, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd, follow_symlinks=False)
    except FileExistsError:
        raise PlanFileError(f"a {what} named {name} is already there, so canopy leaves it as it is") from None
    finally:
        os.unlink(temporary, dir_fd=dir_fd)


def _replace(state_dir: Path, key: str, name: str, text: str) -> Written:
    """Write `text` over the plan file `name` in the ticket's directory: a temporary file, then renamed into place.

    Returns:
        The file's hash and size as written.

    Raises:
        PlanFileError: `plans/` or the ticket's directory is not the operator's own, or the file could not be written.
    """
    data = text.encode("utf-8")
    plans_fd = _private_dir(None, state_dir / DIR_NAME)
    try:
        ticket_fd = _private_dir(plans_fd, key)
    finally:
        os.close(plans_fd)
    temporary = f".{name}.{secrets.token_hex(8)}.tmp"
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=ticket_fd)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        # A rename replaces the name itself, never what a link there names.
        os.rename(temporary, name, src_dir_fd=ticket_fd, dst_dir_fd=ticket_fd)
    except OSError as e:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=ticket_fd)
        raise PlanFileError(f"the plan was not saved: {e.strerror}") from None
    finally:
        os.close(ticket_fd)
    return Written(sha256=hashlib.sha256(data).hexdigest(), size=len(data))


def _hashed(f: IO[bytes]) -> tuple[bytes, str, int]:
    """Read all of `f`, hashing every byte and keeping the first `_MAX_BYTES` and one more.

    Returns:
        The bytes kept, the whole file's SHA-256, hex, and its size.
    """
    digest = hashlib.sha256()
    head = bytearray()
    size = 0
    while chunk := f.read(_CHUNK):
        digest.update(chunk)
        size += len(chunk)
        if len(head) <= _MAX_BYTES:
            head += chunk[: _MAX_BYTES + 1 - len(head)]
    return bytes(head), digest.hexdigest(), size
