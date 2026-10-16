"""Chores (DESIGN §19, ROADMAP M9): recurring runs the operator defines, the overseer delegates, and guards bound."""

import json
import os
import signal
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO
from unittest import mock

import pytest

from canopy.chores import execute, start
from canopy.cli.main import main
from canopy.core import chore_result as result
from canopy.core import chore_view as view
from canopy.core import db, workspace
from canopy.core.config import load
from canopy.core.context import Context
from canopy.core.vocab import ChoreRunStatus
from canopy.infra import lock, procs
from canopy.loop import attention
from tests.canopy.helpers import InlineRunner, in_tick, journal, lifelock_left
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


@contextmanager
def chore_reports(report: object) -> Iterator[None]:
    """Until the block ends, the fake chore prints `report` as its final line, verbatim if it is a string."""
    with mock.patch.dict(os.environ, {"FAKE_CHORE_RESULT": report if isinstance(report, str) else json.dumps(report)}):
        yield


def decisions(conn: sqlite3.Connection, tick_id: int) -> list[tuple[str | None, str, str]]:
    return [(d.chore, d.action, d.rationale) for d in db.decisions_for_tick(conn, tick_id)]


def run_inline(conn: sqlite3.Connection, report: object, *, close: bool = True) -> int:
    """Start build-health in its own tick, then do its `_chore` in this process, as the detached one would."""
    with in_tick(conn) as tick_id, chore_reports(report):
        assert main(["chore", "run", "build-health"], runner=InlineRunner()) == 0
        run_id = int(conn.execute("SELECT max(id) FROM chore_runs").fetchone()[0])
        assert main(["_chore", str(run_id)], runner=InlineRunner()) == 0
        if close:
            db.finish_tick(conn, tick_id, "ok", "test")
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
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    with mock.patch.dict(os.environ, {"FAKE_AGENT_RESULT": "CANOPY_TICK_DONE"}):
        assert main(["tick", "--dry-run"]) == 0
    assert "chores" not in state_block(agent_log)

    conn = journal(canopy_env)
    with in_tick(conn) as tick_id:
        assert main(["chore", "run", "build-health"], runner=InlineRunner()) == 1
        assert decisions(conn, tick_id) == [
            ("build-health", "refused:unknown_chore", "no chore named 'build-health' is configured for this workspace")
        ]


def test_max_chores_zero_turns_every_chore_off(
    canopy_env: CanopyEnv, chores: Path, treehouse_state: Path, agent_log: Path
) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text() + "\n[capacity]\nmax_chores = 0\n")
    with mock.patch.dict(os.environ, {"FAKE_AGENT_RESULT": "CANOPY_TICK_DONE"}):
        assert main(["tick", "--dry-run"]) == 0
        assert "chores" not in state_block(agent_log)


def test_a_chore_run_records_its_findings(canopy_env: CanopyEnv, chores: Path, agent_log: Path) -> None:
    """M9 against the fakes: a detached `_chore` runs the operator's command in its own directory and closes its row."""
    conn = journal(canopy_env)
    with in_tick(conn) as tick_id, chore_reports(OK):
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
        # Run files are kept by chore, out of its working directory.
        runs = canopy_env.state_dir / "chore-runs" / "build-health"
        assert runs.stat().st_mode & 0o777 == 0o700
        assert row["log_path"] == str(runs / "1.log")
        assert (runs / "1.prompt").stat().st_mode & 0o777 == 0o600
        assert not (cwd / "1.log").exists()
        # Its lifelock goes with it: a run leaves its log and prompt behind, and nothing else.
        assert not lifelock_left(row)
        assert sorted(p.name for p in runs.iterdir()) == ["1.log", "1.prompt"]


def test_the_run_object_carries_the_notice_in_force(canopy_env: CanopyEnv, chores: Path, agent_log: Path) -> None:
    # In the harness's own section, which the operator's file cannot drop (DESIGN §8, §19).
    conn = journal(canopy_env)
    runs = canopy_env.state_dir / "chore-runs" / "build-health"
    run_inline(conn, OK)
    assert run_section((runs / "1.prompt").read_text())["notice"] is None
    assert main(["notice", "CI is down."]) == 0
    backdate(conn, 180)
    run_inline(conn, OK)
    assert run_section((runs / "2.prompt").read_text())["notice"] == "CI is down."


