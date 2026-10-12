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

In a release's single executable (D067), run a sink with `SCIE_BOOT` set to its name; `RELEASE_HELP`, below, which
`--help` prints, has a wrapper script for `PATH`.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import TextIO

from canopy.infra import procs

RELEASE_HELP = """\
In a release's single executable, run this sink with SCIE_BOOT set to its name: SCIE_BOOT=canopy-notify-desktop
/path/to/canopy. A link named canopy-notify-desktop can run canopy itself instead. So that a sink's cmd can name
canopy-notify-desktop, put this script on PATH under that name, with the path to your canopy, and make it executable:

    #!/bin/sh
    exec env SCIE_BOOT=canopy-notify-desktop /path/to/canopy "$@"
"""
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


def run(argv: list[str], stdin: TextIO, *, runner: procs.Runner, platform: str) -> int:
    """Show the message on `stdin` as a desktop notification. Returns the exit code."""
    parser = argparse.ArgumentParser(
        prog="canopy-notify-desktop",
        description=__doc__.split("\n", 1)[0],
        epilog=RELEASE_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Arguments first: `--help` must not wait for a message on stdin.
    parser.parse_args(argv)
    title, body = message(stdin.read())
    if not body:
        print("canopy-notify-desktop: no message on stdin", file=sys.stderr)  # noqa: T201
        return 2
    argv_ = command(title, body, platform)
    if argv_ is None:
        tool = "osascript" if platform == "darwin" else "notify-send"
        print(f"canopy-notify-desktop: {tool} is not installed", file=sys.stderr)  # noqa: T201
        return 2
    try:
        result = runner.run(argv_, timeout=_TIMEOUT_SECONDS)
    except procs.ProcError as e:
        print(f"canopy-notify-desktop: {e}", file=sys.stderr)  # noqa: T201
        return 1
    if not result.ok:
        print(f"canopy-notify-desktop: {argv_[0]} failed: {result.stderr.strip()[-500:]}", file=sys.stderr)  # noqa: T201
        return 1
    return 0


def main() -> int:
    """The `canopy-notify-desktop` command."""
    return run(sys.argv[1:], sys.stdin, runner=procs.SubprocessRunner(), platform=sys.platform)
