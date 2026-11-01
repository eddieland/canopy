"""How the window's plans were approved, and what their PRs needed after (DESIGN §11, §25), for the Plans report.

Reads only. Over the same window as `canopy spend` and `canopy health` (whole local days, today's so far included): the
ticket plans written in it, each with how it went (approved by its planner, approved by the operator as written or
after a change, replaced by a newer plan, dropped, or still waiting), how long its approval took against its length,
measured from its file as its planner wrote it (`plan_metrics`), and the `resume` runs its ticket needed once it was
approved. Split by the level of `policy.planner_may_approve` its plan run's prompt offered, so a level is judged on
what it let through before the key is loosened (#1872).

A plan the operator approved as written says little about the plan by itself: whether its PR then needed a `resume`
says more. A ticket's resumes after its approval are its PR's, since a ticket is never planned once it has a branch.
Feedback plans (DESIGN §32) are the Reviews report's, not here. A plan run from before canopy kept the level it offered
has none, and is counted apart.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

from canopy.core import db, plan_lengths, plan_metrics, plans, records, spend, sql
from canopy.core.vocab import PlanEffort, PlannerApproval, PlanStatus, ResumeReason, RunKind

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Collection, Iterable, Mapping, Sequence
    from datetime import datetime
    from pathlib import Path

#: The kinds that count as a `resume`: the retired `fix-ci` counts as one with the reason `ci` (DESIGN §8).
RESUMES = (RunKind.RESUME, RunKind.FIX_CI)
#: A page of a plan, in the plan editor's lines (`plan_metrics.Metrics.lines`): about a screen at 1440 pixels tall.
PAGE_LINES = 50
#: Where the length table cuts a plan's length, in lines: under a page, under 2, under 4, and the rest.
LENGTH_BOUNDS = (PAGE_LINES, 2 * PAGE_LINES, 4 * PAGE_LINES)


class Outcome(StrEnum):
    """How a plan went, as the report sorts it."""

    #: The harness approved it on its planner's word that it needs no review.
    PLANNER = "planner"
    #: The operator approved the ticket's first plan as its planner wrote it, with no comment on it.
    AS_WRITTEN = "as_written"
    #: The operator approved it after editing it or commenting on it, or after sending an earlier plan of its ticket
    #: back for a new one.
    REVISED = "revised"
    #: A newer plan of its ticket replaced it before it was approved: sent back.
    REPLACED = "replaced"
    #: Superseded before it was approved with no plan after it: skipped, or forgotten.
    DROPPED = "dropped"
    #: Proposed, waiting on the operator.
    WAITING = "waiting"


#: The outcomes of a plan that was approved, the planner's first.
APPROVED = (Outcome.PLANNER, Outcome.AS_WRITTEN, Outcome.REVISED)


@dataclass(frozen=True)
class PlanRow:
    """A ticket plan written in the window, the newest first: how it went, and what its ticket needed after."""

    plan_id: int
    ticket: str
    #: The plan run that wrote it.
    run_id: int
    created_at: str
    #: Its file's size as its planner wrote it, in bytes.
    size: int
    #: How long it is, measured from its file as its planner wrote it; None when that file could not be read.
    metrics: plan_metrics.Metrics | None
    effort: PlanEffort | None
    #: The level its plan run's prompt offered its planner; None for a run from before canopy kept it.
    level: PlannerApproval | None
    outcome: Outcome
    #: When it was approved; None when it was not.
    approved_at: str | None
    #: Whether its file was edited before its approval: the hash approved is not the hash written.
    edited: bool
    #: The operator's comments and replies on its ticket's plan between when it was written and when it was approved,
    #: replaced, or now.
    comments: int
    #: The ticket's plans before it, which it replaced.
    earlier: int
    #: Whether an `implement` followed it.
    implemented: bool
    #: The `resume` runs its ticket started once it was approved, `RESUMES`, and how many named each reason.
    resumes: int
    reasons: Mapping[ResumeReason, int]
    #: Whether the loop has marked its ticket done, so its resumes are all in.
    done: bool
    #: What its own run cost; None when it reported none.
    cost_usd: float | None

    @property
    def to_approve(self) -> timedelta | None:
        """From when it was written to its approval; None when it was not approved."""
        if self.approved_at is None:
            return None
        return db.parse_time(self.approved_at) - db.parse_time(self.created_at)


@dataclass(frozen=True)
class Group:
    """The window's approved plans of one level and one outcome, and what their tickets needed after."""

    #: None for the plans whose run kept no level.
    level: PlannerApproval | None
    outcome: Outcome
    plans: int
    #: The median of their times to approval.
    median_to_approve: timedelta | None
    #: The medians of their lengths in the plan editor's lines and of their words, of those measured; None with none.
    median_lines: int | None
    median_words: int | None
    #: Those an `implement` followed, and of those, the ones whose ticket needed at least one `resume`.
    implemented: int
    with_resume: int
    resumes: int
    #: Those whose ticket the loop marked done, so their count is final.
    done: int


