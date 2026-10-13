"""The single subprocess boundary.

Every external process canopy runs (`treehouse`, `git`, the agent runtime, `notify`) goes through a `Runner`. Nothing
else in the package imports `subprocess`; ruff's banned-api rule enforces that. Code that needs to run a process takes
a `Runner` argument, so tests can pass a fake one.
"""

from __future__ import annotations

import contextlib
import os
import queue
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Protocol, cast


class ProcError(Exception):
    """A process could not be started at all."""


class CommandNotFoundError(ProcError):
    """The executable is not on PATH or not executable."""


@dataclass(frozen=True)
class Result:
    """What came back from one process run.

    `timed_out` is True when the run hit its timeout and was killed. `returncode` is then the kill signal as a negative
    number, and `stdout` and `stderr` hold whatever was written before the kill.
    """

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        """Whether the process exited 0 without timing out."""
        return self.returncode == 0 and not self.timed_out


class Runner(Protocol):
    """Runs external processes. `SubprocessRunner` is the real one; tests pass fakes."""

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
    ) -> Result:
        """Run `args` to completion and capture its output.

        Args:
            args: The command and its arguments. Never passed through a shell.
            cwd: Working directory for the child. Defaults to the current one. When given, the child's `PWD` names
                it, overriding any `PWD` in `env`.
            env: Entries merged over the inherited environment.
            stdin: Text written to the child's stdin. When None, stdin is `/dev/null`.
            timeout: Seconds before the child's process group is killed. None waits forever.
            on_start: Called with the child's pid, which is also its process group id, once it has started.
            on_line: Called with each line of the child's stdout, its newline kept, as the child prints it, on the
                calling thread. `stdout` in the result holds the same lines. An exception it raises kills the child
                and propagates.

        Returns:
            The exit code and captured output. `timed_out` is set when `timeout` expired.

        Raises:
            CommandNotFoundError: The executable is missing or not executable.
            ProcError: The process could not be started, for example because `cwd` does not exist.
        """
        ...

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:
        """Start `args` detached and return its pid without waiting.

        Args:
            args: The command and its arguments. Never passed through a shell.
            cwd: Working directory for the child, which its `PWD` also names.
            log_path: File the child's stdout and stderr are appended to, created readable only by the operator.

        Returns:
            The child's pid. The child leads its own session, so it outlives its parent and whatever process group
            the parent is in.

        Raises:
            CommandNotFoundError: The executable is missing or not executable.
            ProcError: The process could not be started.
        """
        ...


