"""End to end: `canopy tick --dry-run` against the fake treehouse and a fake overseer that calls the real `canopy`."""

import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import config, db, definitions
from canopy.infra import lock, procs
from tests.conftest import CanopyEnv


def journal(env: CanopyEnv) -> sqlite3.Connection:
    return db.connect(env.state_dir / "canopy.db")


def overseer_does(monkeypatch: pytest.MonkeyPatch, *commands: list[str], last_line: str = "tick complete") -> None:
    monkeypatch.setenv("FAKE_AGENT_COMMANDS", json.dumps([["canopy", *c] for c in commands]))
    monkeypatch.setenv("FAKE_AGENT_RESULT", last_line)


def agent_runs(agent_log: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in agent_log.read_text().splitlines()]


def test_dry_run_tick_records_the_overseer_plan(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    overseer_does(
        monkeypatch,
        ["decide", "PROJ-1", "wait", "--rationale", "checks pending"],
        ["ticket", "set", "PROJ-1", "--repo", "repo", "--phase", "ci_running", "--cursor", "ci=run-1"],
        ["dispatch", "PROJ-2", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"],
        ["attention", "PROJ-3", "needs_reviewer", "--detail", "https://example.test/pr/3"],
        ["decide", "PROJ-4;rm", "wait", "--rationale", "bad key"],
    )
    assert main(["tick", "--dry-run"]) == 0
    assert capsys.readouterr().out.startswith("tick 1: ok: dry run; 3 decisions")

    [run] = agent_runs(agent_log)
    commands = run["commands"]
    assert isinstance(commands, list)
    assert [c["returncode"] for c in commands] == [0, 0, 0, 0, 2], commands
    argv = run["argv"]
    assert isinstance(argv, list)
    assert argv[:3] == ["run", "--agent", "canopy-overseer"]
    prompt = argv[3]
    assert isinstance(prompt, str)
    assert prompt.startswith("# canopy overseer")
    assert '"tick_id": 1' in prompt
    assert '"dry_run": true' in prompt
    assert '"labels": [\n      "agent-ready-tester"\n    ]' in prompt
    assert run["cwd"] == str(canopy_env.root)
    snapshot = definitions.ensure(canopy_env.state_dir, config.load(canopy_env.root))
    assert run["env"] == {"CANOPY_TICK_ID": "1", "OPENCODE_CONFIG_DIR": str(snapshot)}

    conn = journal(canopy_env)
    [tick] = conn.execute("SELECT * FROM ticks").fetchall()
    assert (tick["status"], tick["dry_run"]) == ("ok", 1)
    assert tick["ended_at"] is not None
    decisions = [(d["ticket_key"], d["action"]) for d in db.decisions_for_tick(conn, 1)]
    assert decisions == [
        ("PROJ-1", "wait"),
        ("PROJ-2", "dispatch:implement"),
        ("PROJ-3", "attention:needs_reviewer"),
    ]
    proj1 = conn.execute("SELECT * FROM tickets WHERE key = 'PROJ-1'").fetchone()
    assert proj1["phase"] is None
    [unit] = db.units(conn, "PROJ-1")  # a phase about the PR is the unit's
    assert (unit["phase"], unit["last_ci_run_id"]) == ("ci_running", None)  # a dry run never advances cursors
    assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0  # nothing was dispatched
    assert [c[0] for c in json.loads(treehouse_state.read_text())["calls"]] == ["status"]

    log_lines = [json.loads(line) for line in (canopy_env.state_dir / "canopy.log").read_text().splitlines()]
    tick_lines = [line for line in log_lines if line["msg"] in ("tick started", "running overseer", "tick finished")]
    assert [line["tick_id"] for line in tick_lines] == [1, 1, 1]
    output = canopy_env.state_dir / "ticks" / "1.log"
    assert output.read_text().startswith("fake agent: starting")
    assert output.stat().st_mode & 0o077 == 0
    assert canopy_env.state_dir.stat().st_mode & 0o077 == 0


def test_overseer_state_names_the_configured_needs_human_label(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canopy_env.write_shared(canopy_env.shared_file.read_text() + 'needs_human_label = "blocked-on-team"\n')
    overseer_does(monkeypatch)
    assert main(["tick", "--dry-run"]) == 0
    [run] = agent_runs(agent_log)
    argv = run["argv"]
    assert isinstance(argv, list)
    assert '"needs_human_label": "blocked-on-team"' in str(argv[3])


def test_overseer_state_names_the_comment_marks(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The overseer recognizes workers' comments by these, since workers post as the operator (D069).
    canopy_env.write_user(canopy_env.user_file.read_text() + '\n[trust]\ncomment_suffix = "(canopy)"\n')
    overseer_does(monkeypatch)
    assert main(["tick", "--dry-run"]) == 0
    [run] = agent_runs(agent_log)
    argv = run["argv"]
    assert isinstance(argv, list)
    assert '"comment_prefix": "CANOPY:"' in str(argv[3])
    assert '"comment_suffix": "(canopy)"' in str(argv[3])


def test_next_tick_sees_the_journal(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    overseer_does(monkeypatch, ["ticket", "set", "PROJ-9", "--repo", "repo", "--phase", "needs_human"])
    assert main(["tick", "--dry-run"]) == 0
    overseer_does(monkeypatch)
    assert main(["tick", "--dry-run"]) == 0
    second = agent_runs(agent_log)[1]["argv"]
    assert isinstance(second, list)
    assert '"key": "PROJ-9"' in second[-1]
    assert '"phase": "needs_human"' in second[-1]
    assert '"tick_id": 2' in second[-1]


@pytest.mark.parametrize(
    "case",
    [
        ("3", "tick complete", "overseer exited 3"),
        ("0", "I got distracted", "did not end with 'tick complete'"),
        ("0", "", "did not end with 'tick complete'"),
    ],
)
def test_overseer_failure_closes_the_tick(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: tuple[str, str, str],
) -> None:
    exit_code, last_line, summary = case
    overseer_does(monkeypatch, last_line=last_line)
    monkeypatch.setenv("FAKE_AGENT_EXIT", exit_code)
    assert main(["tick", "--dry-run"]) == 1
    tick = journal(canopy_env).execute("SELECT * FROM ticks").fetchone()
    assert tick["status"] == "overseer_failed"
    assert summary in tick["summary"]


@pytest.mark.parametrize(("last_line", "status"), [("tick complete", "ok"), ("I got distracted", "overseer_failed")])
def test_an_overseer_printing_json_events_is_read_by_their_text(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    monkeypatch: pytest.MonkeyPatch,
    last_line: str,
    status: str,
) -> None:
    """With OpenCode's `--format json`, its last line of stdout is an event; the done line is in the events' text."""
    text = canopy_env.user_file.read_text().replace("--agent canopy-overseer", "--agent canopy-overseer --format json")
    canopy_env.write_user(text)
    overseer_does(monkeypatch, last_line=last_line)
    main(["tick", "--dry-run"])
    assert journal(canopy_env).execute("SELECT status FROM ticks").fetchone()[0] == status


@pytest.mark.parametrize("last_line", ["tick complete", "I got distracted"])
def test_a_tick_records_and_prints_what_its_overseer_cost(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    last_line: str,
) -> None:
    """With events, the tick keeps the overseer's session and summed cost, whether or not the overseer succeeded."""
    text = canopy_env.user_file.read_text().replace("--agent canopy-overseer", "--agent canopy-overseer --format json")
    canopy_env.write_user(text)
    monkeypatch.setenv("FAKE_OVERSEER_SESSION", "ses_o1")
    overseer_does(monkeypatch, last_line=last_line)
    main(["tick", "--dry-run"])

    tick = journal(canopy_env).execute("SELECT * FROM ticks").fetchone()
    assert (tick["session_id"], tick["cost_usd"]) == ("ses_o1", 0.25)  # two model calls, summed
    tokens = ("tokens_input", "tokens_output", "tokens_reasoning", "tokens_cache_read", "tokens_cache_write")
    assert tuple(tick[c] for c in tokens) == (2000, 400, 60, 8000, 1000)
    assert capsys.readouterr().out.rstrip().endswith("(cost $0.25, 11.5k tokens)")


def test_a_tick_whose_overseer_reports_nothing_records_no_cost(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Plain stdout, as from a template without `--format json`, reports no session and no cost."""
    overseer_does(monkeypatch)
    main(["tick", "--dry-run"])
    tick = journal(canopy_env).execute("SELECT * FROM ticks").fetchone()
    assert (tick["status"], tick["session_id"], tick["cost_usd"]) == ("ok", None, None)
    assert "cost" not in capsys.readouterr().out


def test_overseer_refuses_to_start_when_the_workspace_defines_its_agent(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    # The overseer runs at the workspace root, where OpenCode reads config (D044).
    config = canopy_env.root / "opencode.json"
    config.write_text('{"agent": {"canopy-overseer": {"permission": {"bash": {"*": "deny", "rm *": "allow"}}}}}')
    assert main(["tick", "--dry-run"]) == 1
    tick = journal(canopy_env).execute("SELECT * FROM ticks").fetchone()
    assert tick["status"] == "overseer_failed"
    assert f"defines one of canopy's agents ({config})" in tick["summary"]
    assert not agent_log.exists()


class TimingOutAgent:
    """Runs everything for real except the agent, which times out."""

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        timeout: float | None = None,
        on_start: Callable[[int], None] | None = None,
    ) -> procs.Result:
        if "agent" in args[:3]:
            assert timeout == 15 * 60
            return procs.Result(tuple(args), -9, "fake agent: starting\n", "", timed_out=True)
        return procs.SubprocessRunner().run(args, cwd=cwd, env=env, stdin=stdin, timeout=timeout, on_start=on_start)

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:
        return procs.SubprocessRunner().spawn(args, cwd=cwd, log_path=log_path)


def test_overseer_timeout(canopy_env: CanopyEnv, treehouse_state: Path) -> None:
    assert main(["tick", "--dry-run"], runner=TimingOutAgent()) == 1
    tick = journal(canopy_env).execute("SELECT * FROM ticks").fetchone()
    assert (tick["status"], tick["summary"]) == ("overseer_failed", "overseer timed out after 15 minutes")


def test_missing_overseer_command(
    canopy_env: CanopyEnv, treehouse_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text().replace("'env ", "'no-such-program ", 1))
    assert main(["tick", "--dry-run"]) == 1
    tick = journal(canopy_env).execute("SELECT * FROM ticks").fetchone()
    assert tick["status"] == "overseer_failed"
    assert "command not found" in tick["summary"]


def test_treehouse_failure_skips_the_overseer(
    canopy_env: CanopyEnv, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FAKE_TREEHOUSE_STATE", raising=False)  # the fake treehouse then exits 2
    assert main(["tick", "--dry-run"]) == 1
    tick = journal(canopy_env).execute("SELECT * FROM ticks").fetchone()
    assert tick["status"] == "reconcile_failed"
    assert not agent_log.exists()


def test_busy_lock_exits_zero_without_a_tick(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with lock.hold(canopy_env.state_dir / "lock"):
        assert main(["tick", "--dry-run"]) == 0
    assert "lock_busy" in capsys.readouterr().out
    assert not agent_log.exists()
    assert journal(canopy_env).execute("SELECT count(*) FROM sqlite_master WHERE name = 'ticks'").fetchone()[0] == 0


def test_unfinished_tick_is_abandoned(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    overseer_does(monkeypatch)
    assert main(["status"]) == 0  # creates and migrates the journal
    conn = journal(canopy_env)
    dead = db.start_tick(conn, dry_run=True)
    assert main(["tick", "--dry-run"]) == 0
    assert conn.execute("SELECT status FROM ticks WHERE id = ?", (dead,)).fetchone()[0] == "abandoned"


def test_prompt_override(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    overseer_does(monkeypatch)
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "overseer.md").write_text("# my overseer\n")
    assert main(["tick", "--dry-run"]) == 0
    argv = agent_runs(agent_log)[0]["argv"]
    assert isinstance(argv, list)
    assert argv[-1].startswith("# my overseer\n\n## State\n")


def test_overseer_output_is_private_even_if_the_file_existed(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    overseer_does(monkeypatch)
    ticks = canopy_env.state_dir / "ticks"
    ticks.mkdir(parents=True)
    stale = ticks / "1.log"
    stale.write_text("left over from a restored backup\n")
    stale.chmod(0o644)
    assert main(["tick", "--dry-run"]) == 0
    assert stale.stat().st_mode & 0o777 == 0o600
    assert stale.read_text().startswith("fake agent: starting")


def test_overseer_output_refuses_a_symlink(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    overseer_does(monkeypatch)
    ticks = canopy_env.state_dir / "ticks"
    ticks.mkdir(parents=True)
    target = tmp_path / "elsewhere.txt"
    target.write_text("not yours\n")
    (ticks / "1.log").symlink_to(target)
    with pytest.raises(OSError, match="Too many levels of symbolic links"):
        main(["tick", "--dry-run"])
    assert target.read_text() == "not yours\n"
