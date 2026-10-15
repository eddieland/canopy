"""End to end: `canopy tick --dry-run` against the fake treehouse and a fake overseer that calls the real `canopy`."""

import json
import os
import sqlite3
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import config, db, definitions
from canopy.infra import lock, procs
from canopy.loop import attention, tick
from tests.canopy.helpers import in_tick
from tests.canopy.test_mirror import state_block
from tests.conftest import CanopyEnv


def journal(env: CanopyEnv) -> sqlite3.Connection:
    return env.journal(migrate=False)


@contextmanager
def overseer_does(*commands: list[str], last_line: str = "CANOPY_TICK_DONE") -> Iterator[None]:
    with mock.patch.dict(
        os.environ,
        {"FAKE_AGENT_COMMANDS": json.dumps([["canopy", *c] for c in commands]), "FAKE_AGENT_RESULT": last_line},
    ):
        yield


def agent_runs(agent_log: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in agent_log.read_text().splitlines()]


def test_dry_run_tick_records_the_overseer_plan(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with overseer_does(
        ["decide", "PROJ-1", "wait", "--rationale", "checks pending"],
        ["ticket", "set", "PROJ-1", "--repo", "repo", "--phase", "ci_running", "--cursor", "ci=run-1"],
        ["dispatch", "PROJ-2", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"],
        ["attention", "PROJ-3", "needs_reviewer", "--detail", "https://example.test/pr/3"],
        ["decide", "PROJ-4;rm", "wait", "--rationale", "bad key"],
    ):
        assert main(["tick", "--dry-run"]) == 0
        assert capsys.readouterr().out.startswith("tick 1: ok: dry run; 3 decisions")

        [run] = agent_runs(agent_log)
        commands = run["commands"]
        assert isinstance(commands, list)
        assert [c["returncode"] for c in commands] == [0, 0, 0, 0, 2], commands
        argv = run["argv"]
        assert isinstance(argv, list)
        assert argv[:3] == ["run", "--agent", "canopy-overseer"]
        # The message is the state block alone; the prompt is in the definition, cached across ticks (DESIGN §6).
        prompt = argv[3]
        assert isinstance(prompt, str)
        assert prompt.startswith("## State\n")
        assert "# canopy overseer" not in prompt
        assert '"tick_id": 1' in prompt
        assert '"dry_run": true' in prompt
        assert '"labels": [\n      "agent-ready-tester"\n    ]' in prompt
        assert run["cwd"] == str(canopy_env.root)
        snapshot = definitions.ensure(canopy_env.state_dir, config.load(canopy_env.root))
        assert run["env"] == {"CANOPY_TICK_ID": "1", "OPENCODE_CONFIG_DIR": str(snapshot)}
        assert "\n# canopy overseer\n" in (snapshot / "agents" / "canopy-overseer.md").read_text()

        conn = journal(canopy_env)
        [tick] = conn.execute("SELECT * FROM ticks").fetchall()
        assert (tick["status"], tick["dry_run"]) == ("ok", 1)
        assert tick["ended_at"] is not None
        decisions = [(d.ticket_key, d.action) for d in db.decisions_for_tick(conn, 1)]
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
        tick_lines = [
            line for line in log_lines if line["msg"] in ("tick started", "running overseer", "tick finished")
        ]
        assert [line["tick_id"] for line in tick_lines] == [1, 1, 1]
        output = canopy_env.state_dir / "ticks" / "1.log"
        assert output.read_text().startswith("fake agent: starting")
        assert output.stat().st_mode & 0o077 == 0
        # The state block is kept beside it, as the input of the transcript's first model call (DESIGN §22).
        kept = canopy_env.state_dir / "ticks" / "1.prompt"
        assert kept.read_text() == prompt
        assert kept.stat().st_mode & 0o077 == 0
        assert canopy_env.state_dir.stat().st_mode & 0o077 == 0


def test_overseer_state_names_the_configured_needs_human_label(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    canopy_env.write_shared(canopy_env.shared_file.read_text() + 'needs_human_label = "blocked-on-team"\n')
    with overseer_does():
        assert main(["tick", "--dry-run"]) == 0
        [run] = agent_runs(agent_log)
        argv = run["argv"]
        assert isinstance(argv, list)
        assert '"needs_human_label": "blocked-on-team"' in str(argv[3])


def test_overseer_state_names_the_comment_marks(canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path) -> None:
    # The overseer recognizes workers' comments by these, since workers post as the operator (D069).
    canopy_env.write_user(canopy_env.user_file.read_text() + '\n[trust]\ncomment_suffix = "(canopy)"\n')
    with overseer_does():
        assert main(["tick", "--dry-run"]) == 0
        [run] = agent_runs(agent_log)
        argv = run["argv"]
        assert isinstance(argv, list)
        assert '"comment_prefix": "CANOPY:"' in str(argv[3])
        assert '"comment_suffix": "(canopy)"' in str(argv[3])


def test_next_tick_sees_the_journal(canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path) -> None:
    with overseer_does(["ticket", "set", "PROJ-9", "--repo", "repo", "--phase", "needs_human"]):
        assert main(["tick", "--dry-run"]) == 0
    with overseer_does():
        assert main(["tick", "--dry-run"]) == 0
        second = agent_runs(agent_log)[1]["argv"]
        assert isinstance(second, list)
        assert '"key": "PROJ-9"' in second[-1]
        assert '"phase": "needs_human"' in second[-1]
        assert '"tick_id": 2' in second[-1]


def test_the_state_block_names_the_tickets_marked_done_lately(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    # A merged ticket stays open in the tracker until a human closes it, so the query keeps finding it: listed, the
    # overseer leaves it alone instead of reading it, mirroring it, and marking it done again every tick (DESIGN §7).
    conn = canopy_env.journal()
    repo = str(canopy_env.root)
    with in_tick(conn) as tick_id:
        for key in ("PROJ-1", "PROJ-2", "PROJ-3", "PROJ-7"):
            db.set_ticket(conn, key, repo, done=True)
            db.record_decision(conn, tick_id, key, "done", "merged")
        db.set_ticket(conn, "PROJ-4", repo, done=True)
        db.set_ticket(conn, "PROJ-5", repo, phase="ci_running")
        db.record_decision(conn, tick_id, "PROJ-5", "done", "merged")
        # The tracker reports a closed ticket closed, so once it is reopened the query must find it again.
        db.set_ticket(conn, "PROJ-6", repo, done=True)
        db.record_decision(conn, tick_id, "PROJ-6", "done", db.CLOSED_RATIONALE)
        db.finish_tick(conn, tick_id, "ok", "")
    # Forgotten, then marked done again with no decision of its own: the earlier one does not count.
    with db.transaction(conn):
        db.forget_ticket(conn, "PROJ-7")
    db.set_ticket(conn, "PROJ-7", repo, done=True)
    long_ago = db.format_time(datetime.now(UTC) - timedelta(days=tick.RECENTLY_DONE_DAYS + 1))
    with db.transaction(conn):
        conn.execute("UPDATE decisions SET created_at = ? WHERE ticket_key = 'PROJ-2'", (long_ago,))
        # Its newest `done` decision is the one that counts.
        conn.execute("UPDATE decisions SET created_at = ? WHERE ticket_key = 'PROJ-3'", (long_ago,))
    with in_tick(conn) as tick_id:
        newest = db.record_decision(conn, tick_id, "PROJ-3", "done", "merged, still open")
        db.finish_tick(conn, tick_id, "ok", "")
    [done_at] = conn.execute("SELECT created_at FROM decisions WHERE ticket_key = 'PROJ-1'").fetchone()
    [newest_at] = conn.execute("SELECT created_at FROM decisions WHERE id = ?", (newest,)).fetchone()
    with overseer_does():
        assert main(["tick", "--dry-run"]) == 0
        state = state_block(agent_log)
    # Not PROJ-2, done too long ago; not PROJ-4, with no `done` decision; not PROJ-5, which is not marked done; not
    # PROJ-6, closed; not PROJ-7, whose decision came before it was forgotten.
    assert state["recently_done"] == [
        {"key": "PROJ-1", "done_at": done_at},
        {"key": "PROJ-3", "done_at": newest_at},
    ]
    assert [t["key"] for t in state["tickets"]] == ["PROJ-5"]


@pytest.mark.parametrize(
    "case",
    [
        ("3", "CANOPY_TICK_DONE", "overseer exited 3"),
        ("0", "I got distracted", "final message has no CANOPY_TICK_DONE line"),
        ("0", "", "final message has no CANOPY_TICK_DONE line"),
    ],
)
def test_overseer_failure_closes_the_tick(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    case: tuple[str, str, str],
) -> None:
    exit_code, last_line, summary = case
    with overseer_does(last_line=last_line), mock.patch.dict(os.environ, {"FAKE_AGENT_EXIT": exit_code}):
        assert main(["tick", "--dry-run"]) == 1
        tick = journal(canopy_env).execute("SELECT * FROM ticks").fetchone()
        assert tick["status"] == "overseer_failed"
        assert summary in tick["summary"]


@pytest.mark.parametrize(
    ("final", "status"),
    [
        ("CANOPY_TICK_DONE", "ok"),
        ("CANOPY_TICK_DONE\n\nRecorded 6 decisions and dispatched 2 runs.", "ok"),  # a summary after it (tick 150)
        ("Recorded 6 decisions.\n  `CANOPY_TICK_DONE`  ", "ok"),
        ("tick complete", "overseer_failed"),  # the old done line
        ("I'll print CANOPY_TICK_DONE when finished", "overseer_failed"),  # the token is the whole line or nothing
        ("canopy_tick_done", "overseer_failed"),
    ],
)
def test_the_done_token_is_a_line_anywhere_in_the_final_message(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    final: str,
    status: str,
) -> None:
    text = canopy_env.user_file.read_text().replace("--agent canopy-overseer", "--agent canopy-overseer --format json")
    canopy_env.write_user(text)
    with overseer_does(last_line=final):
        main(["tick", "--dry-run"])
        assert journal(canopy_env).execute("SELECT status FROM ticks").fetchone()[0] == status


def test_the_done_token_in_an_earlier_message_fails_the_tick(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
) -> None:
    """A run that named the token, then stopped before the procedure's end, did not finish it."""
    text = canopy_env.user_file.read_text().replace("--agent canopy-overseer", "--agent canopy-overseer --format json")
    canopy_env.write_user(text)
    with (
        mock.patch.dict(os.environ, {"FAKE_AGENT_SAYS": "CANOPY_TICK_DONE"}),
        overseer_does(last_line="Now reading the next ticket."),
    ):
        main(["tick", "--dry-run"])
        tick = journal(canopy_env).execute("SELECT status, summary FROM ticks").fetchone()
        assert (tick["status"], tick["summary"]) == (
            "overseer_failed",
            "overseer's final message has no CANOPY_TICK_DONE line",
        )


@pytest.mark.parametrize(("last_line", "status"), [("CANOPY_TICK_DONE", "ok"), ("I got distracted", "overseer_failed")])
def test_an_overseer_printing_json_events_is_read_by_their_text(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    last_line: str,
    status: str,
) -> None:
    """With OpenCode's `--format json`, its last line of stdout is an event; the done line is in the events' text."""
    text = canopy_env.user_file.read_text().replace("--agent canopy-overseer", "--agent canopy-overseer --format json")
    canopy_env.write_user(text)
    with overseer_does(last_line=last_line):
        main(["tick", "--dry-run"])
        assert journal(canopy_env).execute("SELECT status FROM ticks").fetchone()[0] == status


@pytest.mark.parametrize("last_line", ["CANOPY_TICK_DONE", "I got distracted"])
def test_a_tick_records_and_prints_what_its_overseer_cost(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    capsys: pytest.CaptureFixture[str],
    last_line: str,
) -> None:
    """With events, the tick keeps the overseer's session and summed cost, whether or not the overseer succeeded."""
    text = canopy_env.user_file.read_text().replace("--agent canopy-overseer", "--agent canopy-overseer --format json")
    canopy_env.write_user(text)
    with mock.patch.dict(os.environ, {"FAKE_OVERSEER_SESSION": "ses_o1"}), overseer_does(last_line=last_line):
        main(["tick", "--dry-run"])

        tick = journal(canopy_env).execute("SELECT * FROM ticks").fetchone()
        assert (tick["session_id"], tick["cost_usd"]) == ("ses_o1", 0.25)  # two model calls, summed
        tokens = ("tokens_input", "tokens_output", "tokens_reasoning", "tokens_cache_read", "tokens_cache_write")
        assert tuple(tick[c] for c in tokens) == (2000, 400, 60, 8000, 1000)
        assert tick["tokens_peak_context"] == 5500
        assert capsys.readouterr().out.rstrip().endswith("(cost $0.25, 3.5k new tokens, 5.5k peak context)")


def test_a_running_tick_shows_its_overseer_session(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    """The session is on the tick from the overseer's first event, so a page or `canopy decisions` shows it mid-tick."""
    text = canopy_env.user_file.read_text().replace("--agent canopy-overseer", "--agent canopy-overseer --format json")
    canopy_env.write_user(text)
    with mock.patch.dict(os.environ, {"FAKE_OVERSEER_SESSION": "ses_o1"}), overseer_does(["decisions"]):
        assert main(["tick", "--dry-run"]) == 0

        [run] = agent_runs(agent_log)
        commands = run["commands"]
        assert isinstance(commands, list)
        [decisions] = commands
        assert "Tick 1: running (dry run)" in decisions["stdout"]
        assert "overseer session ses_o1\n" in decisions["stdout"]  # no cost yet: the overseer has not ended


def test_a_tick_whose_overseer_reports_nothing_records_no_cost(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Plain stdout, as from a template without `--format json`, reports no session and no cost."""
    with overseer_does():
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
        on_line: Callable[[str], None] | None = None,
    ) -> procs.Result:
        if "agent" in args[:3]:
            assert timeout == 15 * 60
            return procs.Result(tuple(args), -9, "fake agent: starting\n", "", timed_out=True)
        return procs.SubprocessRunner().run(
            args, cwd=cwd, env=env, stdin=stdin, timeout=timeout, on_start=on_start, on_line=on_line
        )

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:
        return procs.SubprocessRunner().spawn(args, cwd=cwd, log_path=log_path)


def test_overseer_timeout(canopy_env: CanopyEnv, treehouse_state: Path) -> None:
    assert main(["tick", "--dry-run"], runner=TimingOutAgent()) == 1
    tick = journal(canopy_env).execute("SELECT * FROM ticks").fetchone()
    assert (tick["status"], tick["summary"]) == ("overseer_failed", "overseer timed out after 15 minutes")


def test_missing_overseer_command(canopy_env: CanopyEnv, treehouse_state: Path) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text().replace("'env ", "'no-such-program ", 1))
    assert main(["tick", "--dry-run"]) == 1
    tick = journal(canopy_env).execute("SELECT * FROM ticks").fetchone()
    assert tick["status"] == "overseer_failed"
    assert "command not found" in tick["summary"]


def test_treehouse_failure_skips_the_overseer(canopy_env: CanopyEnv, agent_log: Path) -> None:
    with mock.patch.dict(os.environ):
        os.environ.pop("FAKE_TREEHOUSE_STATE", None)  # the fake treehouse then exits 2
        assert main(["tick", "--dry-run"]) == 1
        tick = journal(canopy_env).execute("SELECT * FROM ticks").fetchone()
        assert tick["status"] == "reconcile_failed"
        assert not agent_log.exists()


@contextmanager
def broken_canopy(tmp_path: Path, script: str) -> Iterator[None]:
    """Until the block ends, the `canopy` on PATH, where the overseer would find it, runs `script`, and is the only one.

    The only one: exec reports a missing interpreter as a missing file, so a PATH search goes on to the next `canopy`.
    """
    bin_dir = tmp_path / "broken-bin"
    bin_dir.mkdir()
    launcher = bin_dir / "canopy"
    launcher.write_text(script)
    launcher.chmod(0o755)
    others = [d for d in os.environ["PATH"].split(os.pathsep) if d and not (Path(d) / "canopy").exists()]
    with mock.patch.dict(os.environ, {"PATH": os.pathsep.join([str(bin_dir), *others])}):
        yield


@pytest.mark.parametrize(
    ("script", "summary"),
    [
        # A launcher whose environment is gone: its interpreter no longer exists (MEASUREMENTS 2026-10-12, F1).
        ("#!/nonexistent/venv/bin/python\n", "`canopy` does not start for the overseer: command not found: canopy"),
        (
            "#!/bin/sh\necho 'no module named canopy' >&2\nexit 1\n",
            "`canopy --version` exited 1: no module named canopy",
        ),
    ],
)
def test_a_canopy_that_does_not_work_closes_the_tick_without_the_overseer(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    tmp_path: Path,
    script: str,
    summary: str,
) -> None:
    with overseer_does():
        assert main(["tick", "--dry-run"]) == 0  # an `ok` tick, whose list the failed one leaves standing
        with broken_canopy(tmp_path, script):
            assert main(["tick", "--dry-run"]) == 1
            assert main(["tick", "--dry-run"]) == 1
        assert len(agent_runs(agent_log)) == 1  # the overseer ran for the first tick alone

        conn = journal(canopy_env)
        ticks = conn.execute("SELECT id, status, summary FROM ticks ORDER BY id").fetchall()
        assert [(t["status"], t["summary"]) for t in ticks[1:]] == [("canopy_unavailable", summary)] * 2
        [item] = attention.current(conn)
        assert (item.ticket_key, item.reason) == (None, "canopy_unavailable")
        assert item.detail.startswith(f"{summary}; the overseer did not run.")
        first = conn.execute("SELECT created_at FROM decisions WHERE tick_id = ?", (ticks[1]["id"],)).fetchone()[0]
        assert item.since == first  # open since the first tick of the streak
        assert "canopy_unavailable" in (canopy_env.state_dir / "attention.md").read_text()

        # Once `canopy` works again, the next tick runs the overseer and the item is gone.
        assert main(["tick", "--dry-run"]) == 0
        assert len(agent_runs(agent_log)) == 2
        assert attention.current(conn) == []


def test_busy_lock_exits_zero_without_a_tick(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with lock.hold(canopy_env.state_dir / "lock"):
        assert main(["tick", "--dry-run"]) == 0
    assert "lock_busy" in capsys.readouterr().out
    assert not agent_log.exists()
    assert journal(canopy_env).execute("SELECT count(*) FROM sqlite_master WHERE name = 'ticks'").fetchone()[0] == 0


def test_unfinished_tick_is_abandoned(canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path) -> None:
    with overseer_does():
        assert main(["status"]) == 0  # creates and migrates the journal
        conn = journal(canopy_env)
        dead = db.start_tick(conn, dry_run=True)
        assert main(["tick", "--dry-run"]) == 0
        assert conn.execute("SELECT status FROM ticks WHERE id = ?", (dead,)).fetchone()[0] == "abandoned"


def test_prompt_override(canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path) -> None:
    with overseer_does():
        overrides = canopy_env.user_file.parent / "prompts"
        overrides.mkdir()
        (overrides / "overseer.md").write_text("# my overseer\n")
        assert main(["tick", "--dry-run"]) == 0
        [run] = agent_runs(agent_log)
        argv, env = run["argv"], run["env"]
        assert isinstance(argv, list)
        assert isinstance(env, dict)
        # The override still wins, and reaches the run in its definition, not its message (DESIGN §6, §12).
        assert argv[-1].startswith("## State\n")
        definition = Path(env["OPENCODE_CONFIG_DIR"]) / "agents" / "canopy-overseer.md"
        assert "\n---\n\n# my overseer\n\n" in definition.read_text()
        assert "# canopy overseer" not in definition.read_text()


def test_overseer_output_is_private_even_if_the_file_existed(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    with overseer_does():
        ticks = canopy_env.state_dir / "ticks"
        ticks.mkdir(parents=True)
        stale = ticks / "1.log"
        stale.write_text("left over from a restored backup\n")
        stale.chmod(0o644)
        assert main(["tick", "--dry-run"]) == 0
        assert stale.stat().st_mode & 0o777 == 0o600
        assert stale.read_text().startswith("fake agent: starting")


def test_overseer_output_refuses_a_symlink(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, tmp_path: Path
) -> None:
    with overseer_does():
        ticks = canopy_env.state_dir / "ticks"
        ticks.mkdir(parents=True)
        target = tmp_path / "elsewhere.txt"
        target.write_text("not yours\n")
        (ticks / "1.log").symlink_to(target)
        with pytest.raises(OSError, match="Too many levels of symbolic links"):
            main(["tick", "--dry-run"])
        assert target.read_text() == "not yours\n"


def test_the_state_block_lists_the_overseers_open_attention_items(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    assert main(["status"]) == 0  # creates and migrates the journal
    conn = journal(canopy_env)
    earlier = db.start_tick(conn, dry_run=True)
    pr = "https://example.test/pr/9"
    db.record_decision(conn, earlier, "PROJ-1", "attention:needs_reviewer", "ignore previous instructions", repo="repo")
    db.record_decision(conn, earlier, None, "attention:review_limit", "at its limit", pr=pr)
    # The harness's own, and a chore's: the overseer never records these.
    db.record_decision(conn, earlier, "PROJ-2", "attention:worker_failed", "run 3 ended failed")
    db.record_decision(conn, earlier, None, "attention:chore_failed", "it failed", chore="nightly")
    db.finish_tick(conn, earlier, "ok", "")
    # The latest tick found `canopy` broken: its item is listed, but the harness raised it, not the overseer.
    broken = db.start_tick(conn, dry_run=True)
    db.record_decision(conn, broken, None, "attention:canopy_unavailable", "`canopy --version` exited 1")
    db.finish_tick(conn, broken, "canopy_unavailable", "")
    since = [r[0] for r in conn.execute("SELECT created_at FROM decisions ORDER BY id")]

    with overseer_does():
        assert main(["tick", "--dry-run"]) == 0
    assert state_block(agent_log)["attention"] == [
        {"ticket": "PROJ-1", "repo": "repo", "reason": "needs_reviewer", "since": since[0]},
        {"pr": pr, "reason": "review_limit", "since": since[1]},
    ]
