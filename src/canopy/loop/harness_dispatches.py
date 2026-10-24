"""The harness's dispatches (DESIGN §37, ROADMAP M38): planned before the overseer, made after it, in §7's order.

Before the overseer runs, the harness plans what it dispatches this tick: each due chore with no `when` (§19), and,
for a ticket every row of whose derivation is one it dispatches for, a `resume` of its unit with those rows' fixed
context. The state block names them and the workers they hold, and the overseer records nothing about one: a ticket's
verbs and a chore's are refused `decided`. After the overseer's run, whatever it ended as, the harness makes them, runs
first and in §7's order, each under every guard an overseer's dispatch passes (§8, §19) and recorded as its own; a dry
run checks the guards and starts none (D036). A dispatch of the overseer's that would leave fewer workers free than
the harness's runs ranked above it hold is refused `reserved` (`reserved`).

The plan is read from the journal each time, never kept: the tick's derivation (`phases.recorded`), the attention list,
and the chores' runs, so the state block, the overseer's tools, and the dispatches after it read the same plan. A chore
that comes due while the overseer runs is the harness's all the same, since only the harness runs one with no `when`.

The ticket rows it dispatches for are `ROWS`, none yet: each rests on what a connector observed, so each waits on a PR
citing the measurement that shows the derivation right on it (§37, The evidence gate). A chore's row is read from the
config and the journal alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import IntEnum
from typing import TYPE_CHECKING, TypedDict, assert_never

from canopy.chores import start as chore_start
from canopy.core import chore_view, conversation, db, feedback_plans, records, sql
from canopy.core.vocab import Decider, Phase, ResumeReason, RunKind
from canopy.loop import attention, phases
from canopy.runs import dispatch

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Mapping, Sequence

    from canopy.core.config import Chore
    from canopy.core.context import Context
    from canopy.infra import logs


class Rank(IntEnum):
    """Where a dispatch stands in §7's order, whoever decides it: a lower rank goes first."""

    #: A review the operator requested.
    REQUESTED = 0
    #: A human waiting: `human_replied`, `changes_requested`, `review_findings`.
    HUMAN = 1
    #: `conflicted` and `ci_red`: work in flight a machine broke.
    REPAIR = 2
    #: `pushed_no_pr`.
    NO_PR = 3
    #: The loop's own reviews and the review query's.
    REVIEW = 4
    #: `ready`, new work: a blocker before what it blocks.
    READY = 5


#: The rank of each row of §7 that dispatches.
PHASE_RANKS: Mapping[Phase, Rank] = {
    Phase.HUMAN_REPLIED: Rank.HUMAN,
    Phase.CHANGES_REQUESTED: Rank.HUMAN,
    Phase.REVIEW_FINDINGS: Rank.HUMAN,
    Phase.CONFLICTED: Rank.REPAIR,
    Phase.CI_RED: Rank.REPAIR,
    Phase.PUSHED_NO_PR: Rank.NO_PR,
    Phase.REVIEW_PENDING: Rank.REVIEW,
    Phase.BLOCKED: Rank.READY,
    Phase.READY: Rank.READY,
}
#: The rank of the row each reason of a `resume` answers. `retarget` follows a blocker that merged: work in flight.
REASON_RANKS: Mapping[ResumeReason, Rank] = {
    ResumeReason.REPLY: Rank.HUMAN,
    ResumeReason.REVIEW: Rank.HUMAN,
    ResumeReason.CONFLICT: Rank.REPAIR,
    ResumeReason.CI: Rank.REPAIR,
    ResumeReason.RETARGET: Rank.REPAIR,
    ResumeReason.NO_PR: Rank.NO_PR,
}
#: What a `dispatch:chore` the harness makes says of why it runs.
CHORE_WHY = "due, with no `when`"


@dataclass(frozen=True)
class Row:
    """A row of §7 the harness dispatches a `resume` for on a unit: the reason it names, and its fixed context."""

    #: The reason the `resume` names.
    reason: ResumeReason
    #: What the worker is told, fixed in code: never model-written text (TRUST_MODEL T1).
    context: str


