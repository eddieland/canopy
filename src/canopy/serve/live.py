"""The event stream (DESIGN §22): the lists a page shows, sent again whole whenever the journal changes.

SQLite has no change notifications, so each stream holds its own journal connection and reads `PRAGMA data_version` four
times a second: it changes whenever another connection commits. Only then, or when the loop has read its config again
(`Backend.use`), does the stream read the attention list, the runs, the tickets, the chores, the last day's and 30 days'
spend, the latest tick, and the loop's pause again, and it sends each that differs from what it sent last, plus
`ticket.changed` for each ticket whose summary changed. A reload commits nothing, but the chores and the attention list
are read through the config: a chore added to it shows without a journal write. The stream never writes, so its own
reads never move `data_version`. Each such read is one snapshot of the journal, in a read transaction, so a commit
landing partway through cannot pair one list's old rows with another's new ones.

The connection is opened, read, and closed on a thread of the stream's own, never on the server's event loop: on a
journal with months of history one read of the lists takes tens of milliseconds, every open stream reads them on each
commit, and a tick commits each decision it records, so reading them on the event loop held up every other request
while the overseer worked. One thread per stream keeps its connection on one thread, as sqlite3 requires.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from typing import TYPE_CHECKING

from canopy.serve import views
from canopy.serve.schema import (
    AttentionUpdated,
    ChoresUpdated,
    LastTick,
    LoopState,
    LoopUpdated,
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
    """Yield every list, the spend, the latest tick, and the pause at once, then whatever changes, until the end."""
    thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="canopy-stream")
    reader = _Reader(backend)
    loop = asyncio.get_running_loop()
    try:
        while True:
            for event in await loop.run_in_executor(thread, reader.read):
                yield event
            await asyncio.sleep(poll_seconds)
    finally:
        # Queued behind a read still running when the client left, so the connection closes on its own thread, and
        # without waiting for that read here, on the event loop.
        thread.submit(reader.close)
        thread.shutdown(wait=False)


class _Reader:
    """One stream's journal connection and what it has sent: used only on the stream's own thread."""

    def __init__(self, backend: Backend) -> None:
        self._backend = backend
        self._opened = ExitStack()
        self._ctx: Context | None = None
        self._sent = _Sent()
        self._version: int | None = None

    def read(self) -> list[StreamEvent]:
        """The events for whatever changed since the last read: none if neither the journal nor the config has.

        Returns:
            One event per list that differs from what this stream last sent; empty when neither the journal nor the
            config the loop serves has changed.
        """
        if self._ctx is None:
            self._ctx = self._opened.enter_context(self._backend.open())
        current = _data_version(self._ctx)
        served = self._backend.current(self._ctx)
        if current == self._version and served is self._ctx:
            return []
        self._version, self._ctx = current, served
        return self._sent.changes(self._backend, self._ctx)

    def close(self) -> None:
        """Close the connection, if a read opened one."""
        self._opened.close()


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
        self.spend: Spend | None = None
        self.tick: LastTick | None = None
        self.loop: LoopState | None = None

    def changes(self, backend: Backend, ctx: Context) -> list[StreamEvent]:
        """Read the lists again, from one snapshot, and return an event for each that differs from what was sent.

        Returns:
            The events in a fixed order, with a `TicketChanged` for each ticket whose summary changed; empty when
            nothing did.
        """
        with _snapshot(ctx):
            return self._read(backend, ctx)

    def _read(self, backend: Backend, ctx: Context) -> list[StreamEvent]:
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
        if self.spend is None or _costs(spend) != _costs(self.spend):
            self.spend = spend
            found.append(StreamEvent(SpendUpdated(spend=spend)))
        last = views.last_tick(ctx)
        if last != self.tick:
            self.tick = last
            found.append(StreamEvent(TickUpdated(tick=last.tick, acknowledged=last.acknowledged)))
        loop = views.loop_state(ctx)
        if loop != self.loop:
            self.loop = loop
            found.append(StreamEvent(LoopUpdated(paused=loop.paused)))
        return found


@contextmanager
def _snapshot(ctx: Context) -> Iterator[None]:
    """Every read in the block sees the journal as its first read did: a deferred transaction, which writes nothing.

    The connection is in autocommit, so without it each query reads its own snapshot: `views.tickets` reads the tickets'
    order in one and each ticket's summary in more, and a reply committed between them showed a ticket changed in a
    list still in the order from before it. Held only for the reads, never across an `await`, so it never holds back a
    checkpoint for longer than one read of the lists.
    """
    ctx.conn.execute("BEGIN")
    try:
        yield
    except BaseException:
        ctx.conn.execute("ROLLBACK")
        raise
    ctx.conn.execute("COMMIT")


def _costs(spend: Spend) -> tuple[float | None, float | None, float | None]:
    return spend.day.cost_usd, spend.month.cost_usd, spend.total_usd
