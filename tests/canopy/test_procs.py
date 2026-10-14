import contextlib
import gc
import json
import os
import signal
import sys
import time
import warnings
from pathlib import Path
from unittest import mock

import pytest

from canopy.infra import lock, procs
from canopy.infra.procs import CommandNotFoundError, ProcError, SubprocessRunner


def test_captures_stdout_and_exit_code(agent_log: Path) -> None:
    with mock.patch.dict(os.environ, {"FAKE_AGENT_RESULT": '{"status":"failed"}', "FAKE_AGENT_EXIT": "7"}):
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


def test_a_child_given_a_cwd_gets_a_pwd_naming_it(tmp_path: Path) -> None:
    # OpenCode runs its tools in $PWD, not its working directory, so a stale inherited PWD misplaces a worker's edits.
    # `env` prints PWD as given; a shell would correct it and hide the bug.
    with mock.patch.dict(os.environ, {"PWD": "/somewhere/else"}):
        workdir = tmp_path / "slot"
        workdir.mkdir()
        for env in (None, {"EXTRA": "1"}):
            result = SubprocessRunner().run(["env"], cwd=workdir, env=env)
            assert f"PWD={workdir}" in result.stdout.splitlines()
        log = tmp_path / "spawn.log"
        pid = SubprocessRunner().spawn(["env"], cwd=workdir, log_path=log)
        # `spawn` drops its Popen, whose `__del__` reaps the child if it has already exited, as `env` may have.
        with contextlib.suppress(ChildProcessError):
            os.waitpid(pid, 0)
        assert f"PWD={workdir}" in log.read_text().splitlines()


def test_timeout_kills_and_keeps_partial_output(agent_log: Path) -> None:
    started = time.monotonic()
    with mock.patch.dict(os.environ, {"FAKE_AGENT_SLEEP": "30"}):
        result = SubprocessRunner().run(["agent"], timeout=0.5)
    assert time.monotonic() - started < 10
    assert result.timed_out
    assert not result.ok
    assert "fake agent: starting" in result.stdout
    assert "nothing to do" not in result.stdout


def test_timeout_leaves_no_descendant_behind(tmp_path: Path) -> None:
    """A wrapper's children die with it: what a sandbox prefix starts is in the group a timeout kills."""
    # The grandchild holds a FIFO's write end, not the run's pipes, so a survivor shows up here rather than hang the
    # run. Its reader sees EOF only once every writer has exited: unlike asking after a pid, that cannot mistake a
    # reused pid or an unreaped zombie for a survivor.
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    reader = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
    # The grandchild says its pid, so a failure can say what state it was left in.
    script = f"sh -c 'echo $$; exec sleep 30' > {fifo} 2> /dev/null & wait"

    def read() -> bytes | None:
        """What the FIFO holds: None while a writer is open with nothing written, b"" once none is."""
        with contextlib.suppress(BlockingIOError):
            return os.read(reader, 64)
        return None

    said: list[bytes] = []

    def await_grandchild(_pid: int) -> None:
        # The timeout starts after this returns, so on a loaded machine it cannot kill the shell before the grandchild
        # has said its pid. Until a writer opens the FIFO, a read sees no writer and returns b"" too.
        deadline = time.monotonic() + 10
        while not said and time.monotonic() < deadline:
            if line := read():
                said.append(line)
            time.sleep(0.01)

    try:
        result = SubprocessRunner().run(["sh", "-c", script], timeout=0.5, on_start=await_grandchild)
        assert result.timed_out
        [grandchild] = (int(line) for line in said)
        deadline = time.monotonic() + 5
        while (left := read()) != b"" and time.monotonic() < deadline:
            time.sleep(0.05)
        assert left == b"", f"grandchild {grandchild} outlived the timeout: {_stat(grandchild)}"
    finally:
        os.close(reader)


def _stat(pid: int) -> str:
    """What /proc says of `pid`: its state, parent, and group, which follow its parenthesized command name."""
    try:
        state, parent, group = Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[:3]
    except OSError as e:
        return f"no /proc entry ({e.strerror})"
    return f"state {state}, parent {parent}, group {group}"


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


