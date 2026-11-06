"""Epics (DESIGN §43): the operator's submissions, the repositories each one's plan reads, its members, its plans.

Only the operator's channels submit an epic or change its members, each refusing inside a tick or any agent's run
(`inside_run`, TRUST_MODEL T1): the submission is what authorizes an epic's plan runs, and membership is the
operator's word alone. A plan run records the plan it wrote here, as a file in the state directory and a row of its
hashes, `proposed`, never approved: only the operator approves one. A tracker's epic, parent, or sub-issue link never
makes a ticket a member, and membership authorizes no work on it: a member is worked only once a label or a start says
so, as any ticket is. The overseer never reads an epic. `policy.max_epic_tickets` bounds the members of one,
a guard in code (§4). Stopping an epic, the operator's word too, ends its planning and leaves its members alone. A
member's plan whose planner said it departs from the approved plan waits on the operator as `epic_drift` (`drift`).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import conversation, db, epic_outline, plans, records
from canopy.core.conversation import Refused
from canopy.core.vocab import PlanStatus, RunStatus

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from collections.abc import Set as AbstractSet
    from pathlib import Path

    from canopy.core.workspace import Workspace

#: The most an epic's text holds, as an operator message does.
MAX_TEXT = conversation.MAX_OPERATOR
#: A tracker project's key, or a tracker epic's, as a ticket key spells it (DESIGN §18).
KEY_RE = conversation.KEY_RE
MAX_KEY = conversation.MAX_KEY
#: The copy of an approved plan's text, kept beside its file when the operator approves it: what the next approval is
#: compared with, whatever later becomes of the file. Named for the run and the text's hash,
#: `<run>.<sha256>.approved.md`, so an approval retried after one that wrote its copy and then failed finds the copy it
#: would write already there.
APPROVED_SUFFIX = ".approved.md"
#: The copy of a member's epic's approved plan in its planner's desk, read as the operator approved it (DESIGN §43).
EPIC_COPY = ".canopy-epic-plan.md"
#: Where an epic's plans are kept, `<state_dir>/epics/<id>/<run_id>.md`, readable only by the operator, as a
#: ticket's plans are (DESIGN §25, §43).
PLANS_DIR = "epics"


@dataclass(frozen=True)
class Added:
    """What `add` did: the keys it made members, and those already members of this epic."""

    added: Sequence[str]
    already: Sequence[str]
    #: The entries each key was registered against, when the call named some; None when it left them as they were.
    entries: AbstractSet[str] | None = None


@dataclass(frozen=True)
class MemberEpic:
    """A ticket's epic as its planner meets it (DESIGN §43): the epic, its approved plan, and the entries it fulfils."""

    epic_id: int
    #: The epic's latest plan the operator approved.
    plan: records.EpicPlan
    #: The breakdown's entries the member was registered against that the approved plan holds; none for a member of
    #: no entry.
    entries: Sequence[str]
    #: Those it was registered against that a later approval dropped.
    dropped: Sequence[str]


@dataclass(frozen=True)
class Drift:
    """A member's plan that departs from its epic's plan, waiting on the operator to settle it (DESIGN §43)."""

    epic_id: int
    #: The member's plan, which names the epic plan it was written against.
    plan: records.Plan
    #: The requirements and contracts of that epic plan it departs from, as its planner named them.
    ids: Sequence[str]


@dataclass(frozen=True)
class Stopped:
    """What `stop` did: whether the epic was already stopped, and its plan run still working, if one is."""

    already: bool
    running: records.EpicRun | None


@dataclass(frozen=True)
class Approved:
    """What an approval did: the plan approved, and what it changed from the one approved before it, if any."""

    plan: records.EpicPlan
    #: None for the epic's first approved plan.
    change: epic_outline.Change | None


