"""Plans before implementing (DESIGN §25, ROADMAP M44): each plan's file on disk, and its row in the journal.

A plan's text is a markdown file of its own, `<state_dir>/plans/<KEY>/<run>.md`, named for the plan run that wrote it,
so the operator reads, greps, and edits it with their own tools. The journal's `plans` row holds what canopy decides
by: the plan's status, the file's hash as written, and the hash the operator approved. A ticket has at most one plan
that is not superseded, its current plan, waiting (`proposed`) or `approved`.

Whether a ticket needs a plan is its own setting, set only by the operator (`ask`, `skip`), or with none
`policy.plan` (`needed`), unless a triage waived it (`waiver`, M55): a `needs-plan` run's validated `trivial` verdict,
recorded as a journal fact in force while the ticket's setting is unset and no forget came after it. The operator's
verbs here, asking for a plan, skipping it, and approving one, are every channel's: each refuses inside one of canopy's
own runs, and holds the dispatch lock, so a dispatch reads a ticket's plans either before the verb or after it.

A file is written once and never overwritten or deleted: under a temporary name in the ticket's directory, then linked
to its own, which fails if the name is taken. `plans/` and each ticket's directory are operator-only, and one that is
not, or a symlink, refuses the write. Every read opens a regular file without following a link and takes at most
`MAX_CHARS` of UTF-8; its hash is of the whole file, so a file over the bound is not a plan and never matches a hash.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import secrets
import stat
from dataclasses import dataclass
from typing import IO, TYPE_CHECKING, Literal, NotRequired, TypedDict

from canopy.core import contract, conversation, db, records
from canopy.core.conversation import KEY_RE, MAX_KEY, Refused
from canopy.core.vocab import PlanSetting, PlanStatus, RunKind, RunStatus
from canopy.infra import lock

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from pathlib import Path

    from canopy.core.config import Policy

# What a planner can write in one message and an operator can read before approving (DESIGN §25, The prompt).
MAX_CHARS = 100_000
DIR_NAME = "plans"
# A copy of a plan in a run's working directory: in a worker's, the approved plan it follows, and in a plan run's desk,
# the plan it replaces (DESIGN §25, The worker's copy). Written fresh for each run and removed before its slots go back.
COPY = ".canopy-plan.md"
REPLACED = COPY
# The file a planner writes its plan to in its desk, the one file its definition lets it edit (DESIGN §25).
# `.agents/agents/canopy-planner.md` names it too.
WRITTEN = ".canopy-new-plan.md"
# A plan's outline in a worker's prompt: its markdown headings outside fenced code, at most this many, each cut at
# `MAX_HEADING` characters (DESIGN §25, Workers follow the plan).
MAX_OUTLINE = 200
MAX_HEADING = 200
#: A triage's reason is one line, cut at this many characters: its run's report, and its waiver's reason (DESIGN §25).
MAX_TRIAGE_REASON = 300
# The most bytes `MAX_CHARS` characters of UTF-8 can take: one more and the file is over the bound however it decodes.
_MAX_BYTES = 4 * MAX_CHARS
_CHUNK = 64 * 1024

# CommonMark's: an ATX heading, and a fence's opening or closing marker, each indented at most three spaces.
_HEADING_RE = re.compile(r"#{1,6}(?:[ \t]|$)")
_FENCE_RE = re.compile(r"(`{3,}|~{3,})")
_MAX_INDENT = 3

# Why a file is not a plan, as `canopy show` and the refusals say it.
type Problem = Literal["missing", "not a regular file", "unreadable", "not UTF-8", "empty", "over the bound"]


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


def needs_plan(conn: sqlite3.Connection, policy: str, ticket: records.Ticket | None) -> bool:
    """Whether a ticket waits on an approved plan before its implement: `needed`, and no triage waived it (§25).

    Returns:
        True when `needed` says so for the ticket's own setting and `policy`, `policy.plan`, and no waiver is in force.
    """
    if ticket is None:
        return needed(policy, None)
    return needed(policy, ticket.plan_setting) and waiver(conn, ticket) is None


def waiver(conn: sqlite3.Connection, ticket: records.Ticket) -> records.PlanWaiver | None:
    """The waiver a triage gave the ticket's plan, while it is in force (DESIGN §25, Triage before a plan).

    It is in force while the ticket's own setting is unset, so asking for a plan undoes it and `--skip` puts the
    operator's own word in its place, and while no forget came after its triage run, so `canopy forget` ends it. Derived
    from the journal each time it is read; nothing updates a waiver.

    Returns:
        The waiver's row, or None when the ticket has none in force.
    """
    if ticket.plan_setting is not None:
        return None
    return records.fetch_one(
        conn,
        records.PlanWaiver,
        "SELECT * FROM plan_waivers WHERE ticket_key = ? AND run_id > ? ORDER BY id DESC LIMIT 1",
        (ticket.key, ticket.forgotten_run_id or 0),
    )


def record_waiver(conn: sqlite3.Connection, key: str, run_id: int, reason: str) -> None:
    """Record that the triage run `run_id` waived `key`'s plan for `reason`. Call inside the run's closing transaction.

    Only `_run` calls it, from a triage's validated `done` `trivial` result (DESIGN §25): no agent and no command writes
    a waiver.
    """
    conn.execute(
        "INSERT INTO plan_waivers (ticket_key, run_id, reason, at) VALUES (?, ?, ?, ?)", (key, run_id, reason, db.now())
    )


@dataclass(frozen=True)
class Triage:
    """A ticket's triage run (DESIGN §25) as the web UI's plan card tells it: how it ended and what it judged."""

    #: The `needs-plan` run. A ticket is triaged at most once, so this is its only one.
    run_id: int
    #: How it ended, or `running` while it reads.
    status: RunStatus
    #: What a run that ended `done` judged; None while it runs, or for one that ended otherwise, whatever it printed.
    verdict: Literal["trivial", "plan"] | None
    #: Its one-sentence reason, or the harness's note for a run that judged nothing: model text, from the ticket.
    reason: str
    #: When it ended, or when it started while it runs.
    at: str


def triage(conn: sqlite3.Connection, key: str) -> Triage | None:
    """The ticket's triage run, before a forget too, as its stored result says it ended.

    Returns:
        The triage, or None when the ticket has had none.
    """
    row = conn.execute(
        "SELECT id, status, started_at, ended_at, result_json FROM runs WHERE ticket_key = ? AND kind = ? "
        "ORDER BY id DESC LIMIT 1",
        (key, RunKind.NEEDS_PLAN),
    ).fetchone()
    if row is None:
        return None
    run_id, status, started, ended, result_json = row
    stored = contract.stored_object(result_json)
    ended_as = RunStatus(status)
    return Triage(
        run_id=int(run_id),
        status=ended_as,
        verdict=_verdict(stored.get("verdict")) if ended_as is RunStatus.DONE else None,
        reason=contract.stored_note(stored),
        at=str(ended or started),
    )


def _verdict(value: object) -> Literal["trivial", "plan"] | None:
    match value:
        case "trivial":
            return "trivial"
        case "plan":
            return "plan"
        case _:
            return None


def triage_refusal(conn: sqlite3.Connection, policy: Policy, key: str) -> tuple[str, str] | None:  # noqa: PLR0911
    """Return the guard and reason that refuse a triage of `key` now, or None when one is due (DESIGN §25).

    A triage is due when triage is on, the ticket needs a plan by the policy alone, and it has no branch, no plan run,
    no triage run, and no split's children. So a ticket is triaged at most once, before its first plan, and the bound
    is derived from its runs and never reset (D030), not even by `canopy forget`.

    Returns:
        `triage_off`, `triaged`, or `bad_triage` with why, or None.
    """
    if policy.plan_triage != "on":
        return "triage_off", 'policy.plan_triage is not "on": dispatch plan for a ticket that needs one'
    triaged = _first_run(conn, key, RunKind.NEEDS_PLAN)
    if triaged is not None:
        return "triaged", f"{key} had triage run {triaged}; a ticket is triaged once, however that ended"
    ticket = db.get_ticket(conn, key)
    setting = ticket.plan_setting if ticket is not None else None
    if setting is PlanSetting.PLAN:
        return "bad_triage", f"the operator asked for {key}'s plan, so it is planned, whatever a triage would say"
    if setting is PlanSetting.SKIP:
        return "bad_triage", f"the operator skipped {key}'s plan, so there is nothing to triage"
    if policy.plan != "approve":
        return "bad_triage", f'policy.plan is not "approve", so {key} needs no plan to triage'
    if ticket is not None and ticket.branch:
        return "bad_triage", f"{key} already has work on {ticket.branch}; a started ticket is not triaged"
    planned = _first_run(conn, key, RunKind.PLAN)
    if planned is not None:
        return "bad_triage", f"{key} had plan run {planned}; a ticket with a plan is not triaged"
    split_into = db.children_of(conn, key)
    if split_into:
        return "bad_triage", f"{key} was split into {', '.join(split_into)}; triage those instead"
    return None


def _first_run(conn: sqlite3.Connection, key: str, kind: RunKind) -> int | None:
    """The id of `key`'s first run of `kind`, before any forget too.

    Returns:
        The run's id, or None if the ticket has had no run of `kind`.
    """
    found = conn.execute("SELECT min(id) FROM runs WHERE ticket_key = ? AND kind = ?", (key, kind)).fetchone()[0]
    return int(found) if found is not None else None


@dataclass(frozen=True)
class Asked:
    """What `ask` or `skip` did: the plan it superseded, if any, and whether the ticket's setting was already so."""

    superseded: int | None
    already: bool
    #: The triage run whose waiver the verb undid, or replaced with the operator's own `skip` (DESIGN §25).
    waived: int | None = None


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
        waived = waiver(conn, ticket)
        superseded = supersede(conn, key)
        already = ticket.plan_setting is PlanSetting.PLAN and superseded is None
        conn.execute("UPDATE tickets SET plan_setting = ? WHERE key = ?", (PlanSetting.PLAN, key))
    return Asked(superseded=superseded, already=already, waived=waived.run_id if waived is not None else None)


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
        waived = waiver(conn, ticket)
        superseded = supersede(conn, key)
        already = ticket.plan_setting is PlanSetting.SKIP and superseded is None
        conn.execute("UPDATE tickets SET plan_setting = ? WHERE key = ?", (PlanSetting.SKIP, key))
    return Asked(superseded=superseded, already=already, waived=waived.run_id if waived is not None else None)


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
            "unknown", f"canopy has no record of {key}: start it, or label it and let a tick see it, before planning it"
        )
    return ticket


