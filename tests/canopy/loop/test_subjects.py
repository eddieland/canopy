"""The subjects a tick runs the overseer once for each of, in §7's order, and the capacity each is told (DESIGN §40)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from canopy.core import recorded_runs
from canopy.core.vocab import Phase, RecordedKind
from canopy.loop import phases, subjects, tick
from canopy.runs import reconcile
from tests.canopy.helpers import in_tick, seen

if TYPE_CHECKING:
    from canopy.core.context import Context
    from tests.conftest import CanopyEnv


def test_subjects_go_by_the_first_row_each_holds(ctx: Context, canopy_env: CanopyEnv) -> None:
    seen(ctx.conn, canopy_env, "PROJ-1", "PROJ-2", "PROJ-3", "PROJ-4")
    with in_tick(ctx.conn) as tick_id:
        # PROJ-3's human waits, PROJ-4's unit's build is red, PROJ-1 is new work, and PROJ-2 holds no row that
        # dispatches: a human first, then a repair, then `ready`, then the rest.
        phases.record(
            ctx.conn,
            tick_id,
            [
                phases.Derived("PROJ-1", None, (Phase.READY,), candidate=True, closed=False),
                phases.Derived("PROJ-2", None, (), candidate=True, closed=False),
                phases.Derived("PROJ-3", None, (Phase.NEEDS_HUMAN, Phase.HUMAN_REPLIED), candidate=True, closed=False),
                phases.Derived("PROJ-4", None, (), candidate=True, closed=False),
                phases.Derived("PROJ-4", "repo", (Phase.CI_RED,)),
            ],
        )
        said = messages(ctx, tick_id, running=0)
    assert [(s.name, s.new_work) for s, _ in said] == [
        ("PROJ-3", False),
        ("PROJ-4", False),
        ("PROJ-1", True),
        ("PROJ-2", False),
    ]


def test_a_subject_is_told_the_capacity_the_runs_before_it_left(ctx: Context, canopy_env: CanopyEnv) -> None:
    seen(ctx.conn, canopy_env, "PROJ-1")
    with in_tick(ctx.conn) as tick_id:
        phases.record(ctx.conn, tick_id, [phases.Derived("PROJ-1", None, (Phase.READY,), candidate=True, closed=False)])
        [(ready, _)] = messages(ctx, tick_id, running=0)
        base = reconcile.Capacity(max_workers=2, running=0)
        assert subjects.capacity(ctx, tick_id, base, ready) == {"max_workers": 2, "running": 0, "available": 2}
        # A run an earlier subject's run asked for holds a worker until the tick starts it.
        recorded_runs.record(ctx.conn, tick_id=tick_id, kind=RecordedKind.DISPATCH, request={}, ticket_key="PROJ-9")
        recorded_runs.record(ctx.conn, tick_id=tick_id, kind=RecordedKind.DISPATCH, request={}, ticket_key="PROJ-8")
        left = subjects.capacity(ctx, tick_id, base, ready)
    assert left == {"max_workers": 2, "running": 2, "available": 0}
    assert (ready.new_work, subjects.waits(ready, left)) == (True, True)


def messages(ctx: Context, tick_id: int, *, running: int) -> list[tuple[subjects.Subject, str]]:
    """Each subject and its message in tick `tick_id`, with `running` workers running."""
    capacity = reconcile.Capacity(max_workers=ctx.config.capacity.max_workers, running=running)
    return tick.subject_messages(
        ctx,
        tick_id=tick_id,
        dry_run=True,
        now=datetime.now(UTC),
        reconciled=reconcile.Reconciled(capacity),
    )
