"""Plans exported into a directory of the operator's (DESIGN §25): every plan, as its file stands, under its row."""

import json
import os
import sqlite3
from pathlib import Path
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import conversation, feedback_plans, plan_export, plans, records
from canopy.core.context import DISPATCH_LOCK
from canopy.core.vocab import PlanStatus
from tests.canopy.helpers import KEY, PLAN, operator, plan_run, proposed
from tests.conftest import CanopyEnv


@pytest.fixture
def state_dir(canopy_env: CanopyEnv) -> Path:
    return canopy_env.state_dir


def front_matter(path: Path) -> tuple[dict[str, object], str]:
    """An exported file's front matter, each value read as JSON, and the text below it."""
    _, head, text = path.read_text().split("---\n", 2)
    keys = dict(line.split(": ", 1) for line in head.splitlines())
    return {k: json.loads(v) for k, v in keys.items()}, text.removeprefix("\n")


def feedback_plan(conn: sqlite3.Connection, state_dir: Path, text: str) -> int:
    """Write and record a feedback plan for `KEY`, covering no items. Returns its run's id."""
    run_id = plan_run(conn, state_dir)
    feedback_plans.record(conn, KEY, run_id, plans.write(state_dir, KEY, run_id, text), [])
    return run_id


def test_every_plan_is_exported_with_its_row(conn: sqlite3.Connection, state_dir: Path, tmp_path: Path) -> None:
    first = proposed(conn, state_dir)
    plans.approve(conn, state_dir, KEY, channel="cli", dispatch_lock=state_dir / DISPATCH_LOCK)
    second = proposed(conn, state_dir, "# Second\n")
    other = proposed(conn, state_dir, "# Other's\n", key="PROJ-2")
    feedback = feedback_plan(conn, state_dir, "# Feedback\n")
    dest = tmp_path / "archive"

    exported = plan_export.export(conn, state_dir, dest)

    assert exported == plan_export.Exported(
        written=[f"{KEY}/{first}.md", f"{KEY}/{second}.md", f"{KEY}/{feedback}.md", f"PROJ-2/{other}.md"],
        unchanged=0,
        skipped=[],
    )
    meta, text = front_matter(dest / KEY / f"{first}.md")
    [row, _] = plans.history(conn, KEY)
    assert text == PLAN
    assert meta == {
        "kind": "plan",
        "id": row.id,
        "ticket_key": KEY,
        "run_id": first,
        "created_at": row.created_at,
        "status": "superseded",
        "sha256": row.sha256,
        "size": row.size,
        "approved_sha256": row.sha256,
        "approved_at": row.approved_at,
        "approved_channel": "cli",
    }
    meta, text = front_matter(dest / KEY / f"{feedback}.md")
    assert (meta["kind"], meta["status"], text) == ("feedback plan", "proposed", "# Feedback\n")
    # Operator-only, as the plans it copies.
    assert dest.stat().st_mode & 0o777 == 0o700
    assert (dest / KEY).stat().st_mode & 0o777 == 0o700
    assert (dest / KEY / f"{first}.md").stat().st_mode & 0o777 == 0o600
    assert sorted(p.name for p in (dest / KEY).iterdir()) == sorted(f"{r}.md" for r in (first, second, feedback))


def test_an_export_rewrites_only_what_changed(conn: sqlite3.Connection, state_dir: Path, tmp_path: Path) -> None:
    first = proposed(conn, state_dir)
    second = proposed(conn, state_dir, key="PROJ-2")
    dest = tmp_path / "archive"
    plan_export.export(conn, state_dir, dest)

    assert plan_export.export(conn, state_dir, dest) == plan_export.Exported(written=[], unchanged=2, skipped=[])

    # The operator edits a plan, then approves it: its file and its row change, the other plan does neither.
    plans.path_for(state_dir, KEY, first).write_text("# Edited\n")
    assert plan_export.export(conn, state_dir, dest).written == [f"{KEY}/{first}.md"]
    plans.approve(conn, state_dir, KEY, channel="web", dispatch_lock=state_dir / DISPATCH_LOCK)
    exported = plan_export.export(conn, state_dir, dest)
    assert (exported.written, exported.unchanged) == ([f"{KEY}/{first}.md"], 1)
    meta, text = front_matter(dest / KEY / f"{first}.md")
    assert (meta["status"], meta["approved_channel"], text) == ("approved", "web", "# Edited\n")
    assert front_matter(dest / "PROJ-2" / f"{second}.md")[0]["status"] == "proposed"