def _not_planning(conn: sqlite3.Connection, key: str) -> None:
    """Refuse while a plan run for `key` is running: its plan would land after the operator's word.

    Raises:
        Refused: (`bad_plan`) a plan run for `key` is running.
    """
    running = db.running_run_of(conn, key)
    if running is not None and running["kind"] == RunKind.PLAN:
        raise Refused(
            "bad_plan", f"plan run {running['id']} for {key} is running; wait for it to end, then decide on its plan"
        )


class NewestPlan(TypedDict):
    """A ticket's newest plan as the overseer's state block carries it: never its text (DESIGN §25)."""

    id: int
    status: str
    created_at: str


class PlanState(TypedDict):
    """A ticket's `plan` key in the overseer's state block (DESIGN §25, Phases and the overseer's part).

    `changes_asked` is an operator message newer than the newest plan and than the latest plan run's start: a reply the
    planner has not read. `blocked` is the latest plan run ending `blocked` with no operator message since.
    """

    needed: bool
    attempts: int
    limit: int
    newest: NewestPlan | None
    changes_asked: bool
    blocked: bool
    #: With `policy.plan_triage` on, whether a triage is due (`triage_refusal`), so the overseer compares nothing.
    triage_due: NotRequired[bool]
    #: The triage run whose waiver is in force; the ticket then needs no plan (DESIGN §25, Triage before a plan).
    waived: NotRequired[int]