def test_chore_guards(canopy_env: CanopyEnv, chores: Path) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text() + chore_toml("queue-age", every=30))
    (canopy_env.home / "chores" / "queue-age.md").write_text("Queue age.\n")
    conn = journal(canopy_env)
    with in_tick(conn) as tick_id:
        runner = InlineRunner()
        # The run is started but its `_chore` never runs, so it stays running.
        assert main(["chore", "run", "build-health"], runner=runner) == 0
        assert main(["chore", "run", "build-health"], runner=runner) == 1
        assert main(["chore", "run", "queue-age"], runner=runner) == 1
        assert db.finish_run(conn, "chore_runs", 1, ChoreRunStatus.OK, json.dumps({"status": "ok"}))
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
        assert db.running_runs(conn, "runs") == []


def test_a_dry_run_checks_the_guards_and_starts_nothing(canopy_env: CanopyEnv, chores: Path) -> None:
    conn = journal(canopy_env)
    with in_tick(conn, dry_run=True) as tick_id:
        runner = InlineRunner()
        assert main(["chore", "run", "build-health"], runner=runner) == 0
        assert main(["chore", "run", "build-health"], runner=runner) == 1
        assert decisions(conn, tick_id) == [
            ("build-health", "dispatch:chore", "dry run: not dispatched"),
            ("build-health", "refused:running", "this dry run already ran build-health"),
        ]
        assert runner.spawned == []
        assert conn.execute("SELECT count(*) FROM chore_runs").fetchone()[0] == 0


def test_wait_names_a_configured_chore(canopy_env: CanopyEnv, chores: Path, capsys: pytest.CaptureFixture[str]) -> None:
    conn = journal(canopy_env)
    with in_tick(conn) as tick_id:
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
    canopy_env: CanopyEnv, chores: Path, agent_log: Path, report: object
) -> None:
    conn = journal(canopy_env)
    run_id = run_inline(conn, report)
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


def tick(*, dry_run: bool = False) -> None:
    with mock.patch.dict(os.environ, {"FAKE_OVERSEER_RESULT": "CANOPY_TICK_DONE"}):
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
) -> None:
    """M9's acceptance against the fakes: findings are listed and notified once, and leave when no longer reported."""
    conn = journal(canopy_env)
    run_inline(conn, OK)
    tick()
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
    run_inline(conn, {"status": "failed", "summary": "CI unreachable"})
    tick()
    items = {(i.subject, i.reason) for i in attention.current(conn)}
    assert ("chore:build-health", "chore_failed") in items
    second = notified.read_text().split("--\n")[1]
    assert "+ chore:build-health chore_failed: chore run 2 ended failed: CI unreachable; log " in second
    assert "flaky/checkout/test_retry" not in second

    # An ok run that no longer reports it: the finding and chore_failed both resolve.
    backdate(conn, 120)
    run_inline(conn, {"status": "ok", "summary": "all clear"})
    tick()
    third = notified.read_text().split("--\n")[2]
    assert "- chore:build-health flaky/checkout/test_retry\n" in third
    assert "- chore:build-health chore_failed\n" in third
    assert "Nothing needs you." in (canopy_env.state_dir / "attention.md").read_text()


def test_a_finding_is_aged_from_the_first_ok_run_that_reported_it(
    canopy_env: CanopyEnv, chores: Path, agent_log: Path
) -> None:
    conn = journal(canopy_env)
    run_inline(conn, OK)
    backdate(conn, 600)
    run_inline(conn, {"status": "failed"})
    backdate(conn, 120)
    run_inline(conn, {"status": "ok", "findings": [FINDING, {**FINDING, "id": "stuck/pr-7"}]})
    first = db.get_chore_run(conn, 1)
    third = db.get_chore_run(conn, 3)
    assert first is not None
    assert third is not None
    cfg = load(canopy_env.root, canopy_env.user_file)
    found = {f.finding.id: f.since for f in view.open_findings(conn, cfg, workspace.load(canopy_env.root))}
    assert found == {FINDING["id"]: first["started_at"], "stuck/pr-7": third["started_at"]}
    # A finding open longer than one page of history reads back further.
    with mock.patch.object(view, "_HISTORY_RUNS", 1):
        found = {f.finding.id: f.since for f in view.open_findings(conn, cfg, workspace.load(canopy_env.root))}
        assert found == {FINDING["id"]: first["started_at"], "stuck/pr-7": third["started_at"]}


