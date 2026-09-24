"""The single subprocess boundary.

Every external process canopy runs (`treehouse`, `git`, the agent runtime, `notify`) goes through a `Runner`. Nothing
else in the package imports `subprocess`; ruff's banned-api rule enforces that. Code that needs to run a process takes
a `Runner` argument, so tests can pass a fake one.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


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
    ) -> Result:
        """Run `args` to completion and capture its output.

        Args:
            args: The command and its arguments. Never passed through a shell.
            cwd: Working directory for the child. Defaults to the current one.
            env: Entries merged over the inherited environment.
            stdin: Text written to the child's stdin. When None, stdin is `/dev/null`.
            timeout: Seconds before the child's process group is killed. None waits forever.
            on_start: Called with the child's pid, which is also its process group id, once it has started.

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
            cwd: Working directory for the child.
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
    ) -> Result:
        """Run `args` to completion and capture its output. See `Runner.run`."""
        argv = tuple(args)
        full_env = {**os.environ, **env} if env is not None else None
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
            if isinstance(e, PermissionError):
                raise CommandNotFoundError(f"command not executable: {argv[0]}") from e
            raise

        try:
            if on_start is not None:
                on_start(proc.pid)
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
        """Start `args` detached and return its pid. See `Runner.spawn`."""
        argv = tuple(args)
        fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        try:
            # stdin and stdout are never the caller's: a caller whose output is captured through a pipe (an overseer
            # running `canopy dispatch`) would otherwise wait for the detached child to close it.
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
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


def alive(pid: int) -> bool:
    """Return whether process `pid` exists and has not exited.

    A zombie counts as exited: it is reaped here if it is this process's own child, and recognized from `/proc` where
    there is one. A reused pid is not detected; a pid that belongs to some other process reads as alive.
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