#: The rows the harness dispatches for, none yet: each rests on what a connector observed (a PR's mergeability, its
#: checks, a branch with no PR), so each waits on its measurement.
ROWS: Mapping[Phase, Row] = {}


@dataclass(frozen=True)
class TicketRun:
    """A `resume` the harness makes after the overseer: of one unit of a ticket, for the rows that held for it."""

    key: str
    repo: str
    #: The rows it is for, each in `ROWS`, in §7's order.
    phases: Sequence[Phase]
    #: The queue label the ticket was observed with; None for a private ticket, which its start record authorizes.
    label: str | None

    @property
    def rank(self) -> Rank:
        """Its place in §7's order: its highest row's."""
        return min(PHASE_RANKS[p] for p in self.phases)

    @property
    def reasons(self) -> tuple[ResumeReason, ...]:
        """The reasons its `resume` names, each once."""
        return tuple(dict.fromkeys(ROWS[p].reason for p in self.phases))

    @property
    def context(self) -> str:
        """What its worker is told: each row's fixed context."""
        return " ".join(ROWS[p].context for p in self.phases)


@dataclass(frozen=True)
class Plan:
    """The harness's dispatches to come this tick, in the order it makes them."""

    #: Its runs, by rank, then key: each holds a worker within `capacity.max_workers`.
    runs: Sequence[TicketRun]
    #: Its chores, by name: each holds a chore run within `capacity.max_chores`.
    chores: Sequence[str]


class ToCome(TypedDict):
    """The state block's `dispatches_to_come`: the harness's, after the overseer, and the workers they hold."""

    #: The workers its runs hold, of `capacity.available`.
    holds_workers: int
    runs: list[RunToCome]
    chores: list[str]


class RunToCome(TypedDict):
    """A run to come: the ticket and unit, its kind, and the rows it is for."""

    ticket: str
    repo: str
    kind: str
    rows: list[str]


def plan(ctx: Context, tick_id: int, now: datetime) -> Plan:
    """The harness's dispatches to come in tick `tick_id`, as its journal stands at `now`.

    Returns:
        Its runs and chores, in the order it makes them.
    """
    return Plan(runs(ctx, tick_id), chores(ctx, now))


def runs(ctx: Context, tick_id: int) -> list[TicketRun]:
    """The `resume` runs the harness makes after the overseer in tick `tick_id`, from that tick's derivation.

    A ticket is the harness's when its own row is a fresh, open candidate holding no row, and exactly one of its units
    holds rows, every one in `ROWS`, with none stale: one row of judgment anywhere leaves it whole to the overseer. So
    does an item the overseer holds on it, and a `resume` a feedback plan gates (§32).

    Returns:
        Them, by rank, then key.
    """
    if not ROWS:
        return []
    by_ticket: dict[str, list[phases.Derived]] = {}
    for d in phases.recorded(ctx.conn, tick_id):
        by_ticket.setdefault(d.ticket_key, []).append(d)
    kept = _held(ctx.conn)
    found = [
        run for key in sorted(by_ticket) if key not in kept and (run := _run(ctx, key, by_ticket[key])) is not None
    ]
    return sorted(found, key=lambda r: (r.rank, r.key))


def chores(ctx: Context, now: datetime) -> list[str]:
    """The chores the harness runs after the overseer: each due at `now`, not running, and with no `when` (§19).

    Returns:
        Their names, in order.
    """
    states = chore_view.states(ctx.conn, ctx.config, ctx.workspace)
    return [c["name"] for c in chore_view.state_section(states, now) if c["due"] and not c["running"] and not c["when"]]


def takes_chore(chore: Chore) -> bool:
    """Whether `chore` is the harness's to run: one with no `when` needs no judgment of when (§19, §37).

    Returns:
        True when its `when` is empty.
    """
    return not chore.when


def tickets(ctx: Context, tick_id: int) -> frozenset[str]:
    """The tickets the harness dispatches after the overseer in tick `tick_id`, which the overseer is not shown.

    Returns:
        Their keys.
    """
    return frozenset(r.key for r in runs(ctx, tick_id))


