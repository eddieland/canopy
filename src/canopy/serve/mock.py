"""Fixtures for the sessions and leases endpoints, which have no source in the journal yet (ROADMAP M20).

Deterministic: fixed times, and a stream that moves through a fixed cycle, so screenshots and tests are stable.
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from canopy.serve.schema import Lease, LeaseState, LeaseUpdated, Session, SessionState, SessionUpdated, StreamEvent

_T0 = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def _at(minutes: int) -> datetime:
    return _T0 + timedelta(minutes=minutes)


SESSIONS: tuple[Session, ...] = (
    Session(
        id="run:41",
        subject="ABC-101",
        kind="worker",
        state="running",
        started_at=_at(0),
        updated_at=_at(12),
        cost_usd=0.42,
        lease_id="lease:1",
    ),
    Session(
        id="run:42",
        subject="ABC-102",
        kind="worker",
        state="blocked",
        started_at=_at(-30),
        updated_at=_at(-4),
        cost_usd=1.07,
        lease_id="lease:2",
    ),
    Session(id="run:43", subject="web#88", kind="review", state="idle", started_at=_at(-5), updated_at=_at(-1)),
    Session(
        id="run:39",
        subject="ABC-099",
        kind="worker",
        state="done",
        started_at=_at(-90),
        updated_at=_at(-61),
        ended_at=_at(-61),
        cost_usd=2.31,
    ),
    Session(
        id="run:40",
        subject="chore:deps",
        kind="chore",
        state="failed",
        started_at=_at(-75),
        updated_at=_at(-70),
        ended_at=_at(-70),
        cost_usd=0.18,
    ),
)

LEASES: tuple[Lease, ...] = (
    Lease(
        id="lease:1",
        repo="acme/web",
        path="~/.treehouse/web-1",
        state="held",
        session_id="run:41",
        acquired_at=_at(0),
        expires_at=_at(60),
    ),
    Lease(
        id="lease:2",
        repo="acme/web",
        path="~/.treehouse/web-2",
        state="expiring",
        session_id="run:42",
        acquired_at=_at(-30),
        expires_at=_at(2),
    ),
    Lease(id="lease:3", repo="acme/api", path="~/.treehouse/api-1", state="released"),
)

_SESSION_CYCLE: tuple[SessionState, ...] = ("running", "blocked", "idle", "running", "done")
_LEASE_CYCLE: tuple[LeaseState, ...] = ("held", "expiring", "released", "held")


def events() -> AsyncIterator[StreamEvent]:
    """Return an endless stream of updates, one per call to `__anext__`, without waiting between them."""
    return _cycle()


async def _cycle() -> AsyncIterator[StreamEvent]:
    first, lease = SESSIONS[0], LEASES[0]
    for step in itertools.count(1):
        if step % 3:
            state = _SESSION_CYCLE[step % len(_SESSION_CYCLE)]
            session = first.model_copy(update={"state": state, "updated_at": _at(12 + step)})
            yield StreamEvent(SessionUpdated(session=session))
        else:
            state = _LEASE_CYCLE[step % len(_LEASE_CYCLE)]
            yield StreamEvent(LeaseUpdated(lease=lease.model_copy(update={"state": state})))
        await asyncio.sleep(0)


async def paced(seconds: float | None) -> AsyncIterator[StreamEvent]:
    """Yield `events()` one every `seconds`, or nothing, forever, when `seconds` is None."""
    if seconds is None:
        await asyncio.Event().wait()
        return
    async for event in events():
        await asyncio.sleep(seconds)
        yield event