def submit(
    conn: sqlite3.Connection,
    workspace: Workspace,
    text: str,
    *,
    repos: Sequence[str],
    project: str | None,
    tracker_epic: str | None,
    channel: str,
) -> records.Epic:
    """Record the operator's epic, its goal `text`, whose plan reads repositories `repos` (DESIGN §43).

    `repos` may be empty only in a workspace of one repository, which it then reads. `project` names the tracker
    project its breakdown's tickets are filed in, and `tracker_epic` a tracker key whose children are put to the
    operator as suggestions; None for either is none.

    Returns:
        The epic, as recorded.

    Raises:
        Refused: `inside_run` inside a tick or a run, `bad_body` for an empty text or one over `MAX_TEXT` characters,
            `unknown_repo` for a repository the map does not name, or none named in a workspace of several, and
            `bad_key` for a project or a tracker epic that is not a plain key.
        DatabaseError: the row was not recorded, which nothing but a broken journal does.
    """
    conversation.check_operator()
    body = text.strip()
    if not body:
        raise Refused("bad_body", "the epic's text is empty")
    if len(body) > MAX_TEXT:
        raise Refused("bad_body", f"the epic's text is {len(body)} characters; the most is {MAX_TEXT}")
    names = _repositories(workspace, repos)
    for option, value in (("--project", project), ("--tracker-epic", tracker_epic)):
        if value is not None:
            _check_key(value, option)
    with db.transaction(conn):
        insert = records.insert(
            records.Epic,
            text=body,
            project=project,
            tracker_epic=tracker_epic,
            channel=channel,
            submitted_at=db.now(),
        )
        epic_id = int(insert.run(conn).lastrowid or 0)
        rows = records.insert_rows(records.EpicRepo, ("epic_id", "repo"))
        rows.many(conn, [(epic_id, name) for name in names])
    found = get(conn, epic_id)
    if found is None:
        raise sqlite3.DatabaseError("the epic's row was not recorded")
    return found


def get(conn: sqlite3.Connection, epic_id: int) -> records.Epic | None:
    """Return epic `epic_id`, or None if there is none."""
    return records.select(records.Epic).where("id = ?", epic_id).one(conn)


def every(conn: sqlite3.Connection) -> list[records.Epic]:
    """Return every epic, the newest first: none is ever deleted."""
    return records.select(records.Epic).order_by("id DESC").all(conn)


def repos_of(conn: sqlite3.Connection, epic_id: int) -> list[str]:
    """Return the repositories epic `epic_id`'s plan reads, by name, in the order the map gave them."""
    rows = records.select(records.EpicRepo).where("epic_id = ?", epic_id).order_by("rowid").all(conn)
    return [row.repo for row in rows]


def members_of(conn: sqlite3.Connection, epic_id: int) -> list[records.EpicMember]:
    """Return epic `epic_id`'s members, those the operator has not removed, by when each was added."""
    query = records.select(records.EpicMember).where(
        "epic_id = ? AND removed_at IS NULL",
        epic_id,
    )
    return query.order_by("id").all(conn)


def membership(conn: sqlite3.Connection, key: str) -> records.EpicMember | None:
    """Return ticket `key`'s membership of an epic, or None while it is a member of none."""
    query = records.select(records.EpicMember).where("ticket_key = ? AND removed_at IS NULL", key)
    return query.one(conn)