def reserved(ctx: Context, tick_id: int, kind: RunKind, reasons: Iterable[ResumeReason]) -> int:
    """The workers the harness's runs to come in tick `tick_id` hold ahead of an overseer's `kind` dispatch.

    Each run ranked above it holds one: a human waiting goes ahead of a conflict, and `ready` gets what is left.

    Returns:
        How many, to leave free.
    """
    rank = rank_of(kind, reasons)
    return sum(r.rank < rank for r in runs(ctx, tick_id))


def rank_of(kind: RunKind, reasons: Iterable[ResumeReason]) -> Rank:
    """Where an overseer's `kind` dispatch for `reasons` stands in §7's order.

    A `feedback-plan` answers a human or a red build, and says which in no reason, so it is ranked a human waiting:
    never held behind a repair. A retired kind is refused before its rank matters.

    Returns:
        A `resume` its highest reason's rank, `implement` and `plan` `ready`'s.
    """
    match kind:
        case RunKind.RESUME:
            return min((REASON_RANKS[r] for r in reasons), default=Rank.HUMAN)
        case RunKind.FEEDBACK_PLAN:
            return Rank.HUMAN
        case RunKind.IMPLEMENT | RunKind.PLAN | RunKind.FIX_CI | RunKind.SPLIT | RunKind.NEEDS_PLAN:
            return Rank.READY
        case _:
            assert_never(kind)


def section(planned: Plan) -> ToCome | None:
    """The state block's `dispatches_to_come`, naming each and the workers its runs hold.

    Returns:
        It, or None when the harness makes none this tick.
    """
    if not planned.runs and not planned.chores:
        return None
    return {
        "holds_workers": len(planned.runs),
        "runs": [
            {"ticket": r.key, "repo": r.repo, "kind": RunKind.RESUME, "rows": [str(p) for p in r.phases]}
            for r in planned.runs
        ],
        "chores": list(planned.chores),
    }


def make(ctx: Context, tick_id: int, log: logs.TickAdapter) -> None:
    """Make the harness's dispatches in tick `tick_id`, after the overseer: runs in order, then chores.

    Each passes every guard an overseer's would, and is recorded as the harness's, its refusal too. A dry run checks
    the guards and records what it would have started, and starts nothing (D036).
    """
    tick = db.get_tick(ctx.conn, tick_id)
    dry_run = tick is not None and tick.dry_run
    planned = plan(ctx, tick_id, datetime.now(UTC))
    for run in planned.runs:
        _resume(ctx, tick_id, run, dry_run=dry_run, log=log)
    for name in planned.chores:
        _chore(ctx, tick_id, name, dry_run=dry_run, log=log)


def _held(conn: sqlite3.Connection) -> set[str]:
    """The tickets with an item the overseer holds open on the attention list: none gets the harness's run.

    What the item says may be why not to run, which is judgment; a `wait` acts on nothing, so the harness still takes
    one, and the item stands while it does (`attention.current`).

    Returns:
        Their keys.
    """
    items = attention.current(conn)
    return {i.ticket_key for i in items if i.ticket_key is not None and i.reason not in attention.HARNESS_REASONS}


def _run(ctx: Context, key: str, subjects: Sequence[phases.Derived]) -> TicketRun | None:
    """The run the harness makes of ticket `key`, from its derived `subjects`: its own row first, then its units'.

    Returns:
        The run, or None when the ticket is left to the overseer.
    """
    own, units = subjects[0], subjects[1:]
    if own.repo is not None or own.stale is not None or own.closed or not own.candidate or own.phases:
        return None
    if any(u.stale is not None or any(p not in ROWS for p in u.phases) for u in units):
        return None
    dispatching = [u for u in units if u.phases and u.repo is not None]
    # One run carries everything a unit needs (§8); a run per unit of several is the overseer's to order.
    if len(dispatching) != 1:
        return None
    [unit] = dispatching
    reasons = {ROWS[p].reason for p in unit.phases}
    if feedback_plans.needed(ctx.config.policy, reasons) or feedback_plans.current(ctx.conn, key) is not None:
        return None
    if conversation.is_started(conversation.start_of(ctx.conn, key)):
        label = None
    else:
        label = _label(ctx, key)
        if label is None:
            return None
    return TicketRun(key, str(unit.repo), tuple(unit.phases), label)


