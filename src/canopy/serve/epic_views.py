"""Epics as the API sends them (DESIGN §43): the epics list, an epic's page with its breakdown, and its plans.

Reads only. An epic's text and replies are the operator's; its plans and what its plan runs said are an agent's:
control characters are dropped, line breaks kept, and the UI renders them as text. The outline is read by the readers
the CLI and the harness use, `epics.approved_outline` and `epic_outline.read`, from the approved plan's kept copy, or,
while none is approved, from the proposed plan's file: a plan whose ids repeat or will not parse is served as its
problem, never as part of a map (TRUST_MODEL T1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, assert_never

from canopy.core import contract, conversation, db, epic_outline, epics, plans
from canopy.core.vocab import PlanStatus, RunStatus
from canopy.runs import epic_runs
from canopy.serve.schema.epic import (
    EpicDetail,
    EpicEntry,
    EpicId,
    EpicMember,
    EpicOutline,
    EpicPlanFile,
    EpicPlanRun,
    EpicPlans,
    EpicPlanSummary,
    EpicRunLatest,
    EpicSummary,
)
from canopy.serve.views import attachments_of, lines, message, run_state, said, ticket_title

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Mapping, Sequence
    from collections.abc import Set as AbstractSet

    from canopy.core import records
    from canopy.core.context import Context
    from canopy.serve.schema.epic import EpicStanding, OutlineSource


def epics_list(ctx: Context) -> list[EpicSummary]:
    """Every epic, the newest first, as `canopy epic list` lists them: none is ever deleted (DESIGN §43).

    Returns:
        Each epic's summary, with where it stands and how much of its breakdown has members.
    """
    due = _due(ctx)
    return [_summary(ctx, e, _outlined(ctx, e.id), due=due) for e in epics.every(ctx.conn)]


def epic_detail(ctx: Context, epic_id: int) -> EpicDetail | None:
    """Epic `epic_id`, as `canopy show epic:N` prints it, or None if canopy has no such epic.

    Returns:
        The epic, its members with the entries each fulfils, its bounds, its plan runs, its replies, its current plan,
        and its outline.
    """
    epic = epics.get(ctx.conn, epic_id)
    if epic is None:
        return None
    outlined = _outlined(ctx, epic_id)
    members = epics.members_of(ctx.conn, epic_id)
    registered = {m.id: epics.entries_of(ctx.conn, m.id) for m in members}
    held = outlined.held()
    recorded = {p.run_id: p.id for p in epics.plans_of(ctx.conn, epic_id)}
    current = epics.current_plan(ctx.conn, epic_id)
    latest = db.latest_runs(ctx.conn)
    return EpicDetail(
        epic=_summary(ctx, epic, outlined, due=_due(ctx)),
        members=[_member(ctx.conn, m, registered[m.id], held, latest.get(m.ticket_key)) for m in members],
        bound=ctx.config.policy.max_epic_tickets,
        max_plan_attempts=ctx.config.policy.max_plan_attempts,
        runs=[_plan_run(r, recorded.get(r.id)) for r in epic_runs.runs_of(ctx.conn, epic_id)],
        messages=[message(m) for m in epics.messages_of(ctx.conn, epic_id)],
        attachments=attachments_of(ctx, conversation.Ref(conversation.EPIC, str(epic_id))),
        plan=plan_summary(current) if current is not None else None,
        outline=outlined.view(_fulfilling(members, registered)),
    )


def epic_plans(ctx: Context, epic_id: int) -> EpicPlans | None:
    """Epic `epic_id`'s plans, each as its file stands now, or None if canopy has no such epic.

    Each file is read bounded and never through a link, as `canopy show epic:N` reads it; the journal holds only its
    status and hashes.

    Returns:
        The plan run writing its next plan, if one is, every plan, the oldest first, and when the operator asked for
        changes the next tick's plan run reads.
    """
    if epics.get(ctx.conn, epic_id) is None:
        return None
    running = next((r.id for r in epic_runs.runs_of(ctx.conn, epic_id) if r.status is RunStatus.RUNNING), None)
    replies = epics.messages_of(ctx.conn, epic_id)
    asked = replies[-1].at if replies and epic_id in _due(ctx) else None
    return EpicPlans(
        epic_id=epic_id,
        planning=running,
        plans=[_plan_file(ctx, p) for p in epics.plans_of(ctx.conn, epic_id)],
        changes_asked=db.parse_time(asked) if asked is not None else None,
    )


def plan_summary(plan: records.EpicPlan) -> EpicPlanSummary:
    """An epic's plan's status and approval, never its text.

    Returns:
        The plan, as the API sends it.
    """
    return EpicPlanSummary(
        id=plan.id,
        run_id=plan.run_id,
        status=plan.status.value,
        created_at=db.parse_time(plan.created_at),
        approved_at=db.parse_time(plan.approved_at) if plan.approved_at is not None else None,
        approved_channel=plan.approved_channel,
    )


@dataclass(frozen=True)
class _Outlined:
    """An epic's outline as read: the plan it is read from, and the outline, or why it cannot be read."""

    source: OutlineSource | None = None
    #: The plan it is read from; None while the epic has none to read.
    plan: records.EpicPlan | None = None
    outline: epic_outline.Outline | None = None
    #: Why the plan's ids or breakdown cannot be read; None when they can, or there is no plan.
    problem: str | None = None

    def held(self) -> AbstractSet[str] | None:
        """Return the entries an approved plan holds, which a member's registrations are held to.

        Returns:
            None when no approved plan reads, so every registration stands, as `epics.member_epic` keeps them.
        """
        if self.source != "approved" or self.outline is None:
            return None
        return frozenset(self.outline.entries)

    def view(self, fulfilling: Mapping[str, Sequence[str]]) -> EpicOutline | None:
        """Return the outline as the API sends it, each entry with the members registered against it.

        Returns:
            None while the epic has no plan to read.
        """
        if self.source is None or self.plan is None:
            return None
        base = EpicOutline(source=self.source, plan_id=self.plan.id, run_id=self.plan.run_id, problem=self.problem)
        if self.outline is None:
            return base
        # An entry's members come only from an approved plan's registrations: none is made against a proposed one.
        members = fulfilling if self.source == "approved" else {}
        return base.model_copy(
            update={
                "requirements": [EpicId(id=i, text=_text(t)) for i, t in self.outline.requirements.items()],
                "contracts": [EpicId(id=i, text=_text(t)) for i, t in self.outline.contracts.items()],
                "entries": [_entry(e, members.get(e.id, ())) for e in self.outline.entries.values()],
            },
        )