def test_a_shadowing_config_above_the_cwd_stops_the_chore(canopy_env: CanopyEnv, chores: Path, agent_log: Path) -> None:
    project = canopy_env.home / "project"
    (project / "sub").mkdir(parents=True)
    (project / ".opencode" / "agent").mkdir(parents=True)
    (project / ".opencode" / "agent" / "canopy-chore.md").write_text("---\npermission:\n  bash: allow\n---\n")
    cwd = f"cwd = {json.dumps(str(project / 'sub'))}\n"
    canopy_env.write_user(canopy_env.user_file.read_text() + cwd)
    conn = journal(canopy_env)
    run_id = run_inline(conn, OK)
    run = db.get_chore_run(conn, run_id)
    assert run is not None
    assert run["status"] == "crashed"
    assert "canopy-chore.md" in json.loads(run["result_json"])["harness"]
    assert not agent_log.exists() or "canopy-chore" not in agent_log.read_text()


def test_deleting_a_chore_clears_its_items(
    canopy_env: CanopyEnv, chores: Path, treehouse_state: Path, agent_log: Path
) -> None:
    conn = journal(canopy_env)
    run_inline(conn, {"status": "failed", "findings": []})
    tick()
    assert "## chore_failed" in (canopy_env.state_dir / "attention.md").read_text()
    canopy_env.write_user(canopy_env.user_file.read_text().split("\n[chores.build-health]")[0])
    tick()
    assert "Nothing needs you." in (canopy_env.state_dir / "attention.md").read_text()
    assert "chores" not in state_block(agent_log)
    assert conn.execute("SELECT count(*) FROM chore_runs").fetchone()[0] == 1  # kept as history


def test_a_chore_for_another_workspace_is_not_configured_here(canopy_env: CanopyEnv, chores: Path) -> None:
    text = canopy_env.user_file.read_text().replace('when = "Weekdays only."', 'workspaces = ["elsewhere"]')
    canopy_env.write_user(text)
    conn = journal(canopy_env)
    with in_tick(conn) as tick_id:
        assert main(["chore", "run", "build-health"], runner=InlineRunner()) == 1
        assert decisions(conn, tick_id)[0][1] == "refused:unknown_chore"
        canopy_env.write_user(text.replace('["elsewhere"]', '["acme"]'))  # the name in this workspace's map
        assert main(["chore", "run", "build-health"], runner=InlineRunner()) == 0


def test_a_chore_that_times_out(canopy_env: CanopyEnv, chores: Path) -> None:
    canopy_env.write_user(
        canopy_env.user_file.read_text().replace("every_minutes = 120", "every_minutes = 120\ntimeout_minutes = 1")
    )
    conn = journal(canopy_env)
    with in_tick(conn):
        assert main(["chore", "run", "build-health"], runner=InlineRunner()) == 0
        assert main(["_chore", "1"], runner=InlineRunner(timeout_agent=True)) == 0
        row = db.get_chore_run(conn, 1)
        assert row is not None
        assert row["status"] == "timeout"
        assert json.loads(row["result_json"]) == {"harness": "the chore timed out after 1 minutes"}


def test_a_killed_chore_run_is_crashed_on_the_next_tick(
    canopy_env: CanopyEnv, chores: Path, treehouse_state: Path, agent_log: Path
) -> None:
    conn = journal(canopy_env)
    with in_tick(conn) as tick_id, mock.patch.dict(os.environ, {"FAKE_CHORE_SLEEP": "60"}):
        assert main(["chore", "run", "build-health"]) == 0
        db.finish_tick(conn, tick_id, "ok", "test")
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

    tick()
    crashed = db.get_chore_run(conn, 1)
    assert crashed is not None
    assert crashed["status"] == "crashed"
    assert not procs.lifelock(Path(crashed["log_path"])).exists()
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
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = journal(canopy_env)
    run_inline(conn, OK)
    capsys.readouterr()
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "\nChores (0/1 running):\n  build-health  last ok 0s ago, due in 1h\n" in out