def add(
    conn: sqlite3.Connection,
    epic_id: int,
    keys: Iterable[str],
    *,
    bound: int,
    channel: str,
    entries: Iterable[str] | None = None,
    state_dir: Path | None = None,
) -> Added:
    """Make tickets `keys` members of epic `epic_id`, the operator's word alone (DESIGN §43).

    Every key is added or none is: a refusal leaves the members as they were. A key already a member of this epic
    stays one. `bound` is `policy.max_epic_tickets`, the most members the epic may then hold. `entries`,
    when given, registers every key against those breakdown entries of the epic's approved plan, read from
    `state_dir`, in place of any it had; an empty one registers them against none. None leaves a member's entries as
    they were, and a new member with none.

    Returns:
        The keys it added, in the order given, and those already members.

    Raises:
        Refused: `inside_run` inside a tick or a run, `unknown_epic` for no such epic, `bad_key` for a key
            that is not a ticket key, `other_epic` for a ticket already a member of another, and
            `epic_full` when the members would then be more than `bound`; `no_plan` for entries named before
            any plan was approved, and `unknown_entry` for one the approved plan does not hold.
    """
    conversation.check_operator()
    _check_epic(conn, epic_id)
    wanted = list(dict.fromkeys(keys))
    for key in wanted:
        _check_key(key, "a ticket key")
    with db.transaction(conn):
        # Inside the write's transaction, so an approval cannot replace the outline between the check and the write.
        named = _entries(conn, state_dir, epic_id, entries) if entries is not None else None
        added: list[str] = []
        already: list[str] = []
        for key in wanted:
            found = membership(conn, key)
            if found is None:
                added.append(key)
            elif found.epic_id == epic_id:
                already.append(key)
            else:
                raise Refused("other_epic", f"{key} is a member of epic:{found.epic_id}")
        held = len(members_of(conn, epic_id))
        # Only what it adds is held to the bound: a key already a member stays one after the bound is lowered.
        if added and held + len(added) > bound:
            raise Refused(
                "epic_full",
                f"epic:{epic_id} has {held} members, and policy.max_epic_tickets lets it hold {bound}",
            )
        if added:
            now = db.now()
            rows = records.insert_rows(
                records.EpicMember,
                ("epic_id", "ticket_key", "added_at", "added_channel"),
            )
            rows.many(conn, [(epic_id, key, now, channel) for key in added])
        if named is not None:
            for key in wanted:
                _register(conn, present_member(conn, key), named)
    return Added(added=tuple(added), already=tuple(already), entries=named)


def present_member(conn: sqlite3.Connection, key: str) -> records.EpicMember:
    """Return ticket `key`'s membership, which the caller knows it has.

    Raises:
        DatabaseError: it has none, which nothing but a broken journal makes so.
    """
    found = membership(conn, key)
    if found is None:
        raise sqlite3.DatabaseError(f"{key}'s membership was not recorded")
    return found


def entries_of(conn: sqlite3.Connection, member_id: int) -> list[str]:
    """Return the breakdown entries member `member_id` fulfils, as the operator registered them, by number."""
    rows = records.select(records.EpicMemberEntry).where("member_id = ?", member_id).all(conn)
    return sorted((r.entry for r in rows), key=lambda e: int(e[1:]))


def remove(conn: sqlite3.Connection, epic_id: int, keys: Iterable[str], *, channel: str) -> list[str]:
    """End tickets `keys`' membership of epic `epic_id`, the operator's word alone (DESIGN §43).

    Every key is removed or none is. The rows stay, ended, so what was a member stays to read; the ticket and its work
    are left as they are.

    Returns:
        The keys it removed, in the order given.

    Raises:
        Refused: `inside_run` inside a tick or a run, `unknown_epic` for no such epic, `bad_key` for a key
            that is not a ticket key, and `not_member` for one that is not a member of this epic.
    """
    conversation.check_operator()
    _check_epic(conn, epic_id)
    wanted = list(dict.fromkeys(keys))
    for key in wanted:
        _check_key(key, "a ticket key")
    with db.transaction(conn):
        for key in wanted:
            found = membership(conn, key)
            if found is None or found.epic_id != epic_id:
                raise Refused("not_member", f"{key} is not a member of epic:{epic_id}")
        now = db.now()
        for key in wanted:
            update = records.update(records.EpicMember).set(removed_at=now, removed_channel=channel)
            update.where("epic_id = ? AND ticket_key = ? AND removed_at IS NULL", epic_id, key).run(conn)
    return wanted


def stop(conn: sqlite3.Connection, epic_id: int) -> Stopped:
    """Mark epic `epic_id` stopped, in one transaction with reading its running plan run (DESIGN §43).

    A stopped epic is never planned again: no tick starts a plan run of it, one due is dropped, and a reply to it is
    refused. Its members, their runs, and its plans are left as they are; membership never authorized work. The tick
    checks the mark in the transaction that inserts a plan run, so whichever commits first wins, and the run returned
    here is any run a tick committed first.

    Returns:
        Whether it was already stopped, and its plan run still running, if one is.

    Raises:
        Refused: `inside_run` inside a tick or a run, and `unknown_epic` for no such epic.
    """
    conversation.check_operator()
    with db.transaction(conn):
        epic = get(conn, epic_id)
        if epic is None:
            raise Refused("unknown_epic", f"canopy has no epic:{epic_id}")
        if epic.stopped_at is None:
            records.update(records.Epic).set(stopped_at=db.now()).where("id = ?", epic_id).run(conn)
        running = records.select(records.EpicRun).where("epic_id = ? AND status = ?", epic_id, RunStatus.RUNNING)
        found = running.one(conn)
    return Stopped(already=epic.stopped_at is not None, running=found)