@dataclass(frozen=True)
class Length:
    """The window's plans the operator approved, of one size bucket, and how long approving them took."""

    #: The bucket's bounds in the plan editor's lines, `[low, high)`; `high` None for the last.
    low: int
    high: int | None
    plans: int
    median_to_approve: timedelta | None
    #: Of those, the ones approved as written.
    as_written: int


@dataclass(frozen=True)
class Plans:
    """How the window's plans were approved, and what their tickets needed after."""

    since: str
    until: str
    days: int
    #: The newest first.
    plans: Sequence[PlanRow]
    #: By level, `off` to `lenient`, then the unrecorded; within each, by outcome as `APPROVED` orders them.
    groups: Sequence[Group]
    #: The smallest first; each one with a plan in it.
    lengths: Sequence[Length]

    def count(self, outcome: Outcome) -> int:
        """How many of the window's plans went `outcome`.

        Returns:
            The count; 0 for none.
        """
        return sum(1 for p in self.plans if p.outcome is outcome)


def report(conn: sqlite3.Connection, state_dir: Path, now: datetime, days: int) -> Plans:
    """How the plans written over the last `days` local days were approved, today's so far included.

    Each plan's measurements are the journal's (`plan_lengths`), or measured from its original under `state_dir`,
    as its planner wrote it, where the journal has none yet.

    Returns:
        The report; a window with no plan has no rows, groups, or lengths.
    """
    start, end = spend.window(now, days)
    since, until = db.format_time(start), db.format_time(end)
    with db.read_snapshot(conn):
        written = (
            records.select(records.Plan)
            .where("created_at >= ? AND created_at < ?", since, until)
            .order_by("created_at DESC, id DESC")
            .all(conn)
        )
        keys = sorted({p.ticket_key for p in written})
        every = records.select(records.Plan).where_in("ticket_key", keys).order_by("id").all(conn)
        tickets = {t.key: t for t in records.select(records.Ticket).where_in("key", keys).all(conn)}
        runs = _runs(conn, keys)
        said = _comments(conn, keys)
        reasons = db.run_reasons(conn, [r.id for r in runs if r.kind is RunKind.RESUME])
        measured = plan_lengths.read(conn, state_dir, written)
    by_ticket: dict[str, list[records.Plan]] = {}
    for p in every:
        by_ticket.setdefault(p.ticket_key, []).append(p)
    rows = [
        _row(
            p,
            by_ticket[p.ticket_key],
            [r for r in runs if r.ticket_key == p.ticket_key],
            reasons,
            said.get(p.ticket_key, []),
            metrics=measured.get(p.id),
            done=(t := tickets.get(p.ticket_key)) is not None and t.done,
        )
        for p in written
    ]
    return Plans(since=since, until=until, days=days, plans=rows, groups=_groups(rows), lengths=_lengths(rows))


@dataclass(frozen=True)
class _Run(records.View):
    """A worker run on a ticket the report reads: a plan run, an implement, or a resume."""

    id: int
    ticket_key: str
    kind: RunKind
    started_at: str
    plan_id: int | None
    plan_review: PlannerApproval | None
    cost_usd: float | None


def _runs(conn: sqlite3.Connection, keys: Collection[str]) -> list[_Run]:
    query = (
        sql.select("id, ticket_key, kind, started_at, plan_id, plan_review, cost_usd")
        .from_("runs")
        .where(
            "ticket_key IN (SELECT value FROM json_each(?)) AND kind IN (?, ?, ?, ?)",
            json.dumps(list(keys)),
            RunKind.PLAN,
            RunKind.IMPLEMENT,
            *RESUMES,
        )
        .order_by("id")
    )
    return records.fetch_all(conn, _Run, query)


@dataclass(frozen=True)
class _Said(records.View):
    """When the operator commented on a ticket's plan, or replied in one of its threads."""

    ticket_key: str
    created_at: str


# Every comment and reply on the tickets' plans, by ticket, oldest first.
def _comments(conn: sqlite3.Connection, keys: Collection[str]) -> dict[str, list[str]]:
    keyed = json.dumps(list(keys))
    threads = (
        sql.select("ticket_key, created_at")
        .from_("plan_threads")
        .where("ticket_key IN (SELECT value FROM json_each(?))", keyed)
    )
    replies = (
        sql.select("t.ticket_key, r.created_at")
        .from_("plan_replies r")
        .join("plan_threads t ON t.id = r.thread_id")
        .where("t.ticket_key IN (SELECT value FROM json_each(?))", keyed)
    )
    found: dict[str, list[str]] = {}
    for said in [*records.fetch_all(conn, _Said, threads), *records.fetch_all(conn, _Said, replies)]:
        found.setdefault(said.ticket_key, []).append(said.created_at)
    return {key: sorted(times) for key, times in found.items()}