def state_section(
    conn: sqlite3.Connection, policy: Policy, ticket: records.Ticket, *, attempts: int, limit: int
) -> PlanState | None:
    """Return a ticket's plan for the overseer's state block, or None when plans do not touch it.

    A ticket that needs no plan, has none, and had no plan run has no `plan` key, so with `policy.plan` off the block
    is as it was before plans (DESIGN §25, Off unless configured). Triage's facts are there only while triage touches
    the ticket: `triage_due` while it is on, and `waived` while a waiver is in force, which makes the plan not needed.
    """
    key = ticket.key
    waived = waiver(conn, ticket)
    needed_now = needed(policy.plan, ticket.plan_setting)
    newest = records.fetch_one(
        conn, records.Plan, "SELECT * FROM plans WHERE ticket_key = ? ORDER BY id DESC LIMIT 1", (key,)
    )
    run = conn.execute(
        "SELECT * FROM runs WHERE ticket_key = ? AND kind = ? AND id > ? ORDER BY id DESC LIMIT 1",
        (key, RunKind.PLAN, ticket.forgotten_run_id or 0),
    ).fetchone()
    if not needed_now and newest is None and run is None and attempts == 0:
        return None
    replied = conn.execute(
        "SELECT max(at) FROM messages WHERE subject_kind = ? AND subject_id = ? AND source = 'operator' AND id > ?",
        (conversation.TICKET, key, ticket.forgotten_message_id or 0),
    ).fetchone()[0]
    blocked = (
        run is not None
        and run["status"] == "blocked"
        and (replied is None or run["ended_at"] is None or replied <= str(run["ended_at"]))
    )
    section: PlanState = {
        "needed": needed_now and waived is None,
        "attempts": attempts,
        "limit": limit,
        "newest": None
        if newest is None
        else {"id": newest.id, "status": newest.status, "created_at": newest.created_at},
        "changes_asked": changes_asked(conn, ticket) is not None,
        "blocked": blocked,
    }
    if policy.plan_triage == "on":
        section["triage_due"] = triage_refusal(conn, policy, key) is None
    if waived is not None:
        section["waived"] = waived.run_id
    return section