def plan_path(state_dir: Path, epic_id: int, run_id: int) -> Path:
    """Where the plan that run `run_id` of epic `epic_id` wrote is kept: built from the ids, never a row.

    Returns:
        `<state_dir>/epics/<epic_id>/<run_id>.md`. The file may not exist.
    """
    return state_dir / PLANS_DIR / str(epic_id) / plans.file_name(run_id)


def write_plan(state_dir: Path, epic_id: int, run_id: int, text: str) -> plans.Written:
    """Write the plan run `run_id` wrote to its file, once, readable only by the operator (DESIGN §43).

    Returns:
        The file's hash and size, for its row.

    Raises:
        PlanFileError: `epics/` or the epic's directory is not the operator's own, or the name is taken.
    """
    return plans.write_new(state_dir / PLANS_DIR, str(epic_id), plans.file_name(run_id), text)


def record_plan(
    conn: sqlite3.Connection,
    epic_id: int,
    run_id: int,
    written: plans.Written,
) -> records.EpicPlan:
    """Record the plan run `run_id` wrote as epic `epic_id`'s newest, `proposed`, superseding its last.

    An approved plan it supersedes stays readable, as what the next approval is compared with (DESIGN §43).

    Returns:
        The plan, as recorded.

    Raises:
        DatabaseError: the row was not recorded, which nothing but a broken journal does.
    """
    with db.transaction(conn):
        superseded = records.update(records.EpicPlan).set(status=PlanStatus.SUPERSEDED)
        superseded.where("epic_id = ? AND status != ?", epic_id, PlanStatus.SUPERSEDED).run(conn)
        insert = records.insert(
            records.EpicPlan,
            epic_id=epic_id,
            run_id=run_id,
            created_at=db.now(),
            sha256=written.sha256,
            size=written.size,
        )
        plan_id = int(insert.run(conn).lastrowid or 0)
    found = records.select(records.EpicPlan).where("id = ?", plan_id).one(conn)
    if found is None:
        raise sqlite3.DatabaseError("the epic plan's row was not recorded")
    return found


def current_plan(conn: sqlite3.Connection, epic_id: int) -> records.EpicPlan | None:
    """Return epic `epic_id`'s plan waiting on the operator or approved, or None while it has neither."""
    query = records.select(records.EpicPlan).where(
        "epic_id = ? AND status != ?",
        epic_id,
        PlanStatus.SUPERSEDED,
    )
    return query.one(conn)


def plans_of(conn: sqlite3.Connection, epic_id: int) -> list[records.EpicPlan]:
    """Return every plan epic `epic_id` has had, the oldest first."""
    return records.select(records.EpicPlan).where("epic_id = ?", epic_id).order_by("id").all(conn)