def _outlined(ctx: Context, epic_id: int) -> _Outlined:
    """Read the epic's outline: the approved plan's, from its kept copy, or, while none is approved, the proposed one's.

    Returns:
        The outline and the plan it is read from, or why it cannot be read; empty while the epic has no plan.
    """
    approved = epics.approved_plan(ctx.conn, epic_id)
    if approved is not None:
        try:
            outline = epics.approved_outline(ctx.conn, ctx.state_dir, epic_id)
        except conversation.Refused as r:
            return _Outlined(source="approved", plan=approved, problem=conversation.printable(r.reason))
        return _Outlined(source="approved", plan=approved, outline=outline)
    current = epics.current_plan(ctx.conn, epic_id)
    if current is None:
        return _Outlined()
    reading = plans.read(epics.plan_path(ctx.state_dir, epic_id, current.run_id))
    if reading.text is None:
        return _Outlined(source="proposed", plan=current, problem=f"its file is {reading.problem}")
    repos = frozenset(epics.repos_of(ctx.conn, epic_id))
    try:
        outline = epic_outline.read(reading.text, repos=repos)
    except epic_outline.OutlineError as e:
        return _Outlined(source="proposed", plan=current, problem=conversation.printable(e.reason))
    return _Outlined(source="proposed", plan=current, outline=outline)


def _summary(ctx: Context, epic: records.Epic, outlined: _Outlined, *, due: AbstractSet[int]) -> EpicSummary:
    members = epics.members_of(ctx.conn, epic.id)
    outline = outlined.outline
    entries = None
    filed = 0
    if outline is not None:
        entries = len(outline.entries)
        if outlined.source == "approved":
            fulfilled = {e for m in members for e in epics.entries_of(ctx.conn, m.id)}
            filed = sum(1 for e in outline.entries if e in fulfilled)
    return EpicSummary(
        id=epic.id,
        text=lines(epic.text),
        repos=epics.repos_of(ctx.conn, epic.id),
        project=epic.project,
        tracker_epic=epic.tracker_epic,
        channel=epic.channel,
        submitted_at=db.parse_time(epic.submitted_at),
        stopped_at=db.parse_time(epic.stopped_at) if epic.stopped_at is not None else None,
        standing=_standing(ctx.conn, epic, due=due),
        members=len(members),
        planned=outlined.plan is not None,
        entries=entries,
        entries_with_members=filed,
    )


