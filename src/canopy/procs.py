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
from collections.abc import Mapping, Sequence
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
        return self.returncode == 0 and not self.timed_out


class Runner(Protocol):
    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        timeout: float | None = None,
    ) -> Result:
        """Run `args` to completion and capture its output.

        `env` entries are merged over the inherited environment. `timeout` is in seconds.
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
    ) -> Result:
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
        except FileNotFoundError as e:
            raise CommandNotFoundError(f"command not found: {argv[0]}") from e
        except PermissionError as e:
            raise CommandNotFoundError(f"command not executable: {argv[0]}") from e

        try:
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


def _kill_group(pgid: int) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pgid, signal.SIGKILL)
