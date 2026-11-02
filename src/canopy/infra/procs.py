"""The single subprocess boundary.

Every external process canopy runs (`treehouse`, `git`, the agent runtime, `notify`) goes through a `Runner`. Nothing
else in the package imports `subprocess`; ruff's banned-api rule enforces that. Code that needs to run a process takes
a `Runner` argument, so tests can pass a fake one.
"""

from __future__ import annotations

import contextlib
import errno
import os
import queue
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, replace
from pathlib import Path
from typing import IO, Protocol, cast

from canopy.infra import lock, tracing

#: The variable a child started with a timeout finds its deadline in, as Unix seconds: the moment `run` kills it, taken
#: when its clock starts, so the two agree (DESIGN §33). A child started without a timeout gets none, not even one its
#: parent had: a deadline is for the process it was set for alone.
DEADLINE_ENV = "CANOPY_DEADLINE"


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
        stdout_to_file: bool = False,
    ) -> Result:
        """Run `args` to completion and capture its output.

        Args:
            args: The command and its arguments. Never passed through a shell.
            cwd: Working directory for the child. Defaults to the current one. When given, the child's `PWD` names
                it, overriding any `PWD` in `env`.
            env: Entries merged over the inherited environment.
            stdin: Text written to the child's stdin. When None, stdin is `/dev/null`.
            timeout: Seconds before the child's process group is killed. None waits forever. With one, the child's
                `DEADLINE_ENV` names when, whatever `env` or the inherited environment says; without, it has none.
            on_start: Called with the child's pid, which is also its process group id, once it has started.
            on_line: Called with each line of the child's stdout, its newline kept, as the child prints it, on the
                calling thread. `stdout` in the result holds the same lines. An exception it raises kills the child
                and propagates.
            stdout_to_file: Capture stdout through a temporary file rather than a pipe, read once the child exits, for
                a child that loses what it has not yet written to a full pipe when it exits. Not with `on_line`.

        Returns:
            The exit code and captured output. `timed_out` is set when `timeout` expired.

        Raises:
            CommandNotFoundError: The executable is missing or not executable.
            ProcError: The process could not be started, for example because `cwd` does not exist.
            ValueError: Both `on_line` and `stdout_to_file` were given.
        """
        ...

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:
        """Start `args` detached and return its pid without waiting.

        Args:
            args: The command and its arguments. Never passed through a shell.
            cwd: Working directory for the child, which its `PWD` also names. It gets no `DEADLINE_ENV`.
            log_path: File the child's stdout and stderr are appended to, created readable only by the operator.
                The child holds the lock beside it, `lifelock(log_path)`, for its whole life; `running` asks after it.

        Returns:
            The child's pid. The child leads its own session, so it outlives its parent and whatever process group
            the parent is in.

        Raises:
            CommandNotFoundError: The executable is missing or not executable.
            ProcError: The process could not be started, or another process holds its lifelock.
        """
        ...