def approve(
    conn: sqlite3.Connection,
    state_dir: Path,
    epic_id: int,
    *,
    repos: AbstractSet[str],
    channel: str,
    read_sha256: str | None = None,
) -> Approved:
    """Approve epic `epic_id`'s waiting plan, as its file stands, the operator's edits included (§43).

    Only the operator approves one, and only a `proposed` plan whose ids and breakdown read in the outline's shape, in
    `repos`, and that uses no id an earlier approved plan dropped. A copy of the approved text is kept beside its file,
    as what the next approval is compared with. With `read_sha256`, the file's hash as a page read it, a file changed
    since is refused rather than approved unseen.

    Returns:
        The plan approved, and what it changed from the plan approved before it.

    Raises:
        Refused: `inside_run` inside a tick or a run, `unknown_epic` for no such epic, `planning` while a
            plan run of it runs, `no_plan` when no plan waits on the operator, `unreadable_plan` when its file is not
            a plan, `stale` when it is not the file `read_sha256` names, `bad_outline` when its ids or breakdown
            cannot be read, `approved_changed` when an earlier approved plan's copy is not what was approved, and
            `reused_id` for an id an earlier approval dropped.
        PlanFileError: the approved copy could not be written: the epic's directory is not the operator's own.
        DatabaseError: the approval was not recorded, which nothing but a broken journal does.
    """
    conversation.check_operator()
    _check_epic(conn, epic_id)
    with db.transaction(conn):
        running = records.select(records.EpicRun).where(
            "epic_id = ? AND status = ?",
            epic_id,
            RunStatus.RUNNING,
        )
        if running.all(conn):
            raise Refused("planning", f"epic:{epic_id} is being planned; approve the plan once its run ends")
        current = current_plan(conn, epic_id)
        if current is None or current.status is not PlanStatus.PROPOSED:
            raise Refused("no_plan", f"no plan of epic:{epic_id} waits on you; reply to it to ask for one")
        reading = plans.read(plan_path(state_dir, epic_id, current.run_id))
        if reading.text is None or reading.sha256 is None:
            raise Refused("unreadable_plan", f"epic:{epic_id}'s plan file is {reading.problem}")
        if read_sha256 is not None and reading.sha256 != read_sha256:
            raise Refused("stale", f"epic:{epic_id}'s plan file changed since you read it; read it again to approve it")
        try:
            outline = epic_outline.read(reading.text, repos=repos)
        except epic_outline.OutlineError as e:
            raise Refused("bad_outline", f"epic:{epic_id}'s plan cannot be read: {e.reason}") from None
        earlier = _approved_outlines(conn, state_dir, epic_id)
        change = epic_outline.compare(earlier[-1], outline) if earlier else None
        if earlier:
            retired = frozenset().union(*(o.ids() for o in earlier)) - earlier[-1].ids()
            reused = epic_outline.reused(outline, retired)
            if reused:
                ids = ", ".join(reused)
                raise Refused("reused_id", f"the plan uses {ids}, which an earlier approved plan dropped: never again")
        _keep_approved(state_dir, epic_id, current.run_id, reading.text, reading.sha256)
        update = records.update(records.EpicPlan).set(
            status=PlanStatus.APPROVED,
            approved_sha256=reading.sha256,
            approved_at=db.now(),
            approved_channel=channel,
        )
        update.where("id = ?", current.id).run(conn)
    approved = records.select(records.EpicPlan).where("id = ?", current.id).one(conn)
    if approved is None:
        raise sqlite3.DatabaseError("the epic plan's approval was not recorded")
    return Approved(plan=approved, change=change)


def approved_outline(
    conn: sqlite3.Connection,
    state_dir: Path,
    epic_id: int,
) -> epic_outline.Outline | None:
    """Return the outline of epic `epic_id`'s latest approved plan, from its approved copy.

    Returns:
        The outline, or None while no plan of it has been approved.

    Raises:
        Refused: (`approved_changed`) its copy is not what the operator approved.
    """
    earlier = _approved_outlines(conn, state_dir, epic_id)
    return earlier[-1] if earlier else None


def approved_path(state_dir: Path, epic_id: int, run_id: int, sha256: str) -> Path:
    """Where the copy of the plan run `run_id` wrote, as the operator approved it with hash `sha256`, is kept.

    Returns:
        `<state_dir>/epics/<epic_id>/<run_id>.<sha256>.approved.md`. The file may not exist.
    """
    return plan_path(state_dir, epic_id, run_id).with_name(f"{run_id}.{sha256}{APPROVED_SUFFIX}")


def approved_plan(conn: sqlite3.Connection, epic_id: int) -> records.EpicPlan | None:
    """Return epic `epic_id`'s latest plan the operator approved, superseded since by a proposed one or not.

    Returns:
        The plan, or None while no plan of it has been approved.
    """
    query = records.select(records.EpicPlan).where("epic_id = ? AND approved_sha256 IS NOT NULL", epic_id)
    found = query.order_by("id DESC").all(conn)
    return found[0] if found else None


