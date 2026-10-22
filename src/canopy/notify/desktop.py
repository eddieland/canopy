"""`canopy-notify-desktop`: the desktop sink (DESIGN §20). Shows each message as one desktop notification.

A sink is a command that reads one message on stdin. This one reads either format: a `json` message's `text` field, or
a `text` message as it is. It shows the message's lines, without the closing path line, through `notify-send` on Linux
and `osascript` on macOS, each given the title and body as separate arguments, never through a shell or a script built
from the text. It exits 0 when the notification was shown, 1 when the tool failed, and 2 when there is no tool or no
message.

It runs as its own process, its command line in canopy.cli.desktop, configured like any other sink:

    [notify.sinks.desktop]
    cmd = "canopy-notify-desktop"
    events = ["attention", "loop", "runs"]
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

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


def show(stdin: str, *, runner: procs.Runner, platform: str) -> int:
    """Show `stdin`, a message in either format, as a desktop notification through `runner`, as on `platform`.

    Returns:
        The exit code: 0 once shown; 1 if the notifier could not run or failed; 2 for an empty message or no notifier
        installed.
    """
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