@pytest.mark.skipif(os.geteuid() == 0, reason="root searches any directory")
def test_missing_command_behind_an_unsearchable_path_dir_is_not_found(tmp_path: Path) -> None:
    # exec reports EACCES, not ENOENT, when a PATH directory cannot be searched, as on WSL.
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o000)
    try:
        with mock.patch.dict(os.environ, {"PATH": os.pathsep.join([str(locked), str(tmp_path)])}):
            with pytest.raises(CommandNotFoundError, match="command not found: no-such-command"):
                SubprocessRunner().run(["no-such-command"])
            script = tmp_path / "not-executable"
            script.write_text("#!/bin/sh\n")
            with pytest.raises(CommandNotFoundError, match="command not executable: not-executable"):
                SubprocessRunner().run(["not-executable"])
        # Relative and empty PATH entries resolve against the child's cwd, as exec resolves them.
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "relative-tool").write_text("#!/bin/sh\n")
        (tmp_path / "cwd-tool").write_text("#!/bin/sh\n")
        with mock.patch.dict(os.environ, {"PATH": os.pathsep.join([str(locked), "bin", ""])}):
            for name in ("relative-tool", "cwd-tool"):
                with pytest.raises(CommandNotFoundError, match=f"command not executable: {name}"):
                    SubprocessRunner().run([name], cwd=tmp_path)
    finally:
        locked.chmod(0o700)


def test_missing_cwd_is_not_reported_as_missing_command(agent_log: Path, tmp_path: Path) -> None:
    with pytest.raises(ProcError, match="working directory") as exc:
        SubprocessRunner().run(["agent"], cwd=tmp_path / "gone")
    assert not isinstance(exc.value, CommandNotFoundError)


def test_on_start_gets_the_pid_that_leads_the_group(agent_log: Path) -> None:
    started: list[int] = []
    assert SubprocessRunner().run(["agent"], on_start=started.append).ok
    [pid] = started
    assert pid != os.getpid()
    assert not procs.alive(pid)


def test_an_interrupted_run_kills_its_child_and_closes_its_pipes() -> None:
    """A Ctrl-C or SIGTERM mid-run reaches the caller, with the child's group killed and nothing left open."""
    pids: list[int] = []

    def interrupt(pid: int) -> None:
        pids.append(pid)
        raise KeyboardInterrupt

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(KeyboardInterrupt):
            SubprocessRunner().run(["sleep", "30"], on_start=interrupt)
        gc.collect()
    assert not procs.alive(pids[0])
    assert [str(w.message) for w in caught if issubclass(w.category, ResourceWarning)] == []


def test_on_line_gets_each_line_of_stdout_as_it_is_printed(tmp_path: Path) -> None:
    """The child waits for a file `on_line` makes on its first line: it ends only if lines arrive before it does."""
    flag = tmp_path / "flag"
    script = f"echo one; echo noise >&2; while [ ! -e {flag} ]; do sleep 0.01; done; printf 'two\\nthree'"
    seen: list[str] = []

    def on_line(line: str) -> None:
        seen.append(line)
        flag.touch()

    result = SubprocessRunner().run(["sh", "-c", script], timeout=10, on_line=on_line)
    assert result.ok
    assert seen == ["one\n", "two\n", "three"]
    assert (result.stdout, result.stderr) == ("one\ntwo\nthree", "noise\n")


def test_on_line_with_stdin_and_a_timeout(tmp_path: Path) -> None:
    seen: list[str] = []
    result = SubprocessRunner().run(["sh", "-c", "cat; sleep 30"], stdin="the diff\n", timeout=0.5, on_line=seen.append)
    assert result.timed_out
    assert not result.ok
    assert seen == ["the diff\n"]
    assert result.stdout == "the diff\n"


def test_an_on_line_that_raises_kills_the_child_and_closes_its_pipes() -> None:
    pids: list[int] = []

    def on_line(_line: str) -> None:
        raise KeyboardInterrupt

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(KeyboardInterrupt):
            SubprocessRunner().run(["sh", "-c", "echo hi; exec sleep 30"], on_start=pids.append, on_line=on_line)
        gc.collect()
    assert not procs.alive(pids[0])
    assert [str(w.message) for w in caught if issubclass(w.category, ResourceWarning)] == []