def _standing(conn: sqlite3.Connection, epic: records.Epic, *, due: AbstractSet[int]) -> EpicStanding:
    """Where the epic stands: its plan run working, else stopped, else its current plan's status, else a run due.

    Returns:
        The word, as the API's vocabulary spells it.
    """
    if any(r.status is RunStatus.RUNNING for r in epic_runs.runs_of(conn, epic.id)):
        return "planning"
    if epic.stopped_at is not None:
        return "stopped"
    current = epics.current_plan(conn, epic.id)
    if current is not None:
        match current.status:
            case PlanStatus.PROPOSED:
                return "proposed"
            case PlanStatus.APPROVED:
                return "approved"
            case PlanStatus.SUPERSEDED:
                # `current_plan` never returns one; read as no plan, should a broken journal hold one.
                pass
            case _:
                assert_never(current.status)
    return "queued" if epic.id in due else "unplanned"


def _due(ctx: Context) -> frozenset[int]:
    """The epics the next tick starts a plan run for, by id, as the tick decides it (`epic_runs.due`).

    Returns:
        Their ids.
    """
    return frozenset(e.id for e in epic_runs.due(ctx.conn, ctx.config.policy.max_plan_attempts))


def _member(
    conn: sqlite3.Connection,
    member: records.EpicMember,
    registered: Sequence[str],
    held: AbstractSet[str] | None,
    latest: records.Run | None,
) -> EpicMember:
    ticket = db.get_ticket(conn, member.ticket_key)
    entries = [e for e in registered if held is None or e in held]
    return EpicMember(
        key=member.ticket_key,
        title=ticket_title(ticket.title) if ticket is not None else None,
        entries=entries,
        dropped=[e for e in registered if e not in entries],
        added_at=db.parse_time(member.added_at),
        added_channel=member.added_channel,
        phase=ticket.phase.value if ticket is not None and ticket.phase is not None else None,
        prs=[u.pr_url for u in db.units(conn, member.ticket_key) if u.pr_url],
        latest_run=EpicRunLatest(
            id=latest.id,
            kind=str(latest.kind),
            status=str(latest.status),
            state=run_state(str(latest.status)),
        )
        if latest is not None
        else None,
    )


def _fulfilling(
    members: Iterable[records.EpicMember],
    registered: Mapping[int, Sequence[str]],
) -> dict[str, list[str]]:
    """The members registered against each entry, by entry, each list by when its members were added.

    Returns:
        The keys, by entry id.
    """
    found: dict[str, list[str]] = {}
    for member in members:
        for entry in registered[member.id]:
            found.setdefault(entry, []).append(member.ticket_key)
    return found


def _entry(entry: epic_outline.Entry, members: Sequence[str]) -> EpicEntry:
    return EpicEntry(
        id=entry.id,
        title=" ".join(conversation.printable(entry.title).split()),
        covers=_ids(entry.covers),
        provides=_ids(entry.provides),
        uses=_ids(entry.uses),
        repos=sorted(entry.repos),
        after=_ids(entry.after),
        trivial=_text(entry.trivial) if entry.trivial is not None else None,
        members=list(members),
    )


def _plan_run(row: records.EpicRun, plan_id: int | None) -> EpicPlanRun:
    stored = contract.stored_object(row.result_json)
    question = lines(str(stored.get("question") or "")) if row.status is RunStatus.BLOCKED else ""
    return EpicPlanRun(
        id=row.id,
        status=str(row.status),
        state=run_state(str(row.status)),
        started_at=db.parse_time(row.started_at),
        ended_at=db.parse_time(row.ended_at) if row.ended_at else None,
        summary=said(row),
        question=question or None,
        plan_id=plan_id,
        model=row.model,
        cost_usd=row.cost_usd,
    )


def _plan_file(ctx: Context, plan: records.EpicPlan) -> EpicPlanFile:
    path = epics.plan_path(ctx.state_dir, plan.epic_id, plan.run_id)
    reading = plans.read(path)
    return EpicPlanFile(
        plan=plan_summary(plan),
        path=str(path),
        text=reading.text,
        problem=reading.problem,
        sha256=reading.sha256,
        edited=reading.sha256 != plan.sha256,
        changed_since_approval=plan.approved_sha256 is not None and reading.sha256 != plan.approved_sha256,
    )


def _ids(found: Iterable[str]) -> list[str]:
    """Return ids of one kind by number, so `R2` comes before `R10`."""
    return sorted(found, key=lambda i: int(i[1:]))


def _text(text: str) -> str:
    """Return model text read from a plan, control characters dropped."""
    return conversation.printable(text)
