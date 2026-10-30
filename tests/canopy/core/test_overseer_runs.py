"""A tick's runs of the overseer (DESIGN §40): what the migration that made them recorded of the ticks before it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import db, records
from canopy.core.vocab import OverseerRunStatus
from canopy.infra import resources
from tests.canopy.helpers import journal_at, versions_after

if TYPE_CHECKING:
    from pathlib import Path

    from tests.conftest import Journals

#: The migration that made `overseer_runs`.
VERSION = 113
UNDONE = "dry run; overseer left duties undone: no decision for PROJ-1"


def test_each_past_tick_that_ran_its_overseer_gets_a_run_ending_as_its_tick_did(
    tmp_path: Path,
    journals: Journals,
) -> None:
    conn = journal_at(journals, tmp_path, VERSION - 1)
    ticks = [
        # id, status, overseer_ran, summary, session, cost
        (1, "ok", 1, "1 decisions: wait=1", "ses_1", 0.5),
        (2, "ok", 0, "no overseer, nothing left to judge; 0 decisions: none", None, None),
        (3, "overseer_failed", 1, UNDONE, "ses_3", 0.25),
        (4, "overseer_failed", 1, "overseer exited 1", None, None),
        (5, "disk_low", 0, "1 MiB free", None, None),
        (6, "abandoned", 1, "the tick process exited without finishing", "ses_6", None),
        (7, "error", 1, "RuntimeError: x", None, 0.75),
        # Before 0090 kept whether it ran: every tick that got that far did.
        (8, "ok", None, "0 decisions: none", None, None),
        (9, "skipped", None, "mcp_unavailable", None, None),
        (10, "reconcile_failed", None, "the pool is gone", None, None),
        (11, "abandoned", None, "the tick process exited without finishing", None, None),
        (12, "running", 1, None, "ses_12", None),
    ]
    conn.executemany(
        "INSERT INTO ticks (id, started_at, ended_at, status, overseer_ran, summary, session_id, cost_usd) "
        "VALUES (?, 'start', 'end', ?, ?, ?, ?, ?)",
        ticks,
    )
    assert db.migrate(conn, resources.migrations_dir()) == versions_after(VERSION - 1)
    runs = records.select(records.OverseerRun).order_by("id").all(conn)
    assert [(r.tick_id, r.subject, r.status, r.failure, r.session_id, r.cost_usd) for r in runs] == [
        (1, None, OverseerRunStatus.OK, None, "ses_1", 0.5),
        (3, None, OverseerRunStatus.UNDONE, UNDONE, "ses_3", 0.25),
        (4, None, OverseerRunStatus.FAILED, "overseer exited 1", None, None),
        (6, None, OverseerRunStatus.ABANDONED, None, "ses_6", None),
        (7, None, OverseerRunStatus.FAILED, "RuntimeError: x", None, 0.75),
        (8, None, OverseerRunStatus.OK, None, None, None),
        (9, None, OverseerRunStatus.OK, None, None, None),
        (12, None, OverseerRunStatus.ABANDONED, None, "ses_12", None),
    ]
    assert {(r.started_at, r.ended_at) for r in runs if r.tick_id != 12} == {("start", "end")}