def test_spawn_detaches_and_logs(agent_log: Path, tmp_path: Path) -> None:
    log = tmp_path / "run.log"
    with mock.patch.dict(os.environ, {"FAKE_AGENT_RESULT": "spawned result"}):
        pid = SubprocessRunner().spawn(["agent", "x"], cwd=tmp_path, log_path=log)
    assert os.getpgid(pid) == pid  # its own session, so its own group
    deadline = time.monotonic() + 10
    while procs.alive(pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not procs.alive(pid)
    assert log.read_text().splitlines()[-1] == "spawned result"
    assert log.stat().st_mode & 0o777 == 0o600
    assert json.loads(agent_log.read_text())["cwd"] == str(tmp_path)


def test_spawn_missing_command(tmp_path: Path) -> None:
    with pytest.raises(CommandNotFoundError):
        SubprocessRunner().spawn([str(tmp_path / "nope")], cwd=tmp_path, log_path=tmp_path / "log")


def test_alive_and_kill_group(agent_log: Path, tmp_path: Path) -> None:
    assert procs.alive(os.getpid())
    assert not procs.alive(0)
    assert not procs.alive(4_194_305)
    assert not procs.kill_group(4_194_305)
    assert not procs.kill_group(1)
    with mock.patch.dict(os.environ, {"FAKE_AGENT_SLEEP": "30"}):
        pid = SubprocessRunner().spawn(["agent"], cwd=tmp_path, log_path=tmp_path / "log")
    assert procs.alive(pid)
    assert procs.kill_group(pid)
    deadline = time.monotonic() + 10
    while procs.alive(pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not procs.alive(pid)  # the zombie was reaped, not counted as alive


def test_alive_ignores_zombies_it_cannot_reap(agent_log: Path, tmp_path: Path) -> None:
    # A zombie that is not this process's child, as a killed `_run` leaves when nothing reaps it, reads as dead.
    script = tmp_path / "orphan"
    script.write_text("#!/bin/sh\nsleep 30 &\necho $!\nexec sleep 30\n")
    script.chmod(0o755)
    if not Path("/proc/self/stat").exists():
        pytest.skip("needs /proc")
    pid = SubprocessRunner().spawn([str(script)], cwd=tmp_path, log_path=tmp_path / "log")
    deadline = time.monotonic() + 10
    while not (tmp_path / "log").read_text().strip() and time.monotonic() < deadline:
        time.sleep(0.02)
    child = int((tmp_path / "log").read_text().split()[0])
    os.kill(child, signal.SIGKILL)  # a zombie until its parent, the script, waits; it never does
    while Path(f"/proc/{child}/stat").read_text().rpartition(")")[2].split()[0] != "Z":
        assert time.monotonic() < deadline
        time.sleep(0.02)
    assert not procs.alive(child)
    procs.kill_group(pid)


def test_a_spawned_child_holds_its_lifelock_until_it_exits(tmp_path: Path) -> None:
    log = tmp_path / "7.log"
    pid = SubprocessRunner().spawn(["sleep", "30"], cwd=tmp_path, log_path=log)
    assert procs.lifelock(log) == tmp_path / "7.lock"
    assert lock.held(procs.lifelock(log))
    assert procs.running(log, None)
    os.kill(pid, signal.SIGKILL)
    with contextlib.suppress(ChildProcessError):
        os.waitpid(pid, 0)
    # Released at exit, though the pid still names a process: this one.
    assert not procs.running(log, os.getpid())


def test_what_a_spawned_child_starts_does_not_hold_its_lifelock(tmp_path: Path) -> None:
    # As `_run` runs its worker: when `_run` dies and its worker lives on, the run reads as gone, so it is reconciled.
    log, pidfile = tmp_path / "7.log", tmp_path / "worker"
    script = (
        "from canopy.infra.procs import SubprocessRunner; "
        f"SubprocessRunner().run(['sh', '-c', 'echo $$ > {pidfile}.tmp && mv {pidfile}.tmp {pidfile}; exec sleep 30'])"
    )
    pid = SubprocessRunner().spawn([sys.executable, "-c", script], cwd=tmp_path, log_path=log)
    deadline = time.monotonic() + 10
    while not pidfile.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    worker = int(pidfile.read_text())
    try:
        os.kill(pid, signal.SIGKILL)
        with contextlib.suppress(ChildProcessError):
            os.waitpid(pid, 0)
        assert procs.alive(worker)
        assert not procs.running(log, None)
    finally:
        procs.kill_group(worker)


def test_spawn_refuses_while_another_process_holds_the_lifelock(tmp_path: Path) -> None:
    log = tmp_path / "7.log"
    held = lock.take(procs.lifelock(log))
    try:
        with pytest.raises(ProcError, match="held by another process"):
            SubprocessRunner().spawn(["sleep", "30"], cwd=tmp_path, log_path=log)
    finally:
        os.close(held)
    assert not lock.held(procs.lifelock(log))


def test_running_asks_after_the_pid_only_without_a_lifelock(tmp_path: Path) -> None:
    log = tmp_path / "7.log"
    # Started by a canopy from before lifelocks: the pid is all there is.
    assert procs.running(log, os.getpid())
    assert not procs.running(log, None)
    os.close(lock.take(procs.lifelock(log)))
    assert not procs.running(log, os.getpid())


def test_alive_reads_a_pid_reaped_after_the_signal_check_as_dead() -> None:
    # The window between `kill(pid, 0)` and reading /proc: a zombie's parent reaps it, and its /proc entry goes.
    if not Path("/proc/self/stat").exists():
        pytest.skip("needs /proc")
    result = SubprocessRunner().run(["sh", "-c", "echo $$"])
    reaped = int(result.stdout)
    # `kill(pid, 0)` says the pid is still there.
    with mock.patch.object(procs.os, "kill", autospec=True, return_value=None):
        assert not procs.alive(reaped)