def member_epic(conn: sqlite3.Connection, state_dir: Path, key: str) -> MemberEpic | None:
    """Return ticket `key`'s epic as its planner meets it: the epic, its approved plan, and the entries it fulfils.

    A registration names the plan approved when it was made, so an entry a later approval dropped is set apart. Where
    the approved copy cannot be read, every entry is kept: the run that reads the copy refuses it.

    Returns:
        None when the ticket is a member of no epic, or its epic has no approved plan yet.
    """
    member = membership(conn, key)
    if member is None:
        return None
    plan = approved_plan(conn, member.epic_id)
    if plan is None:
        return None
    registered = entries_of(conn, member.id)
    held = _held_entries(state_dir, plan)
    entries = [e for e in registered if held is None or e in held]
    dropped = [e for e in registered if e not in entries]
    return MemberEpic(epic_id=member.epic_id, plan=plan, entries=entries, dropped=dropped)


def drift(conn: sqlite3.Connection, ticket: records.Ticket) -> Drift | None:
    """Return `ticket`'s plan that departs from its epic's, while that waits on the operator: `epic_drift` (§43).

    It waits while the plan does (`plans.waits`), the ticket is still a member of the epic whose approved plan it was
    written against, that is still the epic's latest approved plan, and no reply to the epic came after it. So the
    operator ends it by approving the member's plan as written, by approving the epic's plan again, or by asking for a
    new plan of either. The ids were held to that epic plan when the plan was recorded.

    Returns:
        The plan and its ids, or None while no departure waits.
    """
    plan = plans.current(conn, ticket.key)
    if plan is None or plan.epic_drift is None or plan.epic_plan_id is None or not plans.waits(conn, ticket):
        return None
    read = records.select(records.EpicPlan).where("id = ?", plan.epic_plan_id).one(conn)
    member = membership(conn, ticket.key)
    if read is None or member is None or member.epic_id != read.epic_id:
        return None
    latest = approved_plan(conn, read.epic_id)
    if latest is None or latest.id != read.id:
        return None
    if any(m.at > plan.created_at for m in messages_of(conn, read.epic_id)):
        return None
    return Drift(epic_id=read.epic_id, plan=plan, ids=plan.epic_drift.split(plans.DRIFT_SEPARATOR))


def approved_text(state_dir: Path, plan: records.EpicPlan) -> str | None:
    """Return `plan`'s text as the operator approved it, from its kept copy, checked against its approved hash.

    Returns:
        The text, or None when the plan is not approved or its copy is missing or not what was approved.
    """
    if plan.approved_sha256 is None:
        return None
    reading = plans.read(approved_path(state_dir, plan.epic_id, plan.run_id, plan.approved_sha256))
    return reading.text if reading.sha256 == plan.approved_sha256 else None


def messages_of(conn: sqlite3.Connection, epic_id: int) -> list[records.Message]:
    """Return the operator's messages to epic `epic_id`, the oldest first: each its next plan's to read."""
    query = records.select(records.Message).where(
        "subject_kind = ? AND subject_id = ? AND source = 'operator'",
        conversation.EPIC,
        str(epic_id),
    )
    return query.order_by("id").all(conn)


def _keep_approved(state_dir: Path, epic_id: int, run_id: int, text: str, sha256: str) -> None:
    """Keep the copy of an approved plan's `text`, or find it kept already by an approval that failed after writing it.

    Raises:
        PlanFileError: the copy could not be written, or a file of its name holds something else.
    """
    path = approved_path(state_dir, epic_id, run_id, sha256)
    if path.exists() and plans.read(path).sha256 == sha256:
        return
    plans.write_new(state_dir / PLANS_DIR, str(epic_id), path.name, text)


def _held_entries(state_dir: Path, plan: records.EpicPlan) -> AbstractSet[str] | None:
    """Return the breakdown's entries of approved plan `plan`, or None when its copy cannot be read as approved."""
    text = approved_text(state_dir, plan)
    if text is None:
        return None
    try:
        return frozenset(epic_outline.read(text).entries)
    except epic_outline.OutlineError:
        return None


