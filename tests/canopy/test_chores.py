"""Chores (DESIGN §19, ROADMAP M9): recurring runs the operator defines, the overseer delegates, and guards bound."""

import json
import os
import signal
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from canopy.chores import result, view
from canopy.cli.main import main
from canopy.core import db
from canopy.core.config import load
from canopy.core.workspace import of_one
from canopy.infra import procs
from canopy.loop import attention
from tests.canopy.helpers import InlineRunner, in_tick, journal
from tests.conftest import CanopyEnv

FINDING = {
    "id": "flaky/checkout/test_retry",
    "title": "test_retry fails one run in five",
    "detail": "Seen on builds 81, 84, and 90.",
    "link": "https://ci.example.test/job/checkout/90",
}
OK = {"status": "ok", "summary": "one flaky test", "findings": [FINDING]}


def chore_toml(name: str = "build-health", *, every: int = 120, extra: str = "") -> str:
    return (
        f"\n[chores.{name}]\nprompt = {json.dumps(str(Path.home() / 'chores' / f'{name}.md'))}\n"
        f"cmd = 'agent run --agent canopy-chore {{prompt}}'\nevery_minutes = {every}\n{extra}"
    )


@pytest.fixture
def chores(canopy_env: CanopyEnv) -> Path:
    """One chore, build-health, whose command runs the fake agent as `canopy-chore`. Returns its prompt file."""
    prompt = canopy_env.home / "chores" / "build-health.md"
    prompt.parent.mkdir()
    prompt.write_text("# Build health\n\nLook at the build queue.\n")
    canopy_env.write_user(canopy_env.user_file.read_text() + chore_toml(extra='when = "Weekdays only."\n'))
    return prompt


def chore_reports(monkeypatch: pytest.MonkeyPatch, report: object) -> None:
    monkeypatch.setenv("FAKE_CHORE_RESULT", report if isinstance(report, str) else json.dumps(report))


def decisions(conn: sqlite3.Connection, tick_id: int) -> list[tuple[str | None, str, str]]:
    return [(d["chore"], str(d["action"]), str(d["rationale"])) for d in db.decisions_for_tick(conn, tick_id)]


def run_inline(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, report: object, *, close: bool = True) -> int:
    """Start build-health in its own tick, then do its `_chore` in this process, as the detached one would."""
    tick_id = in_tick(conn, monkeypatch)
    chore_reports(monkeypatch, report)
    assert main(["chore", "run", "build-health"], runner=InlineRunner()) == 0
    run_id = int(conn.execute("SELECT max(id) FROM chore_runs").fetchone()[0])
    assert main(["_chore", str(run_id)], runner=InlineRunner()) == 0
    if close:
        db.finish_tick(conn, tick_id, "ok", "test")
    monkeypatch.delenv("CANOPY_TICK_ID", raising=False)  # `_chore` drops it, in this process too
    return run_id


def backdate(conn: sqlite3.Connection, minutes: int) -> None:
    """Move every chore run's start back, so the next one is due."""
    for row in conn.execute("SELECT id, started_at FROM chore_runs").fetchall():
        earlier = db.parse_time(str(row["started_at"])).timestamp() - minutes * 60
        conn.execute("UPDATE chore_runs SET started_at = ? WHERE id = ?", (_stamp(earlier), row["id"]))


def _stamp(seconds: float) -> str:
    return db.format_time(datetime.fromtimestamp(seconds, UTC))


def state_block(agent_log: Path) -> dict[str, Any]:
    overseer = json.loads(agent_log.read_text().splitlines()[-1])
    state: dict[str, Any] = json.loads(overseer["argv"][3].split("```json\n", 1)[1].split("\n```", 1)[0])
    return state


