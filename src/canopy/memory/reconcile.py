"""Memory's part of the tick's reconcile (DESIGN §6 step 3, §28): proposals nobody reviewed expire."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from canopy.core import db, memory
from canopy.core.vocab import MemoryScope, MemoryStatus

if TYPE_CHECKING:
    from canopy.core.context import Context
    from canopy.infra import logs


def run(ctx: Context, log: logs.TickAdapter) -> int:
    """Invalidate each pending proposal written more than `memory.PROPOSAL_DAYS` ago, in every mode, off included.

    Returns:
        How many expired.
    """
    cutoff = db.format_time(datetime.now(UTC) - timedelta(days=memory.PROPOSAL_DAYS))
    cur = ctx.conn.execute(
        "UPDATE memories SET status = ?, why = 'expired', invalidated_at = ? "
        "WHERE scope = ? AND status = ? AND created_at < ?",
        (MemoryStatus.INVALID, db.now(), MemoryScope.PROPOSAL, MemoryStatus.PENDING, cutoff),
    )
    if cur.rowcount:
        log.info("proposals expired", extra={"count": cur.rowcount})
    return cur.rowcount