def test_a_plan_whose_file_is_gone_is_skipped_and_nothing_exported_is_removed(
    conn: sqlite3.Connection,
    state_dir: Path,
    tmp_path: Path,
) -> None:
    run_id = proposed(conn, state_dir)
    dest = tmp_path / "archive"
    plan_export.export(conn, state_dir, dest)
    (dest / "README.md").write_text("The operator's own.\n")
    plans.path_for(state_dir, KEY, run_id).unlink()

    assert plan_export.export(conn, state_dir, dest) == plan_export.Exported(
        written=[],
        unchanged=0,
        skipped=[plan_export.Skipped("plan", KEY, run_id, "missing")],
    )
    assert front_matter(dest / KEY / f"{run_id}.md")[1] == PLAN
    assert (dest / "README.md").read_text() == "The operator's own.\n"


def test_a_link_in_the_export_is_never_followed(conn: sqlite3.Connection, state_dir: Path, tmp_path: Path) -> None:
    run_id = proposed(conn, state_dir)
    dest = tmp_path / "archive"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    target = elsewhere / "target.md"
    target.write_text("untouched\n")
    (dest / KEY).mkdir(parents=True)
    (dest / KEY / f"{run_id}.md").symlink_to(target)

    # A link at the file's name is replaced by the file.
    assert plan_export.export(conn, state_dir, dest).written == [f"{KEY}/{run_id}.md"]
    assert not (dest / KEY / f"{run_id}.md").is_symlink()
    assert target.read_text() == "untouched\n"

    # A link at the ticket's directory refuses the export.
    (dest / KEY / f"{run_id}.md").unlink()
    (dest / KEY).rmdir()
    (dest / KEY).symlink_to(elsewhere)
    with pytest.raises(plan_export.ExportError, match="is not a directory canopy can export into"):
        plan_export.export(conn, state_dir, dest)
    assert sorted(p.name for p in elsewhere.iterdir()) == ["target.md"]


def test_a_reason_the_planner_wrote_stays_one_value() -> None:
    plan = records.FeedbackPlan(
        id=1,
        ticket_key=KEY,
        run_id=2,
        created_at="2026-10-21T00:00:00Z",
        status=PlanStatus.APPROVED,
        sha256="ab",
        size=3,
        approved_sha256="ab",
        approved_at="2026-10-21T00:00:00Z",
        approved_channel=plans.PLANNER,
        spent_run_id=None,
        approved_reason="trivial\n---\nstatus: approved",
        effort=None,
    )
    head, _, _ = plan_export.document("feedback plan", plan, "# Plan\n").decode().partition("---\n\n")
    assert 'approved_reason: "trivial\\n---\\nstatus: approved"\n' in head
    assert head.count("---\n") == 1


def test_canopy_archive_exports_and_says_what_it_did(
    conn: sqlite3.Connection,
    state_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_id = proposed(conn, state_dir)
    gone = proposed(conn, state_dir, key="PROJ-2")
    plans.path_for(state_dir, "PROJ-2", gone).unlink()
    dest = tmp_path / "archive"

    assert operator("archive", str(dest)) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"wrote {KEY}/{run_id}.md",
        f"skipped PROJ-2's plan of run {gone}: its file is missing",
        f"Exported 1 plan to {dest}; 0 unchanged, 1 skipped.",
    ]
    assert front_matter(dest / KEY / f"{run_id}.md")[1] == PLAN


@pytest.mark.parametrize("env", [conversation.TICK_ID_ENV, conversation.RUN_ID_ENV])
def test_an_agent_cannot_export_plans(
    canopy_env: CanopyEnv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    env: str,
) -> None:
    with mock.patch.dict(os.environ, {env: "3"}):
        assert main(["archive", str(tmp_path / "archive")]) == 1
    assert "archive refused (inside_run)" in capsys.readouterr().err
    assert not (tmp_path / "archive").exists()
