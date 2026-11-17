"""Every session the runtime keeps, recorded while `canopy loop` waits between ticks (DESIGN §13).

The wait reads the runtime's record of its sessions, canopy's and not, a page at a time from where the last read
stopped (`canopy.core.runtime_sessions`): every `EVERY_SECONDS` once it has caught up, and `GAP_SECONDS` apart while a
full page says more of the history waits, each session's title with it while `sessions.search` keeps titles. None is
read while the loop is paused, nor in a dry run. It runs in the loop's own process, so nothing reads them outside
`canopy loop` (D042), and it never ends the loop: what it raises is logged, and the next read is `EVERY_SECONDS` later.

While `sessions.search` is `text`, the same wait keeps the index of what every session said in step
(`canopy.core.session_index`), a step at a time, each bounded in time (`Indexer`): `INDEX_GAP_SECONDS` apart while the
first build or a catch-up goes on, else `INDEX_EVERY_SECONDS`. Below `text` it removes the index.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from canopy.core import pause, runtime_sessions, session_index
from canopy.core.vocab import SessionsRead
from canopy.runtime.report import MAX_SESSIONS

if TYPE_CHECKING:
    from collections.abc import Callable

    from canopy.core.context import Context
    from canopy.infra import logs

#: How long after one read the next starts once the reading has caught up: sessions outside canopy run on their own.
EVERY_SECONDS: Final = 300.0
#: How long after a full page the next starts, while the history is read.
GAP_SECONDS: Final = 10.0
#: How long after one step of the index the next starts once it has caught up, and while it has not: a session that
#: ended is found after the loop's next wait, and the first build goes on in the waits without filling them.
INDEX_EVERY_SECONDS: Final = 60.0
INDEX_GAP_SECONDS: Final = 2.0


@dataclass
class Recorder:
    """The runtime's sessions a wait reads: a page a step, `GAP_SECONDS` apart while behind, else `EVERY_SECONDS`."""

    clock: Callable[[], float]
    log: logs.TickAdapter
    #: When the last read ended, on `clock`; None before the first.
    last: float | None = None
    #: Whether the last read returned a full page, so more may wait to be read.
    behind: bool = False

    def step(self, ctx: Context) -> SessionsRead | None:
        """Read the next page of the runtime's sessions, unless the last read was too recent, or the loop is paused.

        Returns:
            How the read ended; None when none was made.
        """
        wait = GAP_SECONDS if self.behind else EVERY_SECONDS
        if self.last is not None and self.clock() - self.last < wait:
            return None
        if pause.paused(ctx.conn) is not None:
            return None
        status = SessionsRead.FAILED
        self.behind = False
        try:
            listed = ctx.config.sessions
            page = runtime_sessions.read_next(
                ctx.conn,
                version=ctx.config.runtime.version,
                exclude=listed.exclude if listed.search != "off" else None,
            )
            status = SessionsRead(page.outcome)
            self.behind = status is SessionsRead.FOUND and len(page.sessions) + page.skipped >= MAX_SESSIONS
            if status is SessionsRead.FAILED:
                self.log.warning("could not read the runtime's sessions", extra={"error": page.error})
        except Exception as e:
            self.log.exception("reading the runtime's sessions raised", extra={"error": str(e)})
        self.last = self.clock()
        return status


@dataclass
class Indexer:
    """The index of what sessions said, kept in step a step at a time: `INDEX_GAP_SECONDS` apart while behind."""

    clock: Callable[[], float]
    log: logs.TickAdapter
    #: When the last step ended, on `clock`; None before the first.
    last: float | None = None
    #: Whether the last step left more to read.
    behind: bool = False

    def step(self, ctx: Context) -> session_index.Stepped | None:
        """Keep the index in step, or remove it below `text`, unless the last step was too recent or the loop paused.

        Returns:
            What the step did; None when none was made, or the setting is below `text`, or the step raised.
        """
        wait = INDEX_GAP_SECONDS if self.behind else INDEX_EVERY_SECONDS
        if self.last is not None and self.clock() - self.last < wait:
            return None
        if pause.paused(ctx.conn) is not None:
            return None
        stepped = None
        self.behind = False
        try:
            setting = ctx.config.sessions
            version = ctx.config.runtime.version
            if session_index.effective(setting.search, version=version) != "text":
                if session_index.remove(ctx.state_dir):
                    self.log.info("removed the index of sessions' text, as sessions.search keeps none")
            else:
                stepped = session_index.step(ctx.conn, ctx.state_dir, version=version, exclude=setting.exclude)
                self.behind = stepped.behind
                if stepped.error is not None:
                    self.log.warning("could not read the runtime's sessions to index", extra={"error": stepped.error})
        except Exception as e:
            self.log.exception("indexing the runtime's sessions raised", extra={"error": str(e)})
        self.last = self.clock()
        return stepped
