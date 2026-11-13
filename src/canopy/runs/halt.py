"""`canopy stop --now` and `--wrap-up`: end the run working a ticket the operator stopped, or ask it to (DESIGN §22).

`canopy stop` marks the start record stopped first, so no dispatch starts another run. Ending the running one kills its
`_run`, which leads its own process group, and its worker's, then closes the run `stopped` as reconcile closes a run
whose `_run` is gone: its slots returned and its desk removed. That it was asked is recorded before the kill, so a stop
that dies after it leaves reconcile to close the run `stopped`, not `crashed`. `stopped` raises no attention item and
counts toward attempt limits like any ended run.

Asking it to wrap up writes a file in the run's answers directory, which canopy's plugin reads after each tool call: the
agent is told once to keep its work and report its result, and the run ends as any run does, on its own or at its
timeout. It is advice, as the clock's line is (§33): the timeout, and `--now`, stay what ends a run that goes on.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from canopy.core import cards, db
from canopy.core.vocab import RunStatus
from canopy.infra import procs
from canopy.runs import reconcile

if TYPE_CHECKING:
    from canopy.core import records
    from canopy.core.context import Context
    from canopy.infra import logs


def end(ctx: Context, run: records.Run, log: logs.TickAdapter) -> bool:
    """Kill run `run`'s processes and close it `stopped`.

    Returns:
        True once the run is closed, or False if it had already ended: nothing changes.

    Raises:
        pools.PoolError: a slot could not be returned; the next tick's reconcile returns it.
    """
    # Read again first: a run that ended since the stop read it signals nothing, so no pid it held, since reused, is.
    current = db.get_run(ctx.conn, run.id)
    if current is None or current["status"] != "running" or not db.ask_stop(ctx.conn, "runs", run.id):
        return False
    _kill(current["pid"])
    # Its `_run` first, so it starts no agent after this; then the worker the row names now, which may be one `_run`
    # started since the read above, such as a run asked again for its result (DESIGN §13).
    now = db.get_run(ctx.conn, run.id)
    _kill((now if now is not None else current)["worker_pid"])
    reconcile.end_run(ctx, current, RunStatus.STOPPED, reconcile.STOP_NOTE, log)
    return True


def _kill(pid: int | None) -> None:
    """Kill process group `pid`, if any, but never this process's own, as a `_run` run in-process by tests has."""
    if pid is not None and pid not in (os.getpid(), os.getpgid(0)):
        procs.kill_group(int(pid))


def wrap_up(ctx: Context, run: records.Run, log: logs.TickAdapter) -> bool:
    """Ask run `run`'s agent to wrap up: to keep its work and report its result, which it hears on its next call.

    Returns:
        True once asked, or False if the run had already ended: nothing changes.
    """
    current = db.get_run(ctx.conn, run.id)
    if current is None or current["status"] != "running":
        return False
    if not cards.ask_wrap_up(cards.answers_dir(ctx.state_dir, str(run.id))):
        return False
    log.info("run asked to wrap up", extra={"run_id": run.id, "ticket": run.ticket_key})
    return True
