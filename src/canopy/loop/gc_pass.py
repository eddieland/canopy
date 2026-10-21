"""What a live tick removes of canopy's own history (DESIGN §26): `canopy.log` rotated, and once a day, the pass.

The pass removes the files `gc.file_kinds` finds removable, the ones `canopy gc --dry-run` counts, and records itself in
`gc_passes`. Either step that fails is logged, and the tick goes on: a full disk is the pass's reason to run, and must
not stop the loop that would free it.
"""

from __future__ import annotations

import stat
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from canopy.core import db, gc_passes
from canopy.infra import logs
from canopy.loop import gc

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.core.context import Context

#: The least time from one pass's start to the next's.
PASS_EVERY = timedelta(days=1)


def run(ctx: Context, tick_id: int, log: logs.TickAdapter) -> int | None:
    """Rotate `canopy.log` if it is past `retention.log_max_mib`, then run the pass if none started in the last day.

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
    now = datetime.now(UTC)
    try:
        latest = gc_passes.latest(ctx.conn)
        if latest is not None and db.parse_time(latest.started_at) > now - PASS_EVERY:
            return None
        return _pass(ctx, tick_id, now, log)
    except Exception as e:
        log.exception("gc pass not recorded", extra={"error": str(e)})
        return None


def _pass(ctx: Context, tick_id: int, now: datetime, log: logs.TickAdapter) -> int:
    """Remove every file a pass at `now` finds removable, and record what it removed.

    Returns:
        The pass's id.
    """
    retention = ctx.config.retention
    removed: dict[str, gc_passes.Removed] = {}
    failures = 0
    error: str | None = None
    try:
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
                    removed[kind.name] = gc_passes.Removed(was.files + 1, was.bytes + found.size)
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
            "files": sum(r.files for r in removed.values()),
            "bytes": sum(r.bytes for r in removed.values()),
            "failures": failures,
        },
    )
    return pass_id


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
