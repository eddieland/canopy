"""`canopy gc --vacuum`: the journal's free pages given back to the disk (DESIGN §26, The journal).

`VACUUM` writes a whole copy of the journal before the copy takes its place, holding the journal's write lock all the
while. So it runs only between ticks, under the tick lock and the dispatch lock, which no tick and no run's start can
then take; only while no run is live, since a live run writes the journal; and only when the journal's disk has room
for the copy. The loop never runs it on its own.
"""

from __future__ import annotations

import shutil
from contextlib import ExitStack
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import db, sql
from canopy.core.context import db_path
from canopy.infra import lock, logs
from canopy.loop import gc, gc_pass

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.core.context import Context


class RefusedError(Exception):
    """`--vacuum` does not run now, and the message says why."""


@dataclass(frozen=True)
class Vacuumed:
    """What `--vacuum` did: the journal's bytes, its WAL's with them, before and after."""

    before: int
    after: int
    #: Whether the WAL was emptied after: while a reader holds it, the journal shrinks only once it lets go.
    checkpointed: bool


def vacuum(ctx: Context) -> Vacuumed:
    """Run `VACUUM` on the journal, then empty its WAL, so the file shrinks by its free pages.

    Returns:
        The journal's size before and after.

    Raises:
        RefusedError: A tick is running or a run is starting, a run is live, or the disk has less free space than the
            journal takes.
    """
    journal = db_path(ctx.ws)
    log = logs.for_tick(None)
    with ExitStack() as stack:
        try:
            stack.enter_context(lock.hold(ctx.lock_path))
            stack.enter_context(lock.hold(ctx.dispatch_lock_path))
        except lock.LockBusyError as e:
            raise RefusedError("a tick is running, or a run is starting; run it again between ticks") from e
        live = db.live_runs(ctx.conn)
        if live:
            runs = f"{live[0]} is" if len(live) == 1 else f"{', '.join(live)} are"
            raise RefusedError(f"{runs} live and writes the journal; run it again once no run is")
        gc_pass.checkpoint(ctx.conn, log)
        before = _size(journal)
        free = shutil.disk_usage(journal.parent).free
        if free < before:
            raise RefusedError(
                f"the journal takes {before / gc.MIB:.1f} MiB and its disk has {free / gc.MIB:.1f} MiB free; "
                "VACUUM writes a whole copy of it first",
            )
        sql.execute(ctx.conn, sql.frag("VACUUM"))
        checkpointed = gc_pass.checkpoint(ctx.conn, log)
        after = _size(journal)
    log.info("journal vacuumed", extra={"before": before, "after": after, "checkpointed": checkpointed})
    return Vacuumed(before, after, checkpointed)


def _size(journal: Path) -> int:
    """The bytes of the journal and its WAL, either missing counting nothing.

    Returns:
        Their sum.
    """
    total = 0
    for path in (journal, journal.with_name(f"{journal.name}-wal")):
        try:
            total += path.stat().st_size
        except FileNotFoundError:
            continue
    return total
