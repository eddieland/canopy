"""`canopy daemon`: `canopy loop` detached, against the fake treehouse and a fake overseer.

The daemon is a real process, so these tests wait on it, polling with a deadline, rather than on a fake clock.
"""

import contextlib
import os
import signal
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import db
from canopy.core.vocab import RunStatus
from canopy.infra import lock
from canopy.loop import daemon, repeat
from tests.canopy.helpers import context, live_run, overseer_does
from tests.conftest import CanopyEnv

DEADLINE_SECONDS = 30.0


@pytest.fixture
def daemon_env(canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path) -> Iterator[CanopyEnv]:
    """The workspace, with the fakes on PATH; a daemon a failed test leaves running is killed when it ends."""
    try:
        yield canopy_env
    finally:
        pid = daemon.state(canopy_env.state_dir).pid
        if pid is not None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)


def test_start_detaches_the_loop_and_stop_ends_it(daemon_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    log = daemon_env.state_dir / daemon.LOG_FILE_NAME
    with overseer_does():
        assert main(["daemon", "start", "--dry-run", "--no-serve", "--every", "60"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("canopy daemon started, pid ")
    assert str(log) in out
    assert lock.held(daemon_env.state_dir / repeat.LOCK_FILE_NAME)
    _until(lambda: 'msg="tick ended" tick=1 status=ok ' in log.read_text())  # the loop's log, in logfmt

    assert main(["daemon", "status"]) == 0
    assert "canopy daemon: running, pid " in capsys.readouterr().out
    assert main(["daemon", "start"]) == 1
    assert "the canopy daemon is already running" in capsys.readouterr().err

    assert main(["daemon", "stop"]) == 0  # during the wait, so at once
    assert capsys.readouterr().out.startswith("canopy daemon stopped, pid ")
    assert not lock.held(daemon_env.state_dir / repeat.LOCK_FILE_NAME)
    assert not (daemon_env.state_dir / daemon.PID_FILE_NAME).exists()
    assert main(["daemon", "status"]) == 1
    assert capsys.readouterr().out == "canopy daemon: not running\n"


def test_stop_refuses_while_runs_are_running(daemon_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    """A canopy that changes the journal does not start under a live run, so the daemon is not stopped under one."""
    _started(daemon_env)
    run_id = live_run(daemon_env, context(daemon_env), "PROJ-9")
    capsys.readouterr()

    assert main(["daemon", "stop"]) == 1
    err = capsys.readouterr().err
    assert f"canopy daemon not stopped: run {run_id} is still running." in err
    assert "`canopy daemon stop --wait` stops it once they end" in err
    assert daemon.state(daemon_env.state_dir).pid is not None


def test_stop_wait_stops_the_daemon_once_its_runs_end(
    daemon_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    log = _started(daemon_env)
    ctx = context(daemon_env)
    run_id = live_run(daemon_env, ctx, "PROJ-9")
    capsys.readouterr()
    exits: list[int] = []
    stopping = threading.Thread(target=lambda: exits.append(main(["daemon", "stop", "--wait"])))
    stopping.start()
    try:
        _until(lambda: 'msg="waiting for runs" runs="PROJ-9 implement"' in log.read_text())
        assert daemon.state(daemon_env.state_dir).pid is not None
    finally:
        db.finish_run(ctx.conn, "runs", run_id, RunStatus.DONE, None)
        stopping.join(DEADLINE_SECONDS)
    assert exits == [0]
    assert "canopy daemon stopped, pid " in capsys.readouterr().out
    assert 'msg="runs ended"' in log.read_text()
    assert daemon.state(daemon_env.state_dir).pid is None


def test_a_daemon_that_ends_on_its_own_says_so(daemon_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    with overseer_does():
        assert main(["daemon", "start", "--dry-run", "--no-serve", "--ticks", "1"]) == 0
    _until(lambda: daemon.state(daemon_env.state_dir).pid is None)
    capsys.readouterr()
    assert main(["daemon", "status"]) == 1
    assert "it exited without `canopy daemon stop`" in capsys.readouterr().out
    assert main(["daemon", "stop"]) == 0
    assert capsys.readouterr().out == "canopy daemon is not running\n"
    assert main(["daemon", "status"]) == 1
    assert capsys.readouterr().out == "canopy daemon: not running\n"


def test_a_loop_that_exits_at_once_fails_the_start_with_its_output(
    daemon_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["daemon", "start", "--every", "0"]) == 1
    err = capsys.readouterr().err
    assert "the loop exited before it started" in err
    assert "Invalid value for '--every'" in err
    assert not (daemon_env.state_dir / daemon.PID_FILE_NAME).exists()


def test_start_refuses_while_another_loop_holds_the_lock(
    daemon_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with lock.hold(daemon_env.state_dir / repeat.LOCK_FILE_NAME):
        assert main(["daemon", "start"]) == 1
        assert "another canopy loop is running" in capsys.readouterr().err
        assert main(["daemon", "status"]) == 1
        assert "a canopy loop not started by it is running" in capsys.readouterr().out
    assert not (daemon_env.state_dir / daemon.LOG_FILE_NAME).exists()  # nothing was started


@pytest.mark.parametrize("verb", ["start", "stop"])
def test_start_and_stop_refuse_inside_canopys_runs(
    daemon_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
    verb: str,
) -> None:
    with mock.patch.dict(os.environ, {"CANOPY_TICK_ID": "1"}):
        assert main(["daemon", verb]) == 1
    assert f"daemon {verb} refused (inside_run)" in capsys.readouterr().err
    assert not (daemon_env.state_dir / daemon.LOG_FILE_NAME).exists()


def _started(env: CanopyEnv) -> Path:
    """Start the daemon on dry runs, an hour apart, and wait until its first tick ends.

    Returns:
        The daemon's log.
    """
    log = env.state_dir / daemon.LOG_FILE_NAME
    with overseer_does():
        assert main(["daemon", "start", "--dry-run", "--no-serve", "--every", "60"]) == 0
    _until(lambda: 'msg="tick ended" tick=1 ' in log.read_text())
    return log


def _until(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + DEADLINE_SECONDS
    while not condition():
        assert time.monotonic() < deadline, "timed out waiting for the daemon"
        time.sleep(0.05)