def changes_asked(conn: sqlite3.Connection, ticket: records.Ticket) -> str | None:
    """Return when the operator asked for changes no planner has read, or None if they have not.

    That is their latest message on the ticket when it is newer than its current plan and than its latest plan run's
    start, as the overseer's state block reads it (`state_section`), so the web UI says what the overseer will act on.

    Returns:
        The message's time as the journal holds it, or None.
    """
    key = ticket.key
    newest = records.fetch_one(
        conn, records.Plan, "SELECT * FROM plans WHERE ticket_key = ? ORDER BY id DESC LIMIT 1", (key,)
    )
    started = conn.execute(
        "SELECT max(started_at) FROM runs WHERE ticket_key = ? AND kind = ? AND id > ?",
        (key, RunKind.PLAN, ticket.forgotten_run_id or 0),
    ).fetchone()[0]
    replied = conn.execute(
        "SELECT max(at) FROM messages WHERE subject_kind = ? AND subject_id = ? AND source = 'operator' AND id > ?",
        (conversation.TICKET, key, ticket.forgotten_message_id or 0),
    ).fetchone()[0]
    since = max(
        newest.created_at if newest is not None and newest.status is not PlanStatus.SUPERSEDED else "",
        str(started) if started is not None else "",
    )
    return replied if replied is not None and since and replied > since else None