def _row(
    plan: records.Plan,
    ticket_plans: Sequence[records.Plan],
    runs: Sequence[_Run],
    reasons: Mapping[int, Sequence[ResumeReason]],
    said: Iterable[str],
    *,
    metrics: plan_metrics.Metrics | None,
    done: bool,
) -> PlanRow:
    earlier = sum(1 for p in ticket_plans if p.id < plan.id)
    after = next((p for p in ticket_plans if p.id > plan.id), None)
    # Its comments are the ones made while it was the ticket's plan: until it was approved, or replaced, or now.
    end = plan.approved_at or (after.created_at if after is not None else None)
    comments = sum(1 for at in said if _at(plan.created_at) <= _at(at) and (end is None or _at(at) < _at(end)))
    edited = plan.approved_sha256 is not None and plan.approved_sha256 != plan.sha256
    wrote = next((r for r in runs if r.id == plan.run_id), None)
    resumes = (
        []
        if plan.approved_at is None
        else [r for r in runs if r.kind in RESUMES and _at(r.started_at) >= _at(plan.approved_at)]
    )
    counted: dict[ResumeReason, int] = {}
    for r in resumes:
        for reason in reasons.get(r.id, ()) if r.kind is RunKind.RESUME else (ResumeReason.CI,):
            counted[reason] = counted.get(reason, 0) + 1
    return PlanRow(
        plan_id=plan.id,
        ticket=plan.ticket_key,
        run_id=plan.run_id,
        created_at=plan.created_at,
        size=plan.size,
        metrics=metrics,
        effort=plan.effort,
        level=None if wrote is None else wrote.plan_review,
        outcome=_outcome(plan, after, edited=edited, comments=comments, earlier=earlier),
        approved_at=plan.approved_at,
        edited=edited,
        comments=comments,
        earlier=earlier,
        implemented=any(r.kind is RunKind.IMPLEMENT and r.plan_id == plan.id for r in runs),
        resumes=len(resumes),
        reasons={reason: counted[reason] for reason in ResumeReason if reason in counted},
        done=done,
        cost_usd=None if wrote is None else wrote.cost_usd,
    )


def _outcome(
    plan: records.Plan,
    after: records.Plan | None,
    *,
    edited: bool,
    comments: int,
    earlier: int,
) -> Outcome:
    if plan.approved_at is not None:
        if plan.approved_channel == plans.PLANNER:
            return Outcome.PLANNER
        return Outcome.REVISED if edited or comments or earlier else Outcome.AS_WRITTEN
    if plan.status is PlanStatus.PROPOSED:
        return Outcome.WAITING
    return Outcome.DROPPED if after is None else Outcome.REPLACED


def _groups(rows: Sequence[PlanRow]) -> list[Group]:
    levels: list[PlannerApproval | None] = [*PlannerApproval, None]
    found: list[Group] = []
    for level in levels:
        for outcome in APPROVED:
            theirs = [r for r in rows if r.level == level and r.outcome is outcome]
            if not theirs:
                continue
            implemented = [r for r in theirs if r.implemented]
            found.append(
                Group(
                    level=level,
                    outcome=outcome,
                    plans=len(theirs),
                    median_to_approve=_median([w for r in theirs if (w := r.to_approve) is not None]),
                    median_lines=_middle([m.lines for r in theirs if (m := r.metrics) is not None]),
                    median_words=_middle([m.words for r in theirs if (m := r.metrics) is not None]),
                    implemented=len(implemented),
                    with_resume=sum(1 for r in implemented if r.resumes),
                    resumes=sum(r.resumes for r in theirs),
                    done=sum(1 for r in theirs if r.done),
                ),
            )
    return found


# The plans the operator approved, by length: the planner's approvals take no time, so they would only pull it down.
# A plan whose file could not be measured is left out.
def _lengths(rows: Iterable[PlanRow]) -> list[Length]:
    bounds = list(zip((0, *LENGTH_BOUNDS), (*LENGTH_BOUNDS, None), strict=True))
    approved = [
        (r, m.lines)
        for r in rows
        if r.outcome in (Outcome.AS_WRITTEN, Outcome.REVISED) and (m := r.metrics) is not None
    ]
    found: list[Length] = []
    for low, high in bounds:
        theirs = [r for r, lines in approved if low <= lines and (high is None or lines < high)]
        if theirs:
            found.append(
                Length(
                    low=low,
                    high=high,
                    plans=len(theirs),
                    median_to_approve=_median([w for r in theirs if (w := r.to_approve) is not None]),
                    as_written=sum(1 for r in theirs if r.outcome is Outcome.AS_WRITTEN),
                ),
            )
    return found


# A journal time as a datetime, so two compare by instant whatever their spelling.
def _at(stamp: str) -> datetime:
    return db.parse_time(stamp)


def _middle(values: Collection[int]) -> int | None:
    return round(statistics.median(values)) if values else None


def _median(waits: Collection[timedelta]) -> timedelta | None:
    return timedelta(seconds=statistics.median(w.total_seconds() for w in waits)) if waits else None
