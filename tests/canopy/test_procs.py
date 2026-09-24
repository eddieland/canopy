import json
import time
from pathlib import Path

import pytest

from canopy.procs import CommandNotFoundError, ProcError, SubprocessRunner


def test_captures_stdout_and_exit_code(agent_log: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_AGENT_RESULT", '{"status":"failed"}')
    monkeypatch.setenv("FAKE_AGENT_EXIT", "7")
    result = SubprocessRunner().run(["agent", "hello"])
    assert result.args == ("agent", "hello")
    assert result.returncode == 7
    assert not result.ok
    assert not result.timed_out
    assert result.stdout.splitlines()[-1] == '{"status":"failed"}'


def test_runs_in_cwd_with_merged_env(agent_log: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "slot"
    workdir.mkdir()
    result = SubprocessRunner().run(["agent"], cwd=workdir, env={"FAKE_AGENT_RESULT": "last"})
    assert result.ok
    assert result.stdout.splitlines()[-1] == "last"
    # FAKE_AGENT_LOG came from the inherited environment, FAKE_AGENT_RESULT from `env`.
    assert json.loads(agent_log.read_text())["cwd"] == str(workdir)


def test_timeout_kills_and_keeps_partial_output(agent_log: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_AGENT_SLEEP", "30")
    started = time.monotonic()
    result = SubprocessRunner().run(["agent"], timeout=0.5)
    assert time.monotonic() - started < 10
    assert result.timed_out
    assert not result.ok
    assert "fake agent: starting" in result.stdout
    assert "nothing to do" not in result.stdout


def test_stdin_is_passed(fakes_on_path: Path, tmp_path: Path) -> None:
    script = tmp_path / "echo-stdin"
    script.write_text("#!/bin/sh\ncat\n")
    script.chmod(0o755)
    result = SubprocessRunner().run([str(script)], stdin="the attention diff\n")
    assert result.ok
    assert result.stdout == "the attention diff\n"


def test_missing_command_raises(tmp_path: Path) -> None:
    with pytest.raises(CommandNotFoundError, match="command not found"):
        SubprocessRunner().run([str(tmp_path / "no-such-command")])


def test_missing_cwd_is_not_reported_as_missing_command(agent_log: Path, tmp_path: Path) -> None:
    with pytest.raises(ProcError, match="working directory") as exc:
        SubprocessRunner().run(["agent"], cwd=tmp_path / "gone")
    assert not isinstance(exc.value, CommandNotFoundError)