def run_section(prompt: str) -> dict[str, Any]:
    section: dict[str, Any] = json.loads(prompt.split("```json\n", 1)[1].split("\n```", 1)[0])
    return section


def open_ids(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> list[str]:
    cfg = load(canopy_env.root, canopy_env.user_file)
    return [f.finding.id for f in view.open_findings(conn, cfg, workspace.load(canopy_env.root))]


def test_try_runs_a_chore_in_the_foreground_and_records_it(
    canopy_env: CanopyEnv,
    chores: Path,
    agent_log: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = journal(canopy_env)
    run_inline(conn, OK)
    backdate(conn, 600)
    assert open_ids(canopy_env, conn) == [FINDING["id"]]
    # Due, but with no tick and no chore capacity left to take: a try is the operator's, outside every guard but
    # `running`.
    held: list[bool] = []

    def holding(ctx: Context, run_id: int, *, out: TextIO) -> execute.Outcome:
        run = db.get_chore_run(ctx.conn, run_id)
        assert run is not None
        held.append(lock.held(procs.lifelock(Path(run["log_path"]))))
        return run_chore(ctx, run_id, out=out)

    run_chore = execute.execute
    with (
        chore_reports({"status": "ok", "summary": "all green", "findings": []}),
        mock.patch.object(execute, "execute", autospec=True, side_effect=holding),
    ):
        assert main(["chore", "try", "build-health", "--context", "Look at build 91"]) == 0
    out = capsys.readouterr()
    assert "trying chore build-health in " in out.err
    assert "recorded as chore run 2" in out.err
    assert '"summary": "all green"' in out.out
    assert out.out.rstrip().endswith("chore try build-health: ok; run 2, see `canopy show chore:build-health`")

    # A run like the overseer's, with no tick and no decision: its result is the chore's latest.
    row = db.get_chore_run(conn, 2)
    assert row is not None
    assert (row["tick_id"], row["status"], row["pid"]) == (None, "ok", os.getpid())
    assert "--- chore stdout ---" in Path(row["log_path"]).read_text()
    assert [d["action"] for d in conn.execute("SELECT action FROM decisions")] == ["dispatch:chore"]
    assert open_ids(canopy_env, conn) == []
    [state] = view.states(conn, load(canopy_env.root, canopy_env.user_file), workspace.load(canopy_env.root))
    earliest = state.earliest()
    assert earliest is not None
    assert earliest > datetime.now(UTC)  # the next run is due counting from the try

    tried = json.loads(agent_log.read_text().splitlines()[-1])
    assert tried["cwd"] == str(canopy_env.state_dir / "chores" / "build-health")
    assert tried["env"]["CANOPY_RUN_ID"] == "chore-2"
    run = run_section(tried["argv"][3])
    assert (run["run_id"], run["context"]) == (2, "Look at build 91")
    assert run_section(start.prompt_file(Path(row["log_path"])).read_text()) == run
    # The try held its run's lifelock, as a detached `_chore` does, and removed it once the row was closed.
    assert held == [True]
    assert not procs.lifelock(Path(row["log_path"])).exists()
    # It sees what a run starting now would: the latest run and its open findings.
    assert run["previous_run"]["run_id"] == 1
    assert [f["id"] for f in run["open_findings"]] == [FINDING["id"]]


def test_try_with_no_record_records_nothing(
    canopy_env: CanopyEnv,
    chores: Path,
    agent_log: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = journal(canopy_env)
    run_inline(conn, OK)
    with chore_reports({"status": "ok", "summary": "all green", "findings": []}):
        assert main(["chore", "try", "build-health", "--no-record"]) == 0
    out = capsys.readouterr()
    assert "nothing is recorded" in out.err
    assert out.out.rstrip().endswith("chore try build-health: ok; nothing recorded")

    assert conn.execute("SELECT count(*) FROM chore_runs").fetchone()[0] == 1
    assert open_ids(canopy_env, conn) == [FINDING["id"]]
    tried = json.loads(agent_log.read_text().splitlines()[-1])
    assert tried["env"]["CANOPY_RUN_ID"] == "chore-try"
    assert run_section(tried["argv"][3])["run_id"] is None


def test_try_works_with_chores_off_and_reports_a_bad_result(
    canopy_env: CanopyEnv,
    chores: Path,
    agent_log: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text() + "\n[capacity]\nmax_chores = 0\n")
    with chore_reports({"status": "done"}):
        assert main(["chore", "try", "build-health", "--no-record"]) == 1
        out = capsys.readouterr().out
        assert "chore try build-health: unknown (the chore's last line was not a valid result" in out
        assert "--- agent text ---" in out
        conn = journal(canopy_env)
        assert conn.execute("SELECT count(*) FROM chore_runs").fetchone()[0] == 0

        assert main(["chore", "try", "build-health"]) == 1
        assert "chore try build-health: unknown (" in capsys.readouterr().out
        row = db.get_chore_run(conn, 1)
        assert row is not None
        assert row["status"] == "unknown"


def test_try_refuses_while_the_chore_runs_unless_it_records_nothing(
    canopy_env: CanopyEnv,
    chores: Path,
    agent_log: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = journal(canopy_env)
    running = db.insert_chore_run(conn, tick_id=None, chore="build-health", logs_dir=canopy_env.state_dir)
    with chore_reports(OK):
        assert main(["chore", "try", "build-health"]) == 1
        err = capsys.readouterr().err
        assert f"chore try refused: chore run {running} of build-health is running; --no-record runs it anyway" in err
        assert conn.execute("SELECT count(*) FROM chore_runs").fetchone()[0] == 1
        assert main(["chore", "try", "build-health", "--no-record"]) == 0


def test_try_refuses_an_unknown_chore_and_inside_canopy_runs(
    canopy_env: CanopyEnv, chores: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["chore", "try", "nope"]) == 1
    assert capsys.readouterr().err.rstrip().endswith("no chore named 'nope' is defined for this workspace")
    with mock.patch.dict(os.environ, {"CANOPY_RUN_ID": "chore-3"}):
        assert main(["chore", "try", "build-health"]) == 1
        assert "chore try refused (inside_run)" in capsys.readouterr().err
        assert journal(canopy_env).execute("SELECT count(*) FROM chore_runs").fetchone()[0] == 0


def test_a_note_to_a_chore_reaches_its_next_runs(
    canopy_env: CanopyEnv,
    chores: Path,
    agent_log: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    note = f"Leave out {FINDING['id']} until 2026-10-15: the fix is merging."
    assert main(["reply", "chore:build-health", note]) == 0
    assert "Recorded message 1 on chore:build-health." in capsys.readouterr().out
    assert main(["reply", "chore:build-health", note]) == 0
    assert "nothing new recorded" in capsys.readouterr().out
    assert main(["reply", "chore:nope", "x"]) == 1
    assert "no chore 'nope' is defined for this workspace" in capsys.readouterr().err

    conn = journal(canopy_env)
    # A note waits for the chore's next run: it does not wake a waiting loop, which wakes for tickets' messages.
    assert db.latest_message_id(conn, source="operator", subject_kind=db.SUBJECT_TICKET) == 0
    run_inline(conn, OK)
    run = run_section(json.loads(agent_log.read_text().splitlines()[-1])["argv"][3])
    [carried] = run["operator_notes"]
    assert (carried["id"], carried["note"]) == (1, note)
    with chore_reports(OK):
        assert main(["chore", "try", "build-health"]) == 0
    assert run_section(json.loads(agent_log.read_text().splitlines()[-1])["argv"][3])["operator_notes"] == [carried]

    capsys.readouterr()
    assert main(["show", "chore:build-health"]) == 0
    shown = capsys.readouterr().out
    assert "Your notes its next run reads (1):" in shown
    assert note in shown


def test_a_dismissed_finding_is_off_the_attention_list_until_the_chore_stops_reporting_it(
    canopy_env: CanopyEnv,
    chores: Path,
    treehouse_state: Path,
    agent_log: Path,
    notified: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = journal(canopy_env)
    page = canopy_env.state_dir / "attention.md"
    run_inline(conn, OK)
    tick()
    assert FINDING["id"] in page.read_text()

    # Only the operator dismisses, and only a finding the chore has open.
    with mock.patch.dict(os.environ, {"CANOPY_TICK_ID": "1"}):
        assert main(["dismiss", "chore:build-health", FINDING["id"]]) == 1
        assert "dismiss refused (inside_run)" in capsys.readouterr().err
    for ref, finding, guard in [
        ("chore:build-health", "stuck/pr-7", "unknown"),
        ("chore:build-health", "not an id", "bad_finding"),
        ("chore:nope", FINDING["id"], "unknown"),
        ("ABC-1", FINDING["id"], "unsupported"),
    ]:
        assert main(["dismiss", ref, finding]) == 1
        assert f"dismiss refused ({guard})" in capsys.readouterr().err
    assert main(["dismiss", "chore:build-health", FINDING["id"], "--undo"]) == 1
    assert "has no dismissed finding" in capsys.readouterr().err

    assert main(["dismiss", "chore:build-health", FINDING["id"]]) == 0
    assert "is dismissed: it is off the attention list" in capsys.readouterr().out
    # `attention.md` is rewritten at once, not at the next tick; a sink hears why the finding left at the next one.
    assert "Nothing needs you." in page.read_text()
    tick()
    assert "Nothing needs you." in page.read_text()
    assert f"- chore:build-health {FINDING['id']} (dismissed)\n" in notified.read_text().split("--\n")[1]
    assert main(["show", "chore:build-health"]) == 0
    assert f"{FINDING['id']}  " in (shown := capsys.readouterr().out)
    assert "(dismissed)" in shown
    assert main(["status"]) == 0
    assert "; 1 finding dismissed" in capsys.readouterr().out

    # A later run still reporting it leaves it dismissed.
    backdate(conn, 120)
    run_inline(conn, OK)
    tick()
    assert "Nothing needs you." in page.read_text()

    # Once a run leaves it out, the dismissal is spent: the finding coming back is listed again.
    backdate(conn, 120)
    run_inline(conn, {"status": "ok", "summary": "all clear"})
    backdate(conn, 120)
    run_inline(conn, OK)
    tick()
    assert FINDING["id"] in page.read_text()

    # Undo lists it again at once.
    assert main(["dismiss", "chore:build-health", FINDING["id"]]) == 0
    cfg = load(canopy_env.root, canopy_env.user_file)
    [found] = view.open_findings(conn, cfg, workspace.load(canopy_env.root))
    assert found.dismissed
    assert main(["dismiss", "chore:build-health", FINDING["id"], "--undo"]) == 0
    assert "is listed again" in capsys.readouterr().out
    [found] = view.open_findings(conn, cfg, workspace.load(canopy_env.root))
    assert not found.dismissed


def test_a_chore_run_records_what_it_cost(
    canopy_env: CanopyEnv,
    chores: Path,
    agent_log: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With OpenCode's JSON events, as the default `chore_cmd` asks for, a chore run records its session and cost."""
    text = canopy_env.user_file.read_text()
    canopy_env.write_user(text.replace("--agent canopy-chore {prompt}", "--agent canopy-chore --format json {prompt}"))
    # The tries after the run report what it did.
    with mock.patch.dict(os.environ, {"FAKE_CHORE_SESSION": "ses_chore"}), chore_reports(OK):
        conn = journal(canopy_env)
        run_id = run_inline(conn, OK)
        row = db.get_chore_run(conn, run_id)
        assert row is not None
        assert row["status"] == "ok"  # the result line is read from the text events
        assert row["session_id"] == "ses_chore"
        usage = db.usage_of(row)
        assert usage is not None
        assert usage.cost_usd == 0.25  # two model calls at 0.125
        assert db.spent_since(conn, "2000-01-01T00:00:00Z") == 0.25

        capsys.readouterr()
        assert main(["show", "chore:build-health"]) == 0
        assert "session ses_chore  $0.25, " in capsys.readouterr().out
        assert main(["chore", "try", "build-health", "--no-record"]) == 0
        assert "--- agent exit 0, cost $0.25, " in capsys.readouterr().out
        # A try that records nothing records its cost neither; a recorded one does.
        assert db.spent_since(conn, "2000-01-01T00:00:00Z") == 0.25
        assert main(["chore", "try", "build-health"]) == 0
        assert db.spent_since(conn, "2000-01-01T00:00:00Z") == 0.5


def test_the_default_chore_cmd_asks_for_events(canopy_env: CanopyEnv) -> None:
    assert "--format json" in load(canopy_env.root, canopy_env.user_file).runtime.chore_cmd