def awaiting(conn: sqlite3.Connection) -> list[conversation.Awaiting]:
    """Return every public, open ticket whose latest plan run ended `blocked` and whose question waits on a reply.

    The planner cannot comment on the ticket or label it, so its question is a worker message on a public ticket too,
    and the harness raises it as a started ticket's (DESIGN §25). A started ticket's are `conversation.awaiting`'s.

    Returns:
        Each ticket's question, by key.
    """
    found: list[conversation.Awaiting] = []
    rows = conn.execute(
        "SELECT r.ticket_key, r.id FROM runs r JOIN tickets t ON t.key = r.ticket_key "
        "WHERE t.done = 0 AND r.id > coalesce(t.forgotten_run_id, 0) AND r.status = 'blocked' "
        "AND r.id = (SELECT max(id) FROM runs WHERE ticket_key = r.ticket_key AND kind = ?) "
        "AND NOT EXISTS (SELECT 1 FROM starts s WHERE s.subject_kind = ? AND s.subject_id = r.ticket_key) "
        "ORDER BY r.ticket_key",
        (RunKind.PLAN, conversation.TICKET),
    ).fetchall()
    for row in rows:
        key = str(row[0])
        asked = question(conn, key)
        if asked is not None and asked["run_id"] == row[1]:
            found.append(conversation.Awaiting(key, int(asked["id"]), str(asked["body"])))
    return found


def question(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    """Return a ticket's latest question when a plan run asked it and no operator message came after it.

    On a public ticket this is the one question canopy holds rather than the tracker (DESIGN §25).

    Returns:
        The question's message, or None.
    """
    found = conversation.latest_question(conn, key)
    if found is None or found["run_id"] is None:
        return None
    run = db.get_run(conn, int(found["run_id"]))
    return found if run is not None and run["kind"] == RunKind.PLAN else None


def path_for(state_dir: Path, key: str, run_id: int) -> Path:
    """Where the plan the run `run_id` wrote for `key` is kept. Built from the key and the id, never read from a row.

    Returns:
        `<state_dir>/plans/<key>/<run_id>.md`. The file may not exist.

    Raises:
        ValueError: `key` is not a ticket key, so it might hold a path separator or `..`.
    """
    if len(key) > MAX_KEY or KEY_RE.fullmatch(key) is None:
        raise ValueError(f"{key[:MAX_KEY]!r} is not a ticket key")
    return state_dir / DIR_NAME / key / f"{run_id}.md"


def write(state_dir: Path, key: str, run_id: int, text: str) -> Written:
    """Write the plan the run `run_id` wrote for `key` to its file, readable only by the operator.

    Returns:
        The file's hash and size, for its row.

    Raises:
        PlanFileError: `plans/` or the ticket's directory is a symlink, not a directory, or not the operator's alone; or
            the file's name is taken, by an earlier file or anything else, which is left as it is.
    """
    path = path_for(state_dir, key, run_id)
    data = text.encode("utf-8")
    plans_fd = _private_dir(None, state_dir / DIR_NAME)
    try:
        ticket_fd = _private_dir(plans_fd, key)
    finally:
        os.close(plans_fd)
    try:
        _link_new(ticket_fd, path.name, data)
    finally:
        os.close(ticket_fd)
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
    event: Callable[[int], db.Event | None] | None = None,
) -> records.Plan:
    """Record the plan the run `run_id` wrote for `key`, after its file, as `proposed`. It supersedes the current one.

    `event` builds the `plan.proposed` event from the plan's id, recorded in the same transaction (DESIGN §20).

    Returns:
        The plan's row.
    """
    with db.transaction(conn):
        supersede(conn, key)
        [plan] = records.fetch_all(
            conn,
            records.Plan,
            "INSERT INTO plans (ticket_key, run_id, created_at, status, sha256, size) VALUES (?, ?, ?, ?, ?, ?) "
            "RETURNING *",
            (key, run_id, db.now(), PlanStatus.PROPOSED, written.sha256, written.size),
        )
        built = event(plan.id) if event is not None else None
        if built is not None:
            db.record_event(conn, built)
    return plan


