"""`canopy daemon`: `canopy loop` detached from the terminal, started, stopped, and asked after (DESIGN §6, D042).

The daemon is the same loop, started through `procs.Runner.spawn` from the workspace root: it leads its own session,
holds the lifelock beside its log for its whole life, and appends its output to `<state_dir>/daemon.log`. Nothing is
installed with the operating system, nothing restarts it, and it does not start at login. Its pid is kept in
`<state_dir>/daemon.pid` so `stop` can signal it; whether it runs is its lifelock, never the pid.

`stop` refuses while runs are running, unless told to wait for them: a canopy started next that changes the journal
does not migrate it under them, so the daemon stopped could not be started again until they end.
"""

from __future__ import annotations

import contextlib
import os
import signal
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from canopy.core import db
from canopy.infra import lock, procs
from canopy.loop import repeat

LOG_FILE_NAME = "daemon.log"
PID_FILE_NAME = "daemon.pid"
# How long `start` waits for the loop to take its lock before it reports the loop started anyway: a slow import or
# migration is not a failure, and the log says what followed.
START_TIMEOUT_SECONDS = 15.0
# How long `stop` waits before saying it waits for the running tick.
QUIET_STOP_SECONDS = 1.0
POLL_SECONDS = 0.05


class DaemonError(Exception):
    """The daemon could not be started: one runs already, a loop holds the lock, or it exited before taking it."""


class RunsRunningError(Exception):
    """`stop` was not told to wait, and runs are running. The daemon was not signalled."""

    def __init__(self, runs: Sequence[str]) -> None:
        """Name the runs that are running, as `db.live_runs` does."""
        super().__init__(", ".join(runs))
        #: Each run, `run 3` or `review run 4`.
        self.runs = tuple(runs)


@dataclass(frozen=True)
class State:
    """What `status` reports.

    `pid` and `since` are set while the daemon runs. `exited` is set when it was started and ended without
    `canopy daemon stop`. `foreground` is set when no daemon runs but another loop holds `<state_dir>/loop.lock`.
    """

    log_path: Path
    pid: int | None = None
    since: str | None = None
    exited: bool = False
    foreground: bool = False


def state(state_dir: Path) -> State:
    """Return whether the daemon of the workspace whose state directory is `state_dir` runs.

    Returns:
        The daemon's state. Reading it changes nothing.
    """
    log_path = state_dir / LOG_FILE_NAME
    pid_file = state_dir / PID_FILE_NAME
    pid = _read_pid(pid_file)
    if pid is not None and procs.running(log_path, pid):
        since = datetime.fromtimestamp(pid_file.stat().st_mtime, UTC).isoformat()
        return State(log_path=log_path, pid=pid, since=since)
    foreground = lock.held(state_dir / repeat.LOCK_FILE_NAME)
    return State(log_path=log_path, exited=pid is not None, foreground=foreground)


def start(runner: procs.Runner, root: Path, state_dir: Path, loop_args: Sequence[str]) -> int:
    """Start `canopy loop` with `loop_args`, detached, in the workspace at `root`, and wait until it takes its lock.

    Returns:
        The daemon's pid.

    Raises:
        DaemonError: The daemon runs already, another loop holds the loop's lock, or the loop exited before taking
            it; the last holds what it printed.
    """
    current = state(state_dir)
    if current.pid is not None:
        raise DaemonError(f"the canopy daemon is already running, pid {current.pid}")
    if current.foreground:
        raise DaemonError(f"another canopy loop is running on {state_dir}; stop it first")
    log_path = current.log_path
    offset = log_path.stat().st_size if log_path.exists() else 0
    # The interpreter that runs this canopy, as dispatch starts `_run` (DESIGN §5): PATH may name another canopy.
    argv = [sys.executable, "-m", "canopy", "loop", *loop_args]
    try:
        pid = runner.spawn(argv, cwd=root, log_path=log_path)
    except procs.ProcError as e:
        raise DaemonError(str(e)) from None
    (state_dir / PID_FILE_NAME).write_text(f"{pid}\n")
    _await_lock(state_dir, log_path, pid, offset)
    return pid


def _await_lock(state_dir: Path, log_path: Path, pid: int, offset: int) -> None:
    """Wait until the loop started as `pid` holds the loop's lock, for at most START_TIMEOUT_SECONDS.

    Raises:
        DaemonError: The loop exited first, such as on a config error or an option `canopy loop` refuses. Its output
            from `offset` on is in the message.
    """
    deadline = time.monotonic() + START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if lock.held(state_dir / repeat.LOCK_FILE_NAME):
            return
        if not procs.running(log_path, pid):
            _forget(state_dir, log_path)
            with log_path.open(encoding="utf-8", errors="replace") as f:
                f.seek(offset)
                printed = f.read().strip()
            raise DaemonError("the loop exited before it started" + (f":\n{printed}" if printed else ""))
        time.sleep(POLL_SECONDS)


def stop(state_dir: Path, *, wait_for_runs: bool, waiting: Callable[[int], None]) -> int | None:
    """Stop the daemon, and wait until it exits: at once during a wait, after the running tick otherwise.

    Without `wait_for_runs`, the daemon is sent SIGTERM, and only when no run is running. With it, it is sent SIGINT,
    as a Ctrl-C stops a loop: it ticks no more, and exits once every run has ended.

    Args:
        state_dir: The workspace's state directory.
        wait_for_runs: Stop the daemon once its runs end, rather than refuse while they run.
        waiting: Called once with the pid, if the daemon has not exited QUIET_STOP_SECONDS after the signal.

    Returns:
        The pid of the daemon stopped, or None when none ran.

    Raises:
        RunsRunningError: Runs are running and `wait_for_runs` is not set.
    """
    current = state(state_dir)
    if current.pid is None:
        _forget(state_dir, current.log_path)
        return None
    if not wait_for_runs and (running := _live_runs(state_dir)):
        raise RunsRunningError(running)
    with contextlib.suppress(ProcessLookupError):  # it exited since `state` asked
        os.kill(current.pid, signal.SIGINT if wait_for_runs else signal.SIGTERM)
    told_at = time.monotonic() + QUIET_STOP_SECONDS
    while procs.running(current.log_path, current.pid):
        if told_at is not None and time.monotonic() >= told_at:
            waiting(current.pid)
            told_at = None
        time.sleep(POLL_SECONDS)
    _forget(state_dir, current.log_path)
    return current.pid


def _live_runs(state_dir: Path) -> list[str]:
    """Return the runs that are running in the journal under `state_dir`, which the running daemon migrated.

    Returns:
        Each run, as `db.live_runs` names it; none when there is no journal.
    """
    path = state_dir / db.DB_FILE_NAME
    if not path.exists():
        return []
    with contextlib.closing(db.connect(path)) as conn:
        return db.live_runs(conn)


def _read_pid(pid_file: Path) -> int | None:
    try:
        text = pid_file.read_text().strip()
    except FileNotFoundError:
        return None
    return int(text) if text.isdigit() else None


def _forget(state_dir: Path, log_path: Path) -> None:
    """Remove the pid file and the lifelock of a daemon that no longer runs. The log stays."""
    (state_dir / PID_FILE_NAME).unlink(missing_ok=True)
    procs.drop_lifelock(log_path)