class SubprocessRunner:
    """The real runner.

    Each child starts in its own session, so a timeout kills the whole process group. Agent runtimes spawn their own
    children; killing only the direct child would leave those running.
    """

    #: Variables removed from every child's environment, whatever the inherited one or a call's `env` holds.
    unset: AbstractSet[str] = frozenset()

    def __init__(self, *, unset: Iterable[str] = ()) -> None:
        """Remove `unset` from every child's environment."""
        self.unset = frozenset(unset)

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
        stdout_to_file: bool = False,
    ) -> Result:
        """Run `args` to completion and capture its output. See `Runner.run`.

        Returns:
            The exit code and captured output. `timed_out` is set when `timeout` expired.

        Raises:
            CommandNotFoundError: The executable is missing or not executable.
            ProcError: `cwd` cannot be used as the working directory, or the arguments are too long to start.
            OSError: The process could not be started for any other reason.
            ValueError: Both `on_line` and `stdout_to_file` were given.
        """
        if on_line is not None and stdout_to_file:
            raise ValueError("on_line reads stdout from a pipe, which stdout_to_file replaces")
        # Text, in the encoding and with the newlines `text=True` decodes a pipe with.
        with tempfile.TemporaryFile("w+") if stdout_to_file else contextlib.nullcontext() as out:
            result = self._run(
                tuple(args),
                cwd=cwd,
                env=env,
                stdin=stdin,
                timeout=timeout,
                on_start=on_start,
                on_line=on_line,
                out=out,
            )
            if out is None:
                return result
            out.seek(0)
            return replace(result, stdout=out.read())

    def _run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path | None,
        env: Mapping[str, str] | None,
        stdin: str | None,
        timeout: float | None,
        on_start: Callable[[int], None] | None,
        on_line: Callable[[str], None] | None,
        out: IO[str] | None,
    ) -> Result:
        """Run `argv` as `run` does, its stdout to `out` when given, where the result's `stdout` is then empty.

        Returns:
            The exit code and captured output.

        Raises:
            CommandNotFoundError: The executable is missing or not executable.
            ProcError: `cwd` cannot be used as the working directory.
            OSError: The process could not be started for any other reason.
        """
        # Taken as the clock `timeout` counts on starts, so the child's deadline is never later than its kill.
        deadline = None if timeout is None else time.time() + timeout
        full_env = _child_env(cwd, env, self.unset, deadline)
        try:
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
                env=full_env,
                stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE if out is None else out,
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
            # Linux holds one argument or variable to 128 KiB, and all of them to its ARG_MAX: a prompt placed in the
            # argv rather than on stdin can pass the first. Both sizes are named, since either may be the cause.
            if e.errno == errno.E2BIG:
                longest = max(len(os.fsencode(a)) for a in argv)
                environ = sum(len(os.fsencode(f"{k}={v}")) + 1 for k, v in (full_env or os.environ).items())
                raise ProcError(
                    f"arguments and environment too long to start {argv[0]}: its longest argument is {longest:,} "
                    f"bytes, its environment {environ:,}",
                ) from e
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
                return Result(argv, proc.returncode, stdout or "", stderr, timed_out=True)
            except BaseException:
                _kill_group(proc.pid)
                proc.wait()
                raise
        return Result(argv, proc.returncode, stdout or "", stderr)

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:
        """Start `args` detached and return its pid. See `Runner.spawn`.

        Returns:
            The child's pid. The child leads its own session.

        Raises:
            CommandNotFoundError: The executable is missing.
            ProcError: The process could not be started, or another process holds its lifelock.
        """
        argv = tuple(args)
        try:
            # Taken before the child exists and passed to it, so the lock is held from before its pid is recorded.
            # The child's own children do not inherit it: `run` and `spawn` close every fd they do not pass.
            held = lock.take(lifelock(log_path))
        except lock.LockBusyError as e:
            raise ProcError(f"cannot start {argv[0]}: {e}") from e
        try:
            fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        except BaseException:
            drop_lifelock(log_path)
            os.close(held)
            raise
        env = _child_env(cwd, None, self.unset, None)
        try:
            # stdin and stdout are never the caller's: a caller whose output is captured through a pipe would
            # otherwise wait for the detached child to close it.
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=fd,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                pass_fds=(held,),
            )
        except FileNotFoundError as e:
            drop_lifelock(log_path)
            raise CommandNotFoundError(f"command not found: {argv[0]}") from e
        except OSError as e:
            drop_lifelock(log_path)
            raise ProcError(f"cannot start {argv[0]}: {e.strerror}") from e
        except ProcError:
            drop_lifelock(log_path)
            raise
        finally:
            # The child's copy of `held` keeps the lock; a child that never started leaves it free.
            os.close(fd)
            os.close(held)
        # The child is detached on purpose. Popen reaps it later if it exits while this process still runs.
        return proc.pid


def _child_env(
    cwd: Path | None,
    env: Mapping[str, str] | None,
    unset: AbstractSet[str],
    deadline: float | None,
) -> dict[str, str] | None:
    """Return the child's environment: the inherited one, `env` merged over it, `unset` removed; None to inherit it.

    A child given a working directory gets `PWD` naming it, as a shell's `cd` would, whatever `env` says. Some programs
    trust `PWD` over the real working directory: OpenCode runs its tools in `PWD`, so an inherited one would put a
    worker's edits in the directory canopy was started from instead of its worktree.

    A child with a `deadline` gets `DEADLINE_ENV` naming it, in whole seconds, rounded down so it is never late; one
    without gets none, so a process canopy starts from inside an agent run does not take the run's deadline as its own.

    While tracing is on, the child gets the current span as `TRACEPARENT`, so a canopy process it is continues the trace
    (`tracing.carrier`).
    """
    traced = tracing.carrier()
    inherited = cwd is None and env is None and not unset and deadline is None
    if inherited and not traced and DEADLINE_ENV not in os.environ:
        return None
    merged = {**os.environ, **traced, **(env or {})}
    merged.pop(DEADLINE_ENV, None)
    if deadline is not None:
        merged[DEADLINE_ENV] = str(int(deadline))
    if cwd is not None:
        merged["PWD"] = str(cwd.absolute())
    return {name: value for name, value in merged.items() if name not in unset}


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


def lifelock(log_path: Path) -> Path:
    """Return the lock a child `spawn` started with `log_path` holds for its whole life: the log's path, `.lock`."""
    return log_path.with_suffix(".lock")


def drop_lifelock(log_path: Path) -> None:
    """Remove the lifelock of the run logging to `log_path`, so the file does not outlive the run.

    Only once the run's row is closed, or its process never started: nothing asks whether it is `running` then. A row
    still `running` with no lock file is asked after by its pid, which may since name another process. Removing the
    file does not release the lock; its holder's exit does. A file that cannot be removed is left, as it does no harm.
    """
    with contextlib.suppress(OSError):
        lifelock(log_path).unlink()


def running(log_path: Path, pid: int | None) -> bool:
    """Return whether the child `spawn` started with `log_path` is still running: whether its lifelock is held.

    The lock goes when the process exits, before it is a zombie, and names no pid that could be reused. A process an
    earlier canopy started holds none, and reads as running while its `pid`, if recorded, is `alive`.
    """
    path = lifelock(log_path)
    if path.exists():
        return lock.held(path)
    return pid is not None and alive(pid)


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
    except (OSError, IndexError) as e:
        # A zombie whose parent reaped it since the signal check has no entry left, where there is a /proc to have one.
        return not (isinstance(e, FileNotFoundError) and Path("/proc/self/stat").exists())
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
