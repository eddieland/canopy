"""Machine-readable status output."""

import json
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import db
from canopy.core.db import RunSlot
from tests.canopy.helpers import journal
from tests.conftest import CanopyEnv


def test_status_json_has_null_latest_tick_before_first_tick(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del treehouse_state, agent_log  # put the fakes on PATH, as for other CLI tests

    assert main(["status", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["latest_tick"] is None


def test_status_json_reports_attention_and_running_workers(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del treehouse_state, agent_log  # put the fakes on PATH, as for other CLI tests
    conn = journal(canopy_env)
    tick_id = db.start_tick(conn, dry_run=False)
    conn.execute("UPDATE ticks SET started_at = ? WHERE id = ?", ("2026-10-07T12:30:00.000Z", tick_id))
    db.touch_ticket(conn, "PROJ-1", str(canopy_env.repo))
    run_id = db.insert_run(
        conn,
        tick_id=tick_id,
        key="PROJ-1",
        kind="implement",
        branch="agent/PROJ-1-status-json",
        slots=[RunSlot("api", canopy_env.repo, "lease", "canopy:PROJ-1", "main")],
        runs_dir=canopy_env.state_dir / "runs",
    )
    run = db.get_run(conn, run_id)
    assert run is not None
    conn.execute("UPDATE runs SET started_at = ? WHERE id = ?", ("2026-10-07T12:34:56.000Z", run_id))
    review_id = db.insert_review_run(
        conn,
        tick_id=tick_id,
        pr_url="https://example.test/pr/2",
        sha="a" * 40,
        ticket=None,
        repo=None,
        logs_dir=canopy_env.state_dir / "reviews",
    )
    conn.execute("UPDATE review_runs SET started_at = ? WHERE id = ?", ("2026-10-07T12:35:56.000Z", review_id))
    db.record_decision(
        conn,
        tick_id,
        "PROJ-1",
        "attention:green_unreviewed",
        "PR needs review",
        repo="api",
    )
    db.finish_tick(conn, tick_id, "ok", "test")

    assert main(["status", "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "latest_tick": {
            "id": tick_id,
            "status": "ok",
            "dry_run": False,
            "started_at": "2026-10-07T12:30:00.000Z",
            "summary": "test",
        },
        "attention": [{"kind": "green_unreviewed", "ticket": "PROJ-1", "repo": "api", "message": "PR needs review"}],
        "workers": {
            "running": [
                {"ticket": "PROJ-1", "kind": "implement", "started_at": "2026-10-07T12:34:56.000Z"},
                {
                    "ticket": None,
                    "kind": "review",
                    "started_at": "2026-10-07T12:35:56.000Z",
                    "pr": "https://example.test/pr/2",
                },
            ],
            "max": 2,
        },
    }
