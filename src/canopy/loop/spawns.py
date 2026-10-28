"""The tick starts every run (DESIGN §40, ROADMAP M40): the overseer's recorded runs and the harness's, after its run.

A run the overseer asks for, a dispatch, a review, a revision, or a chore's, is recorded at the ask, never spawned from
the overseer's process tree (`core.recorded_runs`). Once the overseer's run has ended, whatever it ended as, the tick
spawns each with the harness's own dispatches (§37), in §7's order: the runs and reviews by the rank of the row each
answers, the harness's first within a rank, since it planned them before the overseer ran, then the chores, the
overseer's before the harness's. Each is checked against every guard again, as the harness's are, and its decision is
recorded as it starts, or its refusal then like any other. A dry run recorded none, and checks the harness's only.

So no run is the overseer's descendant: nothing it asked for dies when its run ends, or inherits a sandbox around it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, assert_never

from canopy.core import db, recorded_runs, review_requests
from canopy.core.vocab import RecordedKind, RecordedStatus, ResumeReason, RunKind
from canopy.loop import chore_tools, harness_dispatches, review_tools, tools
from canopy.loop.harness_dispatches import Rank

if TYPE_CHECKING:
    from collections.abc import Callable

    from canopy.core import records
    from canopy.core.context import Context
    from canopy.infra import logs

#: The guard a recorded run is refused under when starting it raised; what it was for is decided again next tick.
SPAWN_FAILED: Final = "spawn_failed"
#: Where the chores go in the order: after every run, as the harness's own always have.
CHORES: Final = len(Rank)


def make(ctx: Context, tick_id: int, log: logs.TickAdapter) -> None:
    """Start the runs tick `tick_id` recorded and the harness's dispatches, after the overseer, in §7's order.

    What one raises is logged, and for a recorded run recorded as its refusal, so it holds up none after it.
    """
    tick = db.get_tick(ctx.conn, tick_id)
    dry_run = tick is not None and tick.dry_run
    planned = harness_dispatches.plan(ctx, tick_id, datetime.now(UTC))
    steps = [
        *(
            _Step((r.rank, 0, i), lambda r=r: harness_dispatches.make_resume(ctx, tick_id, r, dry_run=dry_run, log=log))
            for i, r in enumerate(planned.runs)
        ),
        *(_recorded(ctx, a, log) for a in recorded_runs.of_tick(ctx.conn, tick_id)),
        *(
            _Step((CHORES, 1, i), lambda n=n: harness_dispatches.make_chore(ctx, tick_id, n, dry_run=dry_run, log=log))
            for i, n in enumerate(planned.chores)
        ),
    ]
    for step in sorted(steps, key=lambda s: s.order):
        try:
            step.do()
        except Exception as e:
            log.exception("starting a run after the overseer raised", extra={"error": str(e)})


def start(ctx: Context, recorded: records.RecordedRun) -> None:
    """Start `recorded` through its kind's verb, under its guards again, which records its decision or its refusal."""
    match recorded.kind:
        case RecordedKind.DISPATCH:
            tools.spawn_dispatch(ctx, recorded)
        case RecordedKind.REVIEW:
            review_tools.spawn_review(ctx, recorded)
        case RecordedKind.REVISION:
            review_tools.spawn_revision(ctx, recorded)
        case RecordedKind.CHORE:
            chore_tools.spawn_chore(ctx, recorded)
        case _:
            assert_never(recorded.kind)


@dataclass(frozen=True)
class _Step:
    """One run the tick starts after the overseer: where it goes in the order, and what starts it."""

    #: Its rank in §7's order, then whose it is within the rank, then the order it was planned or asked in.
    order: tuple[int, int, int]
    do: Callable[[], None] = field(compare=False)


def _recorded(ctx: Context, recorded: records.RecordedRun, log: logs.TickAdapter) -> _Step:
    """The step that spawns `recorded` by its kind's verb, recording its refusal should spawning it raise.

    Returns:
        The step, in its place in the order.
    """

    def do() -> None:
        try:
            start(ctx, recorded)
        except Exception as e:
            log.exception("starting a recorded run raised", extra={"recorded_run_id": recorded.id, "error": str(e)})
            if recorded_runs.close(ctx.conn, recorded.id, RecordedStatus.REFUSED):
                db.record_decision(
                    ctx.conn,
                    recorded.tick_id,
                    recorded.ticket_key,
                    f"refused:{SPAWN_FAILED}",
                    f"the tick could not start recorded run {recorded.id}: {type(e).__name__}: {e}",
                    pr=recorded.pr_url,
                    chore=recorded.chore,
                )

    return _Step(_order(ctx, recorded), do)


def _order(ctx: Context, recorded: records.RecordedRun) -> tuple[int, int, int]:
    """Where `recorded` goes among the tick's starts, after the harness's of its rank and in the order it was asked.

    A dispatch goes by its kind and reasons, a review first when the operator requested it, a revision first, as the
    operator's note asks for it, and a chore after every run, before the harness's chores.

    Returns:
        Its rank in §7's order, its place within the rank, and its id.
    """
    match recorded.kind:
        case RecordedKind.DISPATCH:
            asked = recorded_runs.request_of(recorded)
            reasons = asked.get("reasons")
            named = [ResumeReason(str(r)) for r in reasons] if isinstance(reasons, list) else []
            return harness_dispatches.rank_of(RunKind(str(asked["kind"])), named), 1, recorded.id
        case RecordedKind.REVIEW:
            requested = recorded.ticket_key is None and recorded.pr_url is not None
            if requested and review_requests.open_request(ctx.conn, str(recorded.pr_url)) is not None:
                return Rank.REQUESTED, 1, recorded.id
            return Rank.REVIEW, 1, recorded.id
        case RecordedKind.REVISION:
            return Rank.REQUESTED, 1, recorded.id
        case RecordedKind.CHORE:
            return CHORES, 0, recorded.id
        case _:
            assert_never(recorded.kind)
