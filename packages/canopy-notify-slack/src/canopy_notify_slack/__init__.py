"""`canopy-notify-slack`: canopy's Slack sink (DESIGN §20). Posts each message it reads on stdin to an incoming webhook.

It reads canopy's `json` message format on stdin and posts one Slack message. The webhook URL comes from a file that
belongs to the operator and that nobody else can read, never from argv, the environment, or canopy's config:
`--webhook-file PATH`, by default `$XDG_CONFIG_HOME/canopy/slack-webhook`. Text from the journal, which agents and org
members wrote, is escaped for Slack's markup, so it cannot mention a person or `@channel`, or show one link and point at
another.

Exit codes: 0 posted (a 2xx reply); 1 the post failed, with Slack's reply on stderr; 2 the webhook file or the message
on stdin is not usable, saying which. canopy retries anything but 0 on its next tick.

Stdlib only, importing nothing from canopy: canopy runs it as a command, so the process that holds the journal and
enforces the guards never opens a connection or reads this secret (D035).
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path

SLACK_PREFIX = "https://hooks.slack.com/"
TIMEOUT_SECONDS = 30
_MAX_LINES = 45


class SinkError(Exception):
    """The sink cannot post: the webhook file or the message is not usable. Exit 2."""


def default_webhook_file() -> Path:
    """`$XDG_CONFIG_HOME/canopy/slack-webhook`, or `~/.config/canopy/slack-webhook`."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base).expanduser() / "canopy" / "slack-webhook"


def read_webhook(path: Path, *, prefix: str = SLACK_PREFIX) -> str:
    """Return the webhook URL in `path`, which must be the operator's, closed to others, and hold one Slack URL."""
    try:
        st = path.stat()
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise SinkError(f"cannot read the webhook file {path}: {e.strerror}") from e
    if not stat.S_ISREG(st.st_mode):
        raise SinkError(f"the webhook file {path} is not a regular file")
    if st.st_uid != os.getuid():
        raise SinkError(f"the webhook file {path} belongs to someone else; it must be yours")
    if st.st_mode & 0o077:
        raise SinkError(f"the webhook file {path} is readable by others; run: chmod 600 {path}")
    url = text.strip()
    if not url.startswith(prefix) or any(c.isspace() for c in url):
        raise SinkError(f"the webhook file {path} must hold one URL starting {prefix}")
    return url


def escape(text: object) -> str:
    """Escape Slack's markup characters, so text cannot mention anyone or disguise a link. Bare URLs stay clickable."""
    return " ".join(str(text).split()).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _subject(ticket: object, repo: object) -> str:
    if ticket is None:
        return str(repo or "-")
    return f"{ticket} ({repo})" if repo else str(ticket)


def _dicts(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [{str(k): v for k, v in item.items()} for item in value if isinstance(item, dict)]


def _lines(value: object) -> list[str]:
    return [str(line) for line in value] if isinstance(value, list) else []


def render(message: dict[str, object]) -> str:
    """Return the Slack text for one canopy `json` message: a header with counts, a line per item or event, a digest."""
    repo = Path(str(message.get("repo") or "")).name or "canopy"
    lines: list[str] = []
    counts: list[str] = []
    attention = message.get("attention")
    if isinstance(attention, dict):
        added = _dicts(attention.get("added"))
        resolved = _dicts(attention.get("resolved"))
        if added or resolved:
            counts.append(f"{len(added)} new, {len(resolved)} resolved, {attention.get('open', 0)} open")
        for a in added:
            what = escape(_subject(a.get("ticket"), a.get("repo")))
            lines.append(f"+ *{what}* {escape(a.get('reason'))}: {escape(a.get('detail'))}")
        lines += [f"- *{escape(_subject(r.get('ticket'), r.get('repo')))}* {escape(r.get('reason'))}" for r in resolved]
    events = _dicts(message.get("events"))
    if events:
        counts.append(f"{len(events)} event{'s' if len(events) != 1 else ''}")
    lines += [escape(e.get("line") or e.get("kind")) for e in events]
    omitted = message.get("omitted")
    if isinstance(omitted, int) and omitted:
        lines.append(f"_... and {omitted} more: see `canopy status`_")
    digest = message.get("digest")
    if isinstance(digest, dict):
        counts.append("digest")
        lines += ["", "*Digest*", *(escape(line) for line in _lines(digest.get("lines")))]
    if len(lines) > _MAX_LINES:
        lines = [*lines[: _MAX_LINES - 1], f"_... and {len(lines) - _MAX_LINES + 1} more lines_"]
    header = f"*canopy* · {escape(repo)}" + (f": {', '.join(counts)}" if counts else "")
    return "\n".join([header, *lines])


def post(url: str, text: str) -> tuple[bool, str]:
    """Post `text` to the webhook. Returns whether Slack accepted it, and its reply."""
    body = json.dumps({"text": text}).encode()
    # `read_webhook` checked the URL's scheme and host.
    headers = {"Content-Type": "application/json"}
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            return 200 <= response.status < 300, response.read().decode(errors="replace")[:500]  # noqa: PLR2004
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return False, f"cannot reach Slack: {e}"


def read_message(stdin: str) -> dict[str, object]:
    """Read canopy's `json` message format from `stdin`."""
    hint = 'set format = "json" for this sink'
    try:
        parsed: object = json.loads(stdin)
    except json.JSONDecodeError as e:
        raise SinkError(f"stdin is not a canopy json message: {e}; {hint}") from e
    if not isinstance(parsed, dict):
        raise SinkError(f"stdin is not a canopy json message; {hint}")
    return {str(k): v for k, v in parsed.items()}


def run(argv: list[str], stdin: str, *, prefix: str = SLACK_PREFIX) -> int:
    """Post the message on `stdin`. Returns the exit code. `prefix` is what the webhook URL must start with."""
    parser = argparse.ArgumentParser(prog="canopy-notify-slack", description=__doc__.split("\n", 1)[0])
    parser.add_argument("--webhook-file", type=Path, default=None, help="default: " + str(default_webhook_file()))
    args = parser.parse_args(argv)
    try:
        url = read_webhook(args.webhook_file or default_webhook_file(), prefix=prefix)
        parsed = read_message(stdin)
    except SinkError as e:
        print(f"canopy-notify-slack: {e}", file=sys.stderr)  # noqa: T201
        return 2
    ok, reply = post(url, render(parsed))
    if not ok:
        print(f"canopy-notify-slack: Slack refused the post: {reply}", file=sys.stderr)  # noqa: T201
        return 1
    return 0


def main() -> int:
    """The `canopy-notify-slack` command."""
    return run(sys.argv[1:], sys.stdin.read())