def current(conn: sqlite3.Connection, key: str) -> records.Plan | None:
    """The ticket's current plan: the one not superseded, waiting or approved.

    Returns:
        The plan's row, or None when the ticket has none.
    """
    return records.fetch_one(
        conn, records.Plan, "SELECT * FROM plans WHERE ticket_key = ? AND status != ?", (key, PlanStatus.SUPERSEDED)
    )


def history(conn: sqlite3.Connection, key: str) -> list[records.Plan]:
    """Every plan of the ticket, superseded ones included.

    Returns:
        The plans' rows, oldest first.
    """
    return records.fetch_all(conn, records.Plan, "SELECT * FROM plans WHERE ticket_key = ? ORDER BY id", (key,))


def approve(conn: sqlite3.Connection, state_dir: Path, key: str, *, channel: str, dispatch_lock: Path) -> records.Plan:
    """Approve the ticket's current plan as its file stands now, the operator's edits included, recording its hash.

    An operator message newer than the plan, asking for changes, does not stop it: an approval before the new plan run
    starts is the operator's later word (DESIGN §25, Approving a plan).

    Returns:
        The approved plan's row.

    Raises:
        Refused: `inside_run` inside one of canopy's own ticks or runs; `bad_plan` while a plan run for the ticket is
            running, when it has no current plan, when that plan is approved and its file has not changed since, or
            when its file is missing, not a regular file, unreadable, or no longer a plan.
    """
    conversation.check_operator()
    with lock.hold(dispatch_lock, wait=True), db.transaction(conn):
        _not_planning(conn, key)
        plan = current(conn, key)
        if plan is None:
            raise Refused("bad_plan", f"{key} has no plan waiting to be approved")
        path = path_for(state_dir, key, plan.run_id)
        reading = read(path)
        if plan.status is PlanStatus.APPROVED and reading.sha256 == plan.approved_sha256:
            raise Refused("bad_plan", f"plan {plan.id} of {key} is approved, and its file has not changed since")
        if reading.problem is not None:
            raise Refused("bad_plan", f"plan {plan.id}'s file {path} is {reading.problem}, so it cannot be approved")
        [approved] = records.fetch_all(
            conn,
            records.Plan,
            "UPDATE plans SET status = ?, approved_sha256 = ?, approved_at = ?, approved_channel = ? WHERE id = ? "
            "RETURNING *",
            (PlanStatus.APPROVED, reading.sha256, db.now(), channel, plan.id),
        )
    return approved


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
                "bad_plan", f"plan {plan.id}'s file {path} changed since it was read; read it again before saving"
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


def outline(text: str) -> list[str]:
    """A plan's outline: its markdown headings, outside fenced code blocks, as written, in order.

    Returns:
        At most `MAX_OUTLINE` heading lines, each cut at `MAX_HEADING` characters, without control characters.
    """
    found: list[str] = []
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
        if indent <= _MAX_INDENT and _HEADING_RE.match(stripped):
            heading = "".join(c if c.isprintable() else " " for c in stripped.rstrip())
            found.append(heading[:MAX_HEADING])
            if len(found) == MAX_OUTLINE:
                break
    return found


def supersede(conn: sqlite3.Connection, key: str) -> int | None:
    """Supersede the ticket's current plan, waiting or approved, if it has one. Call inside a transaction.

    Returns:
        The superseded plan's id, or None when the ticket had no current plan.
    """
    row = conn.execute(
        "UPDATE plans SET status = ? WHERE ticket_key = ? AND status != ? RETURNING id",
        (PlanStatus.SUPERSEDED, key, PlanStatus.SUPERSEDED),
    ).fetchone()
    return int(row[0]) if row is not None else None


def _private_dir(parent_fd: int | None, path: Path | str) -> int:
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
        raise PlanFileError(f"{path} is not private to you, so canopy writes no plan in it")
    return fd


def _link_new(dir_fd: int, name: str, data: bytes) -> None:
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
        raise PlanFileError(f"a plan named {name} is already there, so canopy leaves it as it is") from None
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
