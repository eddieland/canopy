"""`canopy-notify-desktop`: the desktop sink (DESIGN §20). Shows each message as one desktop notification.

A sink is a command that reads one message on stdin. This one reads either format: a `json` message's `text` field, or
a `text` message as it is. It shows the message's lines, without the closing path line, through `notify-send` on Linux
and `osascript` on macOS, each given the title and body as separate arguments, never through a shell or a script built
from the text. It exits 0 when the notification was shown, 1 when the tool failed, and 2 when there is no tool or no
message.

It runs as its own process, configured like any other sink:

    [notify.sinks.desktop]
    cmd = "canopy-notify-desktop"
    events = ["attention", "loop", "runs"]
"""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

import click

from canopy.infra import procs

TITLE = "canopy"
MAX_LINES = 12
MAX_BODY = 1000
_TIMEOUT_SECONDS = 20
# AppleScript reads the title and body from its arguments, so neither is ever parsed as script.
_OSASCRIPT = [
    "osascript",
    "-e",
    "on run argv",
    "-e",
    "display notification (item 2 of argv) with title (item 1 of argv)",
    "-e",
    "end run",
]


def message(stdin: str) -> tuple[str, str]:
    """Return the notification's title and body for a message in either format."""
    title = TITLE
    text = stdin
    try:
        parsed: object = json.loads(stdin)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        found: object = parsed.get("text")
        text = str(found) if found else ""
        repo: object = parsed.get("repo")
        if repo:
            title = f"{TITLE}: {Path(str(repo)).name}"
    lines = [line for line in text.splitlines() if line.strip() and not line.startswith("Full list: ")]
    if len(lines) > MAX_LINES:
        lines = [*lines[: MAX_LINES - 1], f"... and {len(lines) - MAX_LINES + 1} more lines"]
    body = "\n".join(lines)
    if len(body) > MAX_BODY:
        body = body[: MAX_BODY - 3] + "..."
    return title, body


def command(title: str, body: str, platform: str) -> list[str] | None:
    """Return the argv that shows the notification on `platform`, or None if its tool is not installed."""
    if platform == "darwin":
        return [*_OSASCRIPT, title, body] if shutil.which("osascript") else None
    if shutil.which("notify-send"):
        return ["notify-send", "--app-name=canopy", "--", title, body]
    return None


def run(argv: Sequence[str], stdin: TextIO, *, runner: procs.Runner, platform: str) -> int:
    """Show the message on `stdin` as a desktop notification.

    Returns:
        The exit code: 0 once shown; 1 if the notifier could not run or failed; 2 for a command line it cannot use, an
        empty message, or no notifier installed.
    """
    try:
        found = cli.main(
            args=list(argv),
            prog_name="canopy-notify-desktop",
            standalone_mode=False,
            obj=_Io(stdin, runner, platform),
        )
    except click.ClickException as e:
        e.show()
        return e.exit_code
    return found if isinstance(found, int) else 0


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Show the canopy message on stdin as a desktop notification: canopy's desktop sink (DESIGN §20)."""
    io = ctx.find_object(_Io) or _Io(sys.stdin, procs.SubprocessRunner(), sys.platform)
    ctx.exit(_show(io.stdin.read(), io.runner, io.platform))


def main() -> int:
    """The `canopy-notify-desktop` command.

    Returns:
        The process exit code, as `run` returns it.
    """
    return run(sys.argv[1:], sys.stdin, runner=procs.SubprocessRunner(), platform=sys.platform)


@dataclass(frozen=True)
class _Io:
    """What the sink reads, and how it runs the notifier: the real ones, unless a test gives its own."""

    stdin: TextIO
    runner: procs.Runner
    #: `sys.platform`'s value: `darwin` runs `osascript`, any other `notify-send`.
    platform: str


def _show(stdin: str, runner: procs.Runner, platform: str) -> int:
    title, body = message(stdin)
    if not body:
        print("canopy-notify-desktop: no message on stdin", file=sys.stderr)  # noqa: T201
        return 2
    argv = command(title, body, platform)
    if argv is None:
        tool = "osascript" if platform == "darwin" else "notify-send"
        print(f"canopy-notify-desktop: {tool} is not installed", file=sys.stderr)  # noqa: T201
        return 2
    try:
        result = runner.run(argv, timeout=_TIMEOUT_SECONDS)
    except procs.ProcError as e:
        print(f"canopy-notify-desktop: {e}", file=sys.stderr)  # noqa: T201
        return 1
    if not result.ok:
        print(f"canopy-notify-desktop: {argv[0]} failed: {result.stderr.strip()[-500:]}", file=sys.stderr)  # noqa: T201
        return 1
    return 0
