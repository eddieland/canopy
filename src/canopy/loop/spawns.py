"""What a tick starts once the overseer's run ends (DESIGN §8, §37): the runs it recorded, and the harness's own.

A dispatch, review, revision, or chore run the overseer asks for is recorded at the ask (`core.recorded_runs`), never
spawned from the overseer's process tree, so nothing it asked for dies with it, and no run inherits a sandbox around it.
After the overseer's run, whatever it ended as, the tick starts every run it recorded together with the harness's own
dispatches, in §7's order (`harness_dispatches.Rank`), chores last. Within a rank, the overseer's go first, as they
were checked at the ask before the harness's of that rank were made, and then in the order they were asked for. Each
passes every guard again, and a refusal then is recorded like any other. A dry run records none, so it makes only the
harness's, checking their guards (D036).
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, assert_never

from canopy.core import db, recorded_runs
from canopy.core.vocab import RecordedKind
from canopy.loop import chore_tools, harness_dispatches, review_tools, tools

if TYPE_CHECKING:
    from collections.abc import Callable

    from canopy.core import records
    from canopy.core.context import Context
    from canopy.infra import logs


@dataclass(frozen=True)
class _Start:
    """One start the tick makes after the overseer: its place in the order, and how to make it."""

    #: Its place in §7's order (`harness_dispatches.Rank`).
    rank: int
    #: Whether it is the harness's own: within a rank, the overseer's recorded runs go first.
    harness: bool
    #: Its order within its side and rank: a recorded run's id, or the harness's place in its plan.
    order: int
    #: What it says it is, in the log should it raise.
    what: str
    make: Callable[[], None]


def make(ctx: Context, tick_id: int, log: logs.TickAdapter) -> None:
    """Start, after the overseer, every run tick `tick_id` recorded, and make the harness's dispatches, in §7's order.

    What one start raises is logged, and the rest go on: a recorded run it left is closed unstarted with the tick.
    """
    tick = db.get_tick(ctx.conn, tick_id)
    dry_run = tick is not None and tick.dry_run
    planned = harness_dispatches.plan(ctx, tick_id, datetime.now(UTC))
    starts = [
        *(_recorded(ctx, asked) for asked in recorded_runs.of_tick(ctx.conn, tick_id)),
        *(
            _Start(
                run.rank,
                harness=True,
                order=i,
                what=f"the harness's resume of {run.key}",
                make=functools.partial(harness_dispatches.make_resume, ctx, tick_id, run, dry_run=dry_run, log=log),
            )
            for i, run in enumerate(planned.runs)
        ),
        *(
            _Start(
                harness_dispatches.Rank.CHORE,
                harness=True,
                order=i,
                what=f"the harness's chore {name}",
                make=functools.partial(harness_dispatches.make_chore, ctx, tick_id, name, dry_run=dry_run, log=log),
            )
            for i, name in enumerate(planned.chores)
        ),
    ]
    for start in sorted(starts, key=lambda s: (s.rank, s.harness, s.order)):
        try:
            start.make()
        except Exception as e:
            log.exception("a start after the overseer raised", extra={"start": start.what, "error": str(e)})


def start_recorded(ctx: Context, asked: records.RecordedRun) -> None:
    """Start the run `asked` recorded, under every guard again, as its tick does once the overseer's run ends."""
    match asked.kind:
        case RecordedKind.DISPATCH:
            tools.start_dispatch(ctx, asked)
        case RecordedKind.REVIEW:
            review_tools.start_review(ctx, asked)
        case RecordedKind.REVISION:
            review_tools.start_revision(ctx, asked)
        case RecordedKind.CHORE:
            chore_tools.start_chore(ctx, asked)
        case _:
            assert_never(asked.kind)


def _recorded(ctx: Context, asked: records.RecordedRun) -> _Start:
    """The start of the run `asked` recorded.

    Returns:
        It, at the rank it was recorded with, in the order it was asked for.
    """
    start = functools.partial(start_recorded, ctx, asked)
    return _Start(asked.rank, harness=False, order=asked.id, what=f"recorded run {asked.id} ({asked.kind})", make=start)