class SubprocessRunner:
    """The real runner.

    Each child starts in its own session, so a timeout kills the whole process group. Agent runtimes spawn their own
    children; killing only the direct child would leave those running.
    """

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
    ) -> Result:
        """Run `args` to completion and capture its output. See `Runner.run`.

        Returns:
            The exit code and captured output. `timed_out` is set when `timeout` expired.

        Raises:
            CommandNotFoundError: The executable is missing or not executable.
            ProcError: `cwd` cannot be used as the working directory.
            OSError: The process could not be started for any other reason.
        """
        argv = tuple(args)
        full_env = _child_env(cwd, env)
        try:
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
                env=full_env,
                stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except OSError as e:
            # A bad cwd raises the same exception types as a bad executable; `filename` says which one failed.
            if cwd is not None and e.filename is not None and os.fspath(e.filename) == os.fspath(cwd):
                raise ProcError(f"cannot use working directory {cwd}: {e.strerror}") from e
            if isinstance(e, FileNotFoundError):
                raise CommandNotFoundError(f"command not found: {argv[0]}") from e
            # exec reports EACCES for a missing command when some PATH directory cannot be searched, as WSL's
            # Windows directories often cannot. Only a command that exists is "not executable".
            if isinstance(e, PermissionError):
                reason = "not executable" if _exists(argv[0], cwd=cwd, env=full_env) else "not found"
                raise CommandNotFoundError(f"command {reason}: {argv[0]}") from e
            raise

        # Leaving the block closes the pipes, which communicate() leaves open when a signal interrupts it.
        with proc:
            try:
                if on_start is not None:
                    on_start(proc.pid)
                if on_line is not None:
                    return _stream(proc, argv, stdin, timeout, on_line)
                stdout, stderr = proc.communicate(stdin, timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_group(proc.pid)
                stdout, stderr = proc.communicate()
                return Result(argv, proc.returncode, stdout, stderr, timed_out=True)
            except BaseException:
                _kill_group(proc.pid)
                proc.wait()
                raise
        return Result(argv, proc.returncode, stdout, stderr)

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:
        """Start `args` detached and return its pid. See `Runner.spawn`.

        Returns:
            The child's pid. The child leads its own session.

        Raises:
            CommandNotFoundError: The executable is missing.
            ProcError: The process could not be started.
        """
        argv = tuple(args)
        fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        try:
            # stdin and stdout are never the caller's: a caller whose output is captured through a pipe (an overseer
            # running `canopy dispatch`) would otherwise wait for the detached child to close it.
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
                env=_child_env(cwd, None),
                stdin=subprocess.DEVNULL,
                stdout=fd,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except FileNotFoundError as e:
            raise CommandNotFoundError(f"command not found: {argv[0]}") from e
        except OSError as e:
            raise ProcError(f"cannot start {argv[0]}: {e.strerror}") from e
        finally:
            os.close(fd)
        # The child is detached on purpose. Popen reaps it later if it exits while this process still runs.
        return proc.pid


def _child_env(cwd: Path | None, env: Mapping[str, str] | None) -> dict[str, str] | None:
    """Return the child's environment: the inherited one with `env` merged over it, or None to inherit it unchanged.

    A child given a working directory gets `PWD` naming it, as a shell's `cd` would, whatever `env` says. Some programs
    trust `PWD` over the real working directory: OpenCode runs its tools in `PWD`, so an inherited one would put a
    worker's edits in the directory canopy was started from instead of its worktree.
    """
    if cwd is None:
        return {**os.environ, **env} if env is not None else None
    return {**os.environ, **(env or {}), "PWD": str(cwd.absolute())}


def _exists(command: str, *, cwd: Path | None, env: Mapping[str, str] | None) -> bool:
    """Whether `command` names a file, looked up the way exec looks it up: as a path, or in each PATH directory.

    Returns:
        True when a regular file is found. A directory that cannot be searched counts as not having it.
    """
    # The child changes into `cwd` before exec, so a relative or empty PATH entry, like a relative command, resolves
    # against it. An absolute entry replaces `cwd` in the join.
    base = Path(cwd or ".")
    dirs = [""] if os.sep in command else os.get_exec_path(env)
    candidates = [base / d / command for d in dirs]
    for candidate in candidates:
        # The directories that make exec report EACCES make this raise it too.
        with contextlib.suppress(OSError):
            if candidate.is_file():
                return True
    return False


def _stream(
    proc: subprocess.Popen[str],
    argv: tuple[str, ...],
    stdin: str | None,
    timeout: float | None,
    on_line: Callable[[str], None],
) -> Result:
    """What `communicate` does, but each line of stdout goes to `on_line`, on this thread, as the child prints it.

    Threads read the pipes and write stdin, so a child that fills one pipe while canopy waits on another never blocks.
    Only this thread calls `on_line`, so it may use what this thread owns, such as a journal connection.

    Returns:
        The exit code and captured output, `timed_out` set when `timeout` expired and the child's group was killed.
    """
    # `run` opened both as pipes.
    out, err = cast("IO[str]", proc.stdout), cast("IO[str]", proc.stderr)
    lines: queue.SimpleQueue[str | None] = queue.SimpleQueue()
    stderr: list[str] = []
    stderr_reader = threading.Thread(target=_read_all, args=(err, stderr), daemon=True)
    workers = [threading.Thread(target=_read_lines, args=(out, lines), daemon=True), stderr_reader]
    if stdin is not None:
        workers.append(threading.Thread(target=_write_all, args=(proc.stdin, stdin), daemon=True))
    for worker in workers:
        worker.start()
    deadline = _Deadline(proc.pid, timeout)
    try:
        stdout = _pump(lines, on_line, deadline)
        stderr_reader.join(deadline.left())
        if stderr_reader.is_alive():
            deadline.expire()
        try:
            proc.wait(deadline.left())
        except subprocess.TimeoutExpired:
            deadline.expire()
            proc.wait()
    except BaseException:
        _kill_group(proc.pid)
        raise
    finally:
        # The readers stop at the pipes' end, which the child's exit or a kill brings, before `run` closes the pipes.
        for worker in workers:
            worker.join()
    return Result(argv, proc.returncode, "".join(stdout), "".join(stderr), timed_out=deadline.expired)


class _Deadline:
    """When a timeout expires, and whether it did: expiring kills the child's group, and leaves no deadline after."""

    def __init__(self, pgid: int, timeout: float | None) -> None:
        self.pgid = pgid
        self.at = None if timeout is None else time.monotonic() + timeout
        self.expired = False

    def left(self) -> float | None:
        return None if self.at is None else max(0.0, self.at - time.monotonic())

    def expire(self) -> None:
        _kill_group(self.pgid)
        self.expired = True
        self.at = None


def _pump(lines: queue.SimpleQueue[str | None], on_line: Callable[[str], None], deadline: _Deadline) -> list[str]:
    stdout: list[str] = []
    while True:
        try:
            line = lines.get(timeout=deadline.left())
        except queue.Empty:
            # What the group printed before the kill is still read, and still passed on.
            deadline.expire()
            continue
        if line is None:
            return stdout
        stdout.append(line)
        on_line(line)


def _read_lines(pipe: IO[str], lines: queue.SimpleQueue[str | None]) -> None:
    for line in pipe:
        lines.put(line)
    lines.put(None)


def _read_all(pipe: IO[str], into: list[str]) -> None:
    into.append(pipe.read())


def _write_all(pipe: IO[str], text: str) -> None:
    # A child need not read all of its stdin, as `communicate` allows.
    with contextlib.suppress(BrokenPipeError):
        pipe.write(text)
    with contextlib.suppress(BrokenPipeError):
        pipe.close()


def alive(pid: int) -> bool:
    """Return whether process `pid` exists and has not exited.

    A zombie counts as exited: it is reaped here if it is this process's own child, and recognized from `/proc` where
    there is one. A reused pid is not detected; a pid that belongs to some other process reads as alive.

    Returns:
        True when the process exists and is not a zombie, or when its state cannot be read. False otherwise.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # it exists, owned by someone else
    with contextlib.suppress(ChildProcessError):
        reaped, _ = os.waitpid(pid, os.WNOHANG)
        if reaped == pid:
            return False
    stat = Path(f"/proc/{pid}/stat")
    try:
        # The state is the field after the parenthesized command name, which may itself contain spaces or ")".
        state = stat.read_text().rpartition(")")[2].split()[0]
    except (OSError, IndexError):
        return True
    return state not in ("Z", "X")


def kill_group(pgid: int) -> bool:
    """SIGKILL process group `pgid`, if any process is still in it. Returns whether one was.

    Every child `SubprocessRunner` starts leads its own group, so its pid is the group id. A pid is not reused while a
    group of that id has members, so this reaches only what is left of that child and its descendants, unless the whole
    group has already exited and the pid has since gone to a new group leader.

    Returns:
        True when the signal was sent. False when the group had no process left, or `pgid` is 0 or 1.
    """
    if pgid <= 1:
        return False
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return False
    return True


def _kill_group(pgid: int) -> None:
    kill_group(pgid)