def _approved_outlines(
    conn: sqlite3.Connection,
    state_dir: Path,
    epic_id: int,
) -> list[epic_outline.Outline]:
    """Read every plan of the epic the operator approved, the oldest first, from each one's approved copy.

    Returns:
        Their outlines.

    Raises:
        Refused: (`approved_changed`) a copy is missing or not what was approved, so no approval can be compared.
    """
    found: list[epic_outline.Outline] = []
    for plan in plans_of(conn, epic_id):
        if plan.approved_sha256 is None:
            continue
        path = approved_path(state_dir, epic_id, plan.run_id, plan.approved_sha256)
        reading = plans.read(path)
        if reading.text is None or reading.sha256 != plan.approved_sha256:
            raise Refused("approved_changed", f"{path} is not the plan approved by run {plan.run_id}")
        try:
            found.append(epic_outline.read(reading.text))
        except epic_outline.OutlineError as e:
            raise Refused("approved_changed", f"{path} no longer reads: {e.reason}") from None
    return found


def _entries(
    conn: sqlite3.Connection,
    state_dir: Path | None,
    epic_id: int,
    entries: Iterable[str],
) -> frozenset[str]:
    """Check `entries` against the epic's approved plan's breakdown.

    Returns:
        The entries, each once.

    Raises:
        Refused: `no_plan` when an entry is named and no plan has been approved, `unknown_entry` for one the approved
            plan does not hold.
    """
    named = frozenset(entries)
    if not named:
        return named
    outline = approved_outline(conn, state_dir, epic_id) if state_dir is not None else None
    if outline is None:
        raise Refused("no_plan", f"epic:{epic_id} has no approved plan, so no entry to register against")
    unknown = sorted(named - frozenset(outline.entries))
    if unknown:
        raise Refused("unknown_entry", f"the approved plan of epic:{epic_id} has no {', '.join(unknown)}")
    return named


def _register(conn: sqlite3.Connection, member: records.EpicMember, entries: AbstractSet[str]) -> None:
    """Replace `member`'s entries with `entries`."""
    records.delete(records.EpicMemberEntry).where("member_id = ?", member.id).run(conn)
    if entries:
        rows = records.insert_rows(records.EpicMemberEntry, ("member_id", "entry"))
        rows.many(conn, [(member.id, entry) for entry in sorted(entries)])


def _repositories(workspace: Workspace, repos: Sequence[str]) -> list[str]:
    """The repositories an epic's plan reads: `repos`, each once, or the workspace's only one.

    Returns:
        Their names as the map spells them, in the order given.

    Raises:
        Refused: (`unknown_repo`) a repository is not in the map, or none is named in a workspace of several.
    """
    names = ", ".join(r.name for r in workspace.repos) or "none yet"
    if not repos:
        if len(workspace.repos) == 1:
            return [workspace.repos[0].name]
        raise Refused("unknown_repo", f"--repo is required: name each repository its plan reads ({names})")
    found: list[str] = []
    for repo in repos:
        named = workspace.repo(repo)
        if named is None:
            raise Refused("unknown_repo", f"{repo!r} is not a repository in this workspace ({names})")
        found.append(named.name)
    return list(dict.fromkeys(found))


def _check_key(value: str, what: str) -> None:
    """Refuse `value` unless it is a plain tracker key (`bad_key`), `what` naming it in the reason.

    Raises:
        Refused: (`bad_key`) it does not match `KEY_RE`, or is over `MAX_KEY` characters.
    """
    if len(value) > MAX_KEY or not KEY_RE.fullmatch(value):
        raise Refused("bad_key", f"{value[:MAX_KEY]!r} is not {what}: it must match {KEY_RE.pattern}")


def _check_epic(conn: sqlite3.Connection, epic_id: int) -> None:
    """Refuse an epic canopy has none of (`unknown_epic`).

    Raises:
        Refused: (`unknown_epic`) there is no epic `epic_id`.
    """
    if get(conn, epic_id) is None:
        raise Refused("unknown_epic", f"canopy has no epic:{epic_id}")
