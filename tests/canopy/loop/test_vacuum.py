"""`canopy gc --vacuum` (DESIGN §26, The journal): it shrinks the journal between ticks, and refuses while a tick is
running, a run is live, or the disk has no room for a copy of the journal."""

import os
import shutil
from unittest import mock

from canopy.core import db
from canopy.infra import lock
from canopy.loop import vacuum
from tests.canopy.helpers import in_tick
from tests.canopy.scenario_helpers import Scenario
from tests.conftest import GitPool


def journal_size(scenario: Scenario) -> int:
    """The bytes of the scenario's journal and its WAL."""
    journal = scenario.env.state_dir / db.DB_FILE_NAME
    wal = journal.with_name(f"{journal.name}-wal")
    return journal.stat().st_size + (wal.stat().st_size if wal.exists() else 0)


def free_page_count(scenario: Scenario) -> int:
    """How many of the journal's pages are free."""
    return int(scenario.conn.execute("PRAGMA freelist_count").fetchone()[0])


def free_pages(scenario: Scenario) -> None:
    """Fill the journal with a tick's decisions of about 4 MiB, then delete them, leaving their pages free."""
    with in_tick(scenario.conn, ends_ok=True) as tick_id:
        for _ in range(64):
            db.record_decision(scenario.conn, tick_id, None, "skip", "x" * 65536)
    scenario.conn.execute("DELETE FROM decisions WHERE tick_id = ?", (tick_id,))
    assert free_page_count(scenario) > 0


def test_vacuum_is_refused_while_a_run_is_live_and_shrinks_the_journal_once_none_is(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    free_pages(scenario)
    working = scenario.starts()

    refused = scenario.operator("gc", "--vacuum", code=1)
    assert f"run {working.id} is live" in refused.err

    working.finishes()
    before = journal_size(scenario)
    printed = scenario.operator("gc", "--vacuum")

    assert journal_size(scenario) < before - 3 * 1024 * 1024
    assert free_page_count(scenario) == 0
    assert printed.out.startswith("The journal was ")


def test_vacuum_is_refused_while_a_tick_is_running(scenario: Scenario) -> None:
    held = lock.take(scenario.env.state_dir / lock.LOCK_FILE_NAME)
    try:
        refused = scenario.operator("gc", "--vacuum", code=1)
    finally:
        os.close(held)
    assert "a tick is running" in refused.err


def test_vacuum_is_refused_when_the_disk_has_no_room_for_a_copy_of_the_journal(scenario: Scenario) -> None:
    free_pages(scenario)
    usage = type(shutil.disk_usage(scenario.env.state_dir))
    with mock.patch.object(vacuum.shutil, "disk_usage", autospec=True, return_value=usage(1 << 40, 1 << 40, 4096)):
        refused = scenario.operator("gc", "--vacuum", code=1)
    assert "VACUUM writes a whole copy of it first" in refused.err
    assert free_page_count(scenario) > 0, "nothing was given back"
