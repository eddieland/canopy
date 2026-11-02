"""What a live tick removes of canopy's own history (DESIGN §26): `canopy.log` rotated, and once a day, the pass.

The pass removes the files `gc.file_kinds` finds removable and the journal's rows `gc.row_kinds` does, the ones
`canopy gc --dry-run` counts, records itself in `gc_passes`, and checkpoints the journal's WAL. Any step that fails is
logged, and the tick goes on: a full disk is the pass's reason to run, and must not stop the loop that would free it.
"""

from __future__ import annotations

import stat
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from canopy.core import db, gc_passes, sql
from canopy.infra import logs, tracing
from canopy.loop import gc

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from canopy.core.config import Retention
    from canopy.core.context import Context

#: The least time from one pass's start to the next's.
PASS_EVERY = timedelta(days=1)


def run(ctx: Context, tick_id: int, log: logs.TickAdapter) -> int | None:
    """Rotate `canopy.log` and the traces file past `retention.log_max_mib`, then run the pass if none ran in a day.

    Only a live tick runs it, under the tick lock, so no two passes or rotations run at once.

    Returns:
        The id of the pass it recorded, or None when none was due, or it could not be recorded.
    """
    retention = ctx.config.retention
    try:
        dropped = logs.rotate(ctx.state_dir, max_bytes=retention.log_max_mib * gc.MIB, keep=retention.log_keep)
    except Exception as e:
        log.exception("canopy.log not rotated", extra={"error": str(e)})
    else:
        if dropped:
            log.info("canopy.log rotated", extra={"removed": [p.name for p in dropped]})
    # The traces file, kept as the log is: each process appends to it anew, so follows a rotation (`otlp`).
    try:
        dropped = logs.rotate(
            ctx.state_dir,
            max_bytes=retention.log_max_mib * gc.MIB,
            keep=retention.log_keep,
            name=tracing.TRACES_FILE_NAME,
        )
    except Exception as e:
        log.exception("traces not rotated", extra={"error": str(e)})
    else:
        if dropped:
            log.info("traces rotated", extra={"removed": [p.name for p in dropped]})
    now = datetime.now(UTC)
    try:
        latest = gc_passes.latest(ctx.conn)
        if latest is not None and db.parse_time(latest.started_at) > now - PASS_EVERY:
            return None
        pass_id = _pass(ctx, tick_id, now, log)
    except Exception as e:
        log.exception("gc pass not recorded", extra={"error": str(e)})
        return None
    checkpoint(ctx.conn, log)
    return pass_id


def checkpoint(conn: sqlite3.Connection, log: logs.TickAdapter) -> bool:
    """Copy the journal's WAL into it and empty the WAL, `PRAGMA wal_checkpoint(TRUNCATE)`, logging how it went.

    A reader holding an older snapshot, such as the web UI's, keeps the WAL until it lets go; the next pass takes it.

    Returns:
        Whether the WAL was emptied.
    """
    try:
        busy, frames, copied = sql.execute(conn, sql.frag("PRAGMA wal_checkpoint(TRUNCATE)")).fetchone()
    except Exception as e:
        log.exception("journal not checkpointed", extra={"error": str(e)})
        return False
    log.info("journal checkpointed", extra={"busy": bool(busy), "frames": frames, "copied": copied})
    return not busy


def _pass(ctx: Context, tick_id: int, now: datetime, log: logs.TickAdapter) -> int:
    """Remove every file and journal row a pass at `now` finds removable, and record what it removed.

    Returns:
        The pass's id.
    """
    retention = ctx.config.retention
    removed: dict[str, gc_passes.Removed] = {}
    failures = 0
    error: str | None = None
    try:
        failures = _files(ctx, now, removed, log)
        # After the files: on a full disk, deleting rows needs the room removing them makes.
        removed.update(_rows(ctx.conn, now, retention))
    except Exception as e:
        log.exception("gc pass failed", extra={"error": str(e)})
        error = f"{type(e).__name__}: {e}"
    pass_id = gc_passes.record(
        ctx.conn,
        tick_id=tick_id,
        started_at=now,
        run_files_days=retention.run_files_days,
        tick_files_days=retention.tick_files_days,
        run_cutoff=gc.retention_cutoff(now, retention.run_files_days) or None,
        tick_cutoff=gc.retention_cutoff(now, retention.tick_files_days) or None,
        removed=removed,
        failures=failures,
        error=error,
    )
    log.info(
        "gc pass",
        extra={
            "gc_pass": pass_id,
            "files": sum(r.count for r in removed.values() if r.unit == "files"),
            "rows": sum(r.count for r in removed.values() if r.unit == "rows"),
            "bytes": sum(r.bytes for r in removed.values()),
            "failures": failures,
        },
    )
    return pass_id


def _files(ctx: Context, now: datetime, removed: dict[str, gc_passes.Removed], log: logs.TickAdapter) -> int:
    """Remove every file a pass at `now` finds removable, counting each kind's in `removed` as it goes.

    Returns:
        How many it found removable but could not remove.
    """
    failures = 0
    for kind in gc.file_kinds(ctx, now):
        for found in kind.files:
            if not found.removable:
                continue
            try:
                gone = _remove(found.path)
            except OSError as e:
                failures += 1
                log.warning("gc could not remove a file", extra={"path": str(found.path), "error": str(e)})
                continue
            if gone:
                was = removed.get(kind.name, gc_passes.Removed(0, 0))
                removed[kind.name] = gc_passes.Removed(was.count + 1, was.bytes + found.size)
    return failures


def _remove(path: Path) -> bool:
    """Remove `path` if it is still a regular file: one replaced by a link since it was found stays.

    Returns:
        Whether it removed it; a file already gone is not removed again.
    """
    try:
        found = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(found.st_mode):
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


def _rows(conn: sqlite3.Connection, now: datetime, retention: Retention) -> dict[str, gc_passes.Removed]:
    """Delete every journal row a pass at `now` finds removable.

    One transaction, so no tick closes between finding the window and deleting outside it.

    Returns:
        What it deleted of each kind, the kinds it deleted none of left out.
    """
    removed: dict[str, gc_passes.Removed] = {}
    with db.transaction(conn):
        for row_kind in gc.row_kinds(conn, now, retention):
            found = row_kind.kind(conn)
            if not found.removable:
                continue
            deleted = row_kind.delete().run(conn).rowcount
            removed[row_kind.name] = gc_passes.Removed(deleted, found.removable_size, unit="rows")
    return removed