def test_without_chores_nothing_about_them_reaches_the_overseer(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_AGENT_RESULT", "tick complete")
    assert main(["tick", "--dry-run"]) == 0
    assert "chores" not in state_block(agent_log)

    conn = journal(canopy_env)
    tick_id = in_tick(conn, monkeypatch)
    assert main(["chore", "run", "build-health"], runner=InlineRunner()) == 1
    assert decisions(conn, tick_id) == [
        ("build-health", "refused:unknown_chore", "no chore named 'build-health' is configured for this workspace")
    ]


def test_max_chores_zero_turns_every_chore_off(
    canopy_env: CanopyEnv, chores: Path, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text() + "\n[capacity]\nmax_chores = 0\n")
    monkeypatch.setenv("FAKE_AGENT_RESULT", "tick complete")
    assert main(["tick", "--dry-run"]) == 0
    assert "chores" not in state_block(agent_log)


def test_a_chore_run_records_its_findings(
    canopy_env: CanopyEnv, chores: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M9 against the fakes: a detached `_chore` runs the operator's command in its own directory and closes its row."""
    conn = journal(canopy_env)
    tick_id = in_tick(conn, monkeypatch)
    chore_reports(monkeypatch, OK)
    assert main(["chore", "run", "build-health", "--context", "Look at build 90"]) == 0
    deadline = time.monotonic() + 30
    row = db.get_chore_run(conn, 1)
    while row is not None and row["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
        row = db.get_chore_run(conn, 1)
    assert row is not None
    assert row["status"] == "ok", Path(row["log_path"]).read_text()
    assert result.stored(row["result_json"]) == result.ChoreResult.model_validate(OK)
    assert decisions(conn, tick_id) == [("build-health", "dispatch:chore", "chore run 1; context=Look at build 90")]

    [agent] = [json.loads(line) for line in agent_log.read_text().splitlines()]
    cwd = canopy_env.state_dir / "chores" / "build-health"
    assert agent["cwd"] == str(cwd)
    assert cwd.stat().st_mode & 0o777 == 0o700
    assert "CANOPY_TICK_ID" not in agent["env"]  # a chore cannot act as the overseer
    prompt = agent["argv"][3]
    assert prompt.startswith("# Build health\n\nLook at the build queue.\n\n## Run\n")
    run = json.loads(prompt.split("```json\n", 1)[1].split("\n```", 1)[0])
    assert (run["chore"], run["run_id"], run["context"]) == ("build-health", 1, "Look at build 90")
    assert run["previous_run"] is None
    assert run["open_findings"] == []
    assert run["result_contract"] == result.CONTRACT
    assert (canopy_env.state_dir / "chores" / "1.prompt").stat().st_mode & 0o777 == 0o600


def test_chore_guards(canopy_env: CanopyEnv, chores: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text() + chore_toml("queue-age", every=30))
    (canopy_env.home / "chores" / "queue-age.md").write_text("Queue age.\n")
    conn = journal(canopy_env)
    tick_id = in_tick(conn, monkeypatch)
    runner = InlineRunner()
    # The run is started but its `_chore` never runs, so it stays running.
    assert main(["chore", "run", "build-health"], runner=runner) == 0
    assert main(["chore", "run", "build-health"], runner=runner) == 1
    assert main(["chore", "run", "queue-age"], runner=runner) == 1
    assert db.finish_chore_run(conn, 1, "ok", json.dumps({"status": "ok"}))
    assert main(["chore", "run", "build-health"], runner=runner) == 1
    backdate(conn, 120)
    assert main(["chore", "run", "queue-age"], runner=runner) == 0
    assert main(["chore", "run", "nope"], runner=runner) == 1

    found = decisions(conn, tick_id)
    assert [(c, a) for c, a, _ in found] == [
        ("build-health", "dispatch:chore"),
        ("build-health", "refused:running"),
        ("queue-age", "refused:chore_capacity"),
        ("build-health", "refused:not_due"),
        ("queue-age", "dispatch:chore"),
        ("nope", "refused:unknown_chore"),
    ]
    assert found[1][2] == "chore run 1 of build-health is running"
    assert found[2][2] == "1 of 1 chore runs are running"
    assert found[3][2].startswith("build-health runs at most every 120 minutes; next after ")
    # Chore runs are not workers: they take no worker capacity.
    assert db.running_runs(conn) == []


def test_a_dry_run_checks_the_guards_and_starts_nothing(
    canopy_env: CanopyEnv, chores: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = journal(canopy_env)
    tick_id = in_tick(conn, monkeypatch, dry_run=True)
    runner = InlineRunner()
    assert main(["chore", "run", "build-health"], runner=runner) == 0
    assert main(["chore", "run", "build-health"], runner=runner) == 1
    assert decisions(conn, tick_id) == [
        ("build-health", "dispatch:chore", "dry run: not dispatched"),
        ("build-health", "refused:running", "this dry run already ran build-health"),
    ]
    assert runner.spawned == []
    assert conn.execute("SELECT count(*) FROM chore_runs").fetchone()[0] == 0


def test_wait_names_a_configured_chore(
    canopy_env: CanopyEnv, chores: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = journal(canopy_env)
    tick_id = in_tick(conn, monkeypatch)
    assert main(["chore", "wait", "build-health", "--rationale", "outside working hours"]) == 0
    assert main(["chore", "wait", "nope", "--rationale", "x"]) == 1
    assert "no chore named 'nope'" in capsys.readouterr().err
    assert decisions(conn, tick_id) == [("build-health", "wait", "outside working hours")]
    assert main(["decisions", str(tick_id)]) == 0
    assert "chore:build-health  wait  outside working hours" in capsys.readouterr().out


@pytest.mark.parametrize(
    "report",
    [
        "not json",
        {"status": "done"},
        {"status": "ok", "findings": [FINDING, FINDING]},
        {"status": "ok", "findings": [{**FINDING, "id": "has space"}]},
        {"status": "ok", "findings": [{**FINDING, "link": "http://plain.test"}]},
        {"status": "ok", "findings": [{**FINDING, "id": f"f{i}"} for i in range(21)]},
    ],
)
def test_an_invalid_result_is_unknown_and_records_no_findings(
    canopy_env: CanopyEnv, chores: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch, report: object
) -> None:
    conn = journal(canopy_env)
    run_id = run_inline(conn, monkeypatch, report)
    row = db.get_chore_run(conn, run_id)
    assert row is not None
    assert row["status"] == "unknown"
    assert result.stored(row["result_json"]) is None


def test_long_text_is_cut_to_its_limits() -> None:
    long = {**FINDING, "title": "t" * 300 + "\nsecond line", "detail": "d" * 3000}
    parsed = result.parse(json.dumps({"status": "ok", "summary": "s" * 3000, "findings": [long]}))
    assert parsed is not None
    assert len(parsed.summary) == 2000
    assert len(parsed.findings[0].title) == 200
    assert "\n" not in parsed.findings[0].title
    assert len(parsed.findings[0].detail) == 2000


def tick(monkeypatch: pytest.MonkeyPatch, *, dry_run: bool = False) -> None:
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")
    assert main(["tick", *(["--dry-run"] if dry_run else [])]) == 0


@pytest.fixture
def notified(canopy_env: CanopyEnv, chores: Path, tmp_path: Path) -> Path:
    out = tmp_path / "notified.txt"
    script = tmp_path / "notify"
    script.write_text('#!/bin/sh\ncat >> "$1"\necho "--" >> "$1"\n')
    script.chmod(0o755)
    canopy_env.write_user(canopy_env.user_file.read_text() + f"\n[notify]\ncmd = '{script} {out}'\n")
    return out


def test_findings_reach_the_attention_list_and_are_notified_once(
    canopy_env: CanopyEnv,
    chores: Path,
    treehouse_state: Path,
    agent_log: Path,
    notified: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M9's acceptance against the fakes: findings are listed and notified once, and leave when no longer reported."""
    conn = journal(canopy_env)
    run_inline(conn, monkeypatch, OK)
    tick(monkeypatch)
    page = (canopy_env.state_dir / "attention.md").read_text()
    assert (
        "## chore:build-health\n\n- test_retry fails one run in five https://ci.example.test/job/checkout/90, " in page
    )
    assert page.endswith("(flaky/checkout/test_retry)\n")
    [message] = notified.read_text().split("--\n")[:-1]
    assert (
        "+ chore:build-health flaky/checkout/test_retry: test_retry fails one run in five "
        "https://ci.example.test/job/checkout/90\n"
    ) in message

    # The overseer sees the findings of the latest ok run.
    chore = state_block(agent_log)["chores"][0]
    assert chore["findings"] == [{"id": FINDING["id"], "title": FINDING["title"], "link": FINDING["link"]}]
    assert chore["when"] == "Weekdays only."
    assert chore["running"] is False
    assert chore["due"] is False

    # A failed run leaves the findings standing and raises chore_failed; still nothing new about the finding.
    backdate(conn, 120)
    run_inline(conn, monkeypatch, {"status": "failed", "summary": "CI unreachable"})
    tick(monkeypatch)
    items = {(i.subject, i.reason) for i in attention.current(conn)}
    assert ("chore:build-health", "chore_failed") in items
    second = notified.read_text().split("--\n")[1]
    assert "+ chore:build-health chore_failed: chore run 2 ended failed: CI unreachable; log " in second
    assert "flaky/checkout/test_retry" not in second

    # An ok run that no longer reports it: the finding and chore_failed both resolve.
    backdate(conn, 120)
    run_inline(conn, monkeypatch, {"status": "ok", "summary": "all clear"})
    tick(monkeypatch)
    third = notified.read_text().split("--\n")[2]
    assert "- chore:build-health flaky/checkout/test_retry\n" in third
    assert "- chore:build-health chore_failed\n" in third
    assert "Nothing needs you." in (canopy_env.state_dir / "attention.md").read_text()


def test_a_finding_is_aged_from_the_first_ok_run_that_reported_it(
    canopy_env: CanopyEnv, chores: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = journal(canopy_env)
    run_inline(conn, monkeypatch, OK)
    backdate(conn, 600)
    run_inline(conn, monkeypatch, {"status": "failed"})
    backdate(conn, 120)
    run_inline(conn, monkeypatch, {"status": "ok", "findings": [FINDING, {**FINDING, "id": "stuck/pr-7"}]})
    first = db.get_chore_run(conn, 1)
    third = db.get_chore_run(conn, 3)
    assert first is not None
    assert third is not None
    cfg = load(canopy_env.repo, canopy_env.user_file)
    found = {f.finding.id: f.since for f in view.open_findings(conn, cfg, of_one(canopy_env.repo))}
    assert found == {FINDING["id"]: first["started_at"], "stuck/pr-7": third["started_at"]}
    # A finding open longer than one page of history reads back further.
    monkeypatch.setattr(view, "_HISTORY_RUNS", 1)
    found = {f.finding.id: f.since for f in view.open_findings(conn, cfg, of_one(canopy_env.repo))}
    assert found == {FINDING["id"]: first["started_at"], "stuck/pr-7": third["started_at"]}


def test_a_shadowing_config_above_the_cwd_stops_the_chore(
    canopy_env: CanopyEnv, chores: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = canopy_env.home / "project"
    (project / "sub").mkdir(parents=True)
    (project / ".opencode" / "agent").mkdir(parents=True)
    (project / ".opencode" / "agent" / "canopy-chore.md").write_text("---\npermission:\n  bash: allow\n---\n")
    cwd = f"cwd = {json.dumps(str(project / 'sub'))}\n"
    canopy_env.write_user(canopy_env.user_file.read_text() + cwd)
    conn = journal(canopy_env)
    run_id = run_inline(conn, monkeypatch, OK)
    run = db.get_chore_run(conn, run_id)
    assert run is not None
    assert run["status"] == "crashed"
    assert "canopy-chore.md" in json.loads(run["result_json"])["harness"]
    assert not agent_log.exists() or "canopy-chore" not in agent_log.read_text()


def test_deleting_a_chore_clears_its_items(
    canopy_env: CanopyEnv, chores: Path, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = journal(canopy_env)
    run_inline(conn, monkeypatch, {"status": "failed", "findings": []})
    tick(monkeypatch)
    assert "## chore_failed" in (canopy_env.state_dir / "attention.md").read_text()
    canopy_env.write_user(canopy_env.user_file.read_text().split("\n[chores.build-health]")[0])
    tick(monkeypatch)
    assert "Nothing needs you." in (canopy_env.state_dir / "attention.md").read_text()
    assert "chores" not in state_block(agent_log)
    assert conn.execute("SELECT count(*) FROM chore_runs").fetchone()[0] == 1  # kept as history


def test_a_chore_for_another_workspace_is_not_configured_here(
    canopy_env: CanopyEnv, chores: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = canopy_env.user_file.read_text().replace('when = "Weekdays only."', 'workspaces = ["elsewhere"]')
    canopy_env.write_user(text)
    conn = journal(canopy_env)
    tick_id = in_tick(conn, monkeypatch)
    assert main(["chore", "run", "build-health"], runner=InlineRunner()) == 1
    assert decisions(conn, tick_id)[0][1] == "refused:unknown_chore"
    canopy_env.write_user(text.replace('["elsewhere"]', '["repo"]'))  # the workspace of one is named for its directory
    assert main(["chore", "run", "build-health"], runner=InlineRunner()) == 0


def test_a_chore_that_times_out(canopy_env: CanopyEnv, chores: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    canopy_env.write_user(
        canopy_env.user_file.read_text().replace("every_minutes = 120", "every_minutes = 120\ntimeout_minutes = 1")
    )
    conn = journal(canopy_env)
    in_tick(conn, monkeypatch)
    assert main(["chore", "run", "build-health"], runner=InlineRunner()) == 0
    assert main(["_chore", "1"], runner=InlineRunner(timeout_agent=True)) == 0
    row = db.get_chore_run(conn, 1)
    assert row is not None
    assert row["status"] == "timeout"
    assert json.loads(row["result_json"]) == {"harness": "the chore timed out after 1 minutes"}


def test_a_killed_chore_run_is_crashed_on_the_next_tick(
    canopy_env: CanopyEnv, chores: Path, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = journal(canopy_env)
    tick_id = in_tick(conn, monkeypatch)
    monkeypatch.setenv("FAKE_CHORE_SLEEP", "60")
    assert main(["chore", "run", "build-health"]) == 0
    db.finish_tick(conn, tick_id, "ok", "test")
    monkeypatch.delenv("CANOPY_TICK_ID")
    deadline = time.monotonic() + 30
    row = db.get_chore_run(conn, 1)
    while (row is None or row["agent_pid"] is None) and time.monotonic() < deadline:
        time.sleep(0.05)
        row = db.get_chore_run(conn, 1)
    assert row is not None
    assert row["agent_pid"] is not None, "`_chore` never started the agent"
    pid, agent_pid = int(row["pid"]), int(row["agent_pid"])
    os.kill(pid, signal.SIGKILL)
    while procs.alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)

    tick(monkeypatch)
    crashed = db.get_chore_run(conn, 1)
    assert crashed is not None
    assert crashed["status"] == "crashed"
    while procs.alive(agent_pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not procs.alive(agent_pid)
    [item] = attention.current(conn)
    assert (item.subject, item.reason) == ("chore:build-health", "chore_failed")
    assert item.detail.startswith("chore run 1 ended crashed: the chore process is gone; log ")


def test_status_lists_each_chore(
    canopy_env: CanopyEnv,
    chores: Path,
    agent_log: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = journal(canopy_env)
    run_inline(conn, monkeypatch, OK)
    capsys.readouterr()
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "\nChores (0/1 running):\n  build-health  last ok 0s ago, due in 1h\n" in out
