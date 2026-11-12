"""The span an agent run traces its own process under: which run it is, what canopy chose for it, and how it ended.

Each detached run, `canopy _run` and the others, is a trace of its own (D132), its root span named for its table. The
span carries the run's id, and what the journal and config say canopy chose for it, each one of canopy's own facts: its
role, a worker run's kind and attempt, the model canopy asked for, and whether it ran in the sandbox. It ends with the
run's status, and one in `FAILED_RUN_STATUSES` marks it failed, as a block that raises does: a run that failed without
raising would otherwise read as one that went well, and a backend's filter for errors would miss it.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, assert_never

from canopy.core import records, sandboxing
from canopy.core.run_metrics import ROLES
from canopy.core.vocab import FAILED_RUN_STATUSES
from canopy.infra import tracing

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.context import Context
    from canopy.core.db import RunTable
    from canopy.core.vocab import AnyRunStatus

#: Each run table's span: its name, and the attribute it names its run by.
SPANS: Mapping[RunTable, tuple[str, str]] = {
    "runs": ("run", "run_id"),
    "task_runs": ("task", "task_run_id"),
    "epic_runs": ("epic", "epic_run_id"),
    "chore_runs": ("chore", "chore_run_id"),
    "review_runs": ("review", "review_run_id"),
}


@contextlib.contextmanager
def span(
    ctx: Context,
    table: RunTable,
    run_id: int,
    *,
    attempt: Callable[[sqlite3.Connection, int], int | None] | None = None,
) -> Iterator[RunSpan]:
    """Trace the `with` block, run `run_id` of `table` at work, as a trace of its own, linked to what started it.

    `attempt` numbers the run's attempt, from the journal and its id, for a table whose runs count their attempts. It
    and the rest the span says of the run are read only while tracing is on.

    Yields:
        The run's span, to end with its status.
    """
    name, key = SPANS[table]
    with tracing.span(name, new_trace=True) as traced:
        traced.set(**{key: run_id})
        if tracing.enabled():
            traced.set(
                **_chosen(ctx, table, run_id),
                attempt=attempt(ctx.conn, run_id) if attempt is not None else None,
            )
        yield RunSpan(traced)


@dataclass(frozen=True)
class RunSpan:
    """A run's span, while the run is at work."""

    traced: tracing.Span

    def ended(self, status: AnyRunStatus) -> None:
        """Set the status the run ended in, and mark the span failed when the status is a failure."""
        self.traced.set(status=status)
        if status in FAILED_RUN_STATUSES:
            self.traced.fail(status)


class _Chosen(Protocol):
    """What every run table's row says of the model canopy chose for its agent."""

    @property
    def model(self) -> str | None:
        """The model canopy asked the runtime for; None when it chose none."""
        ...


def _chosen(ctx: Context, table: RunTable, run_id: int) -> dict[str, tracing.Attribute]:
    """What canopy chose for run `run_id` of `table`, as its span's attributes; only its role, for a run not found.

    Returns:
        The attributes: the role, a worker run's kind, the model, and whether it ran sandboxed.
    """
    conn = ctx.conn
    row: _Chosen | None
    repos: Sequence[str | None] = ()
    match table:
        case "runs":
            row = records.select(records.Run).where("id = ?", run_id).one(conn)
            repos = [s.repo for s in records.select(records.RunSlot).where("run_id = ?", run_id).all(conn)]
        case "epic_runs":
            row = records.select(records.EpicRun).where("id = ?", run_id).one(conn)
            repos = [s.repo for s in records.select(records.EpicRunSlot).where("run_id = ?", run_id).all(conn)]
        case "task_runs":
            task_run = records.select(records.TaskRun).where("id = ?", run_id).one(conn)
            row, repos = task_run, [task_run.repo] if task_run else []
        case "review_runs":
            review_run = records.select(records.ReviewRun).where("id = ?", run_id).one(conn)
            row, repos = review_run, [review_run.repo] if review_run else []
        case "chore_runs":
            # canopy never starts a chore's agent in the sandbox (DESIGN §24), whatever its command does.
            row = records.select(records.ChoreRun).where("id = ?", run_id).one(conn)
        case _:
            assert_never(table)
    if row is None:
        return {"role": ROLES[table]}
    return {
        "role": ROLES[table],
        "kind": row.kind if isinstance(row, records.Run) else None,
        "model": row.model,
        "sandboxed": sandboxing.sandboxed(ctx.config.runtime, repos),
    }
