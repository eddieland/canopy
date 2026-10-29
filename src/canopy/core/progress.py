"""What a running tick's overseer or a run's agent has printed so far, kept as it prints it (DESIGN §6, §19, §22).

Each line goes to the log as it comes, so the web UI reads a running session's transcript from it, and what its events
report so far, its session and what it has spent, goes on the tick or the chore, task, or review run, whose change the
UI's stream carries, and a review's status card (`cards`) on the review.
A worker run's `_run` keeps its own, which also records the latest tool call and the status card on the run (§8).
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, TextIO

from canopy.core import cards, db
from canopy.runtime.watch import Watch

if TYPE_CHECKING:
    from collections.abc import Mapping

    from canopy.infra import logs
    from canopy.runtime.implementation import Version


class Progress:
    """Called with each line an agent prints: writes it to `out`, and records on its row what its events say so far.

    A line comes on the thread that runs the agent, so this may use the journal connection. A journal write that fails
    is logged, not raised: raising would kill the agent, and the session and spend are recorded again when it ends.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        table: db.ProgressTable,
        row_id: int,
        out: TextIO,
        log: logs.TickAdapter,
        *,
        agent: str,
        fields: Mapping[str, object],
        version: Version,
    ) -> None:
        """Watch the agent of the row `row_id` in `table`; the log's lines name it `agent`, with `fields`.

        Its lines are read as the runtime `version` runs prints them.
        """
        self.conn = conn
        self.table: db.ProgressTable = table
        self.row_id = row_id
        self.out = out
        self.log = log
        self.agent = agent
        self.fields = fields
        self.watch = Watch(version=version)

    def __call__(self, line: str) -> None:
        """Write `line` to the log, and record the session at its first event and the spend at each model call's end."""
        self.out.write(line)
        self.out.flush()
        change = self.watch.read(line)
        if change is None:
            return
        if self.table == "review_runs":
            # A reviewer keeps a status card, as a worker does (`cards`).
            try:
                cards.seen(self.conn, self.table, self.row_id, change)
            except sqlite3.Error as e:
                self.log.warning("agent card not recorded", extra={**self.fields, "agent": self.agent, "error": str(e)})
        if not change.started and change.usage is None:
            return
        try:
            db.set_progress(self.conn, self.table, self.row_id, change.session_id, usage=change.usage)
        except sqlite3.Error as e:
            self.log.warning("agent progress not recorded", extra={**self.fields, "agent": self.agent, "error": str(e)})
        if change.started:
            self.log.info(
                "agent session started",
                extra={**self.fields, "agent": self.agent, "session_id": change.session_id},
            )
