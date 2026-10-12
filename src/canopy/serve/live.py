"""The event stream (DESIGN §22): the lists a page shows, sent again whole whenever the journal changes.

SQLite has no change notifications, so each stream holds its own journal connection and reads `PRAGMA data_version`
four times a second: it changes whenever another connection commits. Only then does the stream read the attention
list, the runs, the tickets, the chores, the last day's and 30 days' spend, and the latest tick again, and it sends
each that differs from what it sent last, plus `ticket.changed` for each ticket whose summary changed. The stream never
writes, so its own reads never move `data_version`.

The connection is opened and used only by the stream's own coroutine, on the server's event loop: the reads are small
and quick, and keeping them on one thread is what sqlite3 requires of a connection.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from canopy.serve import views
from canopy.serve.schema import (
    AttentionUpdated,
    ChoresUpdated,
    LastTick,
    RunsUpdated,
    Spend,
    SpendUpdated,
    StreamEvent,
    TicketChanged,
    TicketSummary,
    TicketsUpdated,
    TickUpdated,
)

if TYPE_CHECKING:
    from canopy.core.context import Context
    from canopy.serve.backend import Backend

# Reading one pragma costs next to nothing, and a server has a handful of streams open, so a change shows within a
# quarter of a second rather than within one.
POLL_SECONDS = 0.25


async def events(backend: Backend, *, poll_seconds: float = POLL_SECONDS) -> AsyncIterator[StreamEvent]:
    """Yield every list, the spend, and the latest tick at once, then whatever changes, until the client leaves."""
    with backend.open() as ctx:
        state = _Sent()
        version: int | None = None
        while True:
            current = _data_version(ctx)
            if current != version:
                version = current
                for event in state.changes(backend, ctx):
                    yield event
            await asyncio.sleep(poll_seconds)


def _data_version(ctx: Context) -> int:
    row = ctx.conn.execute("PRAGMA data_version").fetchone()
    return int(row[0])


class _Sent:
    """What one stream has sent: each list and the spend as they were last sent, and each ticket's summary."""

    def __init__(self) -> None:
        self.attention: AttentionUpdated | None = None
        self.runs: RunsUpdated | None = None
        self.chores: ChoresUpdated | None = None
        self.tickets: dict[str, TicketSummary] | None = None
        self.spend: list[Spend] | None = None
        self.tick: LastTick | None = None

    def changes(self, backend: Backend, ctx: Context) -> list[StreamEvent]:
        """Read the lists again and return an event for each that differs from what was sent, remembering it."""
        found: list[StreamEvent] = []
        attention = AttentionUpdated(items=views.attention(backend, ctx))
        if attention != self.attention:
            self.attention = attention
            found.append(StreamEvent(attention))
        runs = RunsUpdated(runs=views.runs(ctx))
        if runs != self.runs:
            self.runs = runs
            found.append(StreamEvent(runs))
        tickets = views.tickets(ctx)
        by_key = {t.key: t for t in tickets}
        if self.tickets is None or by_key != self.tickets:
            before = self.tickets or {}
            changed = [k for k, t in by_key.items() if self.tickets is not None and before.get(k) != t]
            self.tickets = by_key
            found.append(StreamEvent(TicketsUpdated(tickets=tickets)))
            found.extend(StreamEvent(TicketChanged(key=k)) for k in changed)
        chores = ChoresUpdated(chores=views.chores(backend, ctx))
        if chores != self.chores:
            self.chores = chores
            found.append(StreamEvent(chores))
        # Sent when a cost changes, not a window: the windows move with the clock on every read.
        spend = views.spend(backend, ctx)
        if self.spend is None or [s.cost_usd for s in spend] != [s.cost_usd for s in self.spend]:
            self.spend = spend
            found.append(StreamEvent(SpendUpdated(spend=spend)))
        last = views.last_tick(ctx)
        if last != self.tick:
            self.tick = last
            found.append(StreamEvent(TickUpdated(tick=last.tick, acknowledged=last.acknowledged)))
        return found
