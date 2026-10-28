"""The one place the bench runs another program: git and gh, by argv, never through a shell."""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING, Final

from canopy_review_bench.bench import BenchError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

#: How long a command may run by default.
TIMEOUT_SECONDS: Final = 120
#: How much of a failed command's output its error quotes.
_QUOTED: Final = 600


def run(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    stdin: bytes | None = None,
    timeout: float = TIMEOUT_SECONDS,
) -> str:
    """Run `argv` and return what it printed on stdout.

    `env` is added to this process's environment, not put in its place.

    Returns:
        Its stdout, decoded as UTF-8, any byte that is not replaced.

    Raises:
        BenchError: it could not be run, ran past `timeout`, or exited other than 0.
    """
    try:
        done = subprocess.run(  # noqa: S603
            list(argv),
            cwd=cwd,
            env={**os.environ, **env} if env else None,
            input=stdin,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise BenchError(f"{' '.join(argv[:2])}: {e}") from e
    if done.returncode != 0:
        said = (done.stderr or done.stdout).decode("utf-8", "replace").strip()
        raise BenchError(f"{' '.join(argv[:3])} exited {done.returncode}: {said[:_QUOTED]}")
    return done.stdout.decode("utf-8", "replace")