def _label(ctx: Context, key: str) -> str | None:
    """The configured queue label ticket `key` was last observed with, which authorizes its run (§8).

    Returns:
        The first of `tracker.labels` it carries, or None.
    """
    seen = records.fetch_one(
        ctx.conn,
        records.ObservedTicket,
        sql.select("*").from_("observed_tickets").where("key = ?", key),
    )
    if seen is None:
        return None
    names = {label["name"] for label in phases.labels_of(seen)}
    return next((label for label in ctx.config.tracker.labels if label in names), None)


def _resume(ctx: Context, tick_id: int, run: TicketRun, *, dry_run: bool, log: logs.TickAdapter) -> None:
    """Dispatch `run`, or in a dry run check its guards, and record the dispatch or its refusal as the harness's."""
    key, repos, kind = run.key, (run.repo,), RunKind.RESUME
    db.touch_ticket(ctx.conn, key, ctx.repo)
    rows = ", ".join(run.phases)
    try:
        if dry_run:
            dispatch.check(
                ctx,
                tick_id=tick_id,
                key=key,
                kind=kind,
                label=run.label,
                slug=None,
                base=None,
                repos=repos,
                reasons=run.reasons,
            )
            rationale = f"dry run: not dispatched; resume {key} in {run.repo}, for {rows}"
        else:
            started = dispatch.start(
                ctx,
                tick_id=tick_id,
                key=key,
                kind=kind,
                label=run.label,
                slug=None,
                base=None,
                context=run.context,
                repos=repos,
                reasons=run.reasons,
            )
            rationale = f"run {started.run_id}: resume {key} in {run.repo}, for {rows}"
    except dispatch.Refusal as r:
        _record(ctx, tick_id, key, f"refused:{r.guard}", r.reason)
        if r.attention is not None:
            _record(ctx, tick_id, key, f"{attention.ACTION_PREFIX}{r.attention}", r.reason, repo=r.repo)
        log.info("harness dispatch refused", extra={"ticket": key, "guard": r.guard, "reason": r.reason})
        return
    _record(ctx, tick_id, key, f"dispatch:{kind}", rationale)
    log.info("harness dispatched", extra={"ticket": key, "kind": kind, "dry_run": dry_run})


def _chore(ctx: Context, tick_id: int, name: str, *, dry_run: bool, log: logs.TickAdapter) -> None:
    """Start chore `name` with no context, or in a dry run check its guards, and record it as the harness's."""
    try:
        if dry_run:
            chore_start.check(ctx, tick_id=tick_id, name=name)
            rationale = f"dry run: not dispatched; {CHORE_WHY}"
        else:
            started = chore_start.start(ctx, tick_id=tick_id, name=name, context=None)
            rationale = f"chore run {started.run_id}; {CHORE_WHY}"
    except chore_start.Refusal as r:
        _record(ctx, tick_id, None, f"refused:{r.guard}", r.reason, chore=name)
        if r.attention is not None:
            _record(ctx, tick_id, None, f"{attention.ACTION_PREFIX}{r.attention}", r.reason, chore=name)
        log.info("harness chore run refused", extra={"chore": name, "guard": r.guard, "reason": r.reason})
        return
    _record(ctx, tick_id, None, chore_start.DISPATCH_ACTION, rationale, chore=name)
    log.info("harness started a chore", extra={"chore": name, "dry_run": dry_run})


def _record(
    ctx: Context,
    tick_id: int,
    key: str | None,
    action: str,
    rationale: str,
    *,
    repo: str | None = None,
    chore: str | None = None,
) -> None:
    db.record_decision(ctx.conn, tick_id, key, action, rationale, repo=repo, chore=chore, decider=Decider.HARNESS)
