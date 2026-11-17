"""A private OpenCode 2 server canopy asks its questions of (DESIGN §13), started for them and stopped after.

OpenCode 2 has no command that prints what it has loaded reliably: its debug commands attach to the shared background
service, and a private server started for one command, `--standalone`, answers before its plugins have loaded, with
no agent or skill of canopy's, and with the models of its catalog where a provider's plugin lists its own. So canopy
starts `opencode serve` itself, on a port of the system's choosing, with a password of its own, asks it through
`opencode api --server` until it has loaded what the question is about, and stops it.

What an answer holds may be a secret, a provider's key or a server's token, so no failure quotes what was printed.
"""

from __future__ import annotations

import re
import secrets
from typing import TYPE_CHECKING

from pydantic import ValidationError

from canopy.infra import procs

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

#: How long the server may take to say where it listens, and to answer every question once it has.
TIMEOUT_SECONDS = 120
#: How long one question of the server may take.
ASK_SECONDS = 30
#: The variable a server takes its password from, and a client the password it sends.
PASSWORD_ENV = "OPENCODE_PASSWORD"  # noqa: S105 - a variable's name, not a password
#: The words that start OpenCode, as canopy's own questions run it.
OPENCODE = ("opencode",)
# Where the server says it listens.
LISTENING_RE = re.compile(r"server listening on (http://127\.0\.0\.1:\d{1,5})\b")


class FailedError(Exception):
    """The server could not be started, asked, or understood."""


class Serve:
    """`opencode serve`, started with `launcher` in `cwd` with `env` and a password of its own, for one function."""

    def __init__(self, runner: procs.Runner, launcher: Sequence[str], cwd: Path, env: Mapping[str, str]) -> None:
        """Take what starts the server; nothing runs until `ask`."""
        self.runner = runner
        self.launcher = tuple(launcher)
        self.cwd = cwd
        self.env = {**env, PASSWORD_ENV: secrets.token_urlsafe(24)}

    def ask[T](self, questions: Callable[[Client], T]) -> T:
        """Start the server, put `questions` to it once it listens, and stop it.

        Returns:
            What `questions` returned.

        Raises:
            FailedError: The server could not start, or exited or timed out before it listened, or `questions` did.
        """
        argv = [*self.launcher, "serve", "--hostname", "127.0.0.1", "--port", "0"]
        answers: list[T] = []

        def listening(line: str) -> None:
            found = LISTENING_RE.search(line)
            if found is None:
                return
            answers.append(questions(Client(self, found[1])))
            # Raised from here, it stops the server.
            raise _Answered

        try:
            result = self.runner.run(argv, cwd=self.cwd, env=self.env, timeout=TIMEOUT_SECONDS, on_line=listening)
        except _Answered:
            return answers[0]
        except procs.CommandNotFoundError:
            raise FailedError(f"{self.launcher[0]} is not on PATH") from None
        except procs.ProcError as e:
            raise FailedError(f"`opencode serve` could not start: {e}") from None
        if result.timed_out:
            raise FailedError(f"`opencode serve` did not listen within {TIMEOUT_SECONDS} seconds")
        raise FailedError(f"`opencode serve` exited {result.returncode}; run it to see why")


class _Answered(Exception):  # noqa: N818 - it is no error: it ends the server once the questions are answered.
    """The questions were answered, so the server may stop."""


class Client:
    """`opencode api --server`, asking the server at `url` with the server's own launcher and environment."""

    def __init__(self, server: Serve, url: str) -> None:
        """Take the server to ask and where it listens."""
        self.server = server
        self.url = url

    def get(self, operation: str) -> str:
        """Return what operation `operation` answered.

        Raises:
            FailedError: It could not start, timed out, or failed.
        """
        server = self.server
        argv = [*server.launcher, "api", "--server", self.url, operation]
        try:
            # Through a file, not a pipe: OpenCode exits having written only what a pipe's buffer holds, 64 KiB.
            result = server.runner.run(argv, cwd=server.cwd, env=server.env, timeout=ASK_SECONDS, stdout_to_file=True)
        except procs.ProcError as e:
            raise FailedError(f"`opencode api {operation}` could not start: {e}") from None
        if result.timed_out:
            raise FailedError(f"`opencode api {operation}` took over {ASK_SECONDS} seconds")
        if not result.ok:
            # Not what it printed: an error about the config may quote a value of it, and an agent reads this.
            raise FailedError(f"`opencode api {operation}` exited {result.returncode}")
        return result.stdout


def read[T](printed: str, validate: Callable[[str], T], operation: str) -> T:
    """Read `printed`, what `operation` answered, with `validate`.

    Returns:
        What `validate` made of it.

    Raises:
        FailedError: `validate` could not read it.
    """
    try:
        return validate(printed)
    except (ValidationError, ValueError, TypeError):
        # Not the error itself: it quotes what was printed, which for the config may hold a secret.
        raise FailedError(f"`opencode api {operation}` printed what canopy cannot read") from None
