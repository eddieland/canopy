"""`canopy-notify-slack`: canopy's Slack sink (DESIGN §20). Posts each message it reads on stdin to a Slack channel.

It reads canopy's `json` message format on stdin and posts one Slack message, to an incoming webhook or, given
`--channel`, with a bot token through `chat.postMessage`, optionally under its own `--username` and `--icon-emoji`.
The secret comes from a file that belongs to the operator and
that nobody else can read, never from argv, the environment, or canopy's config: `--webhook-file PATH`, by default
`$XDG_CONFIG_HOME/canopy/slack-webhook`, or `--token-file PATH`, by default `$XDG_CONFIG_HOME/canopy/slack-token`.
Text from the journal, which agents and org members wrote, is escaped for Slack's markup, so it cannot mention a person
or `@channel`, or show one link and point at another.

Exit codes: 0 posted (a 2xx reply, and `"ok": true` from the Web API); 1 the post failed, with Slack's reply on
stderr; 2 the secret file, the channel, or the message on stdin is not usable, saying which. canopy retries anything
but 0 on its next tick.

Stdlib only, importing nothing from canopy: canopy runs it as a command, so the process that holds the journal and
enforces the guards never opens a connection or reads this secret (D035).
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

SLACK_PREFIX = "https://hooks.slack.com/"
SLACK_API_URL = "https://slack.com/api/chat.postMessage"
# A bot token: a user token (`xoxp-`) acts as the operator, with every scope they granted it.
TOKEN_PREFIX = "xoxb-"  # noqa: S105
TIMEOUT_SECONDS = 30
_MAX_LINES = 45
# A channel id (`C0123ABCD`) or a name (`#canopy`, `canopy`).
_CHANNEL = re.compile(r"#?[A-Za-z0-9._-]{1,80}")
# An emoji code (`:robot_face:`), with an optional skin tone (`:wave::skin-tone-3:`).
_EMOJI = re.compile(r"(?::[a-z0-9_+'-]{1,100}:){1,2}")
_MAX_USERNAME = 80


class SinkError(Exception):
    """The sink cannot post: the secret file, the channel, or the message is not usable. Exit 2."""


def _config_file(name: str) -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base).expanduser() / "canopy" / name


def default_webhook_file() -> Path:
    """`$XDG_CONFIG_HOME/canopy/slack-webhook`, or `~/.config/canopy/slack-webhook`."""
    return _config_file("slack-webhook")


def default_token_file() -> Path:
    """`$XDG_CONFIG_HOME/canopy/slack-token`, or `~/.config/canopy/slack-token`."""
    return _config_file("slack-token")


def _read_secret(path: Path, what: str) -> str:
    """Return the stripped text of `path`, which must be a regular file of the operator's, closed to others."""
    try:
        st = path.stat()
    except OSError as e:
        raise SinkError(f"cannot read the {what} file {path}: {e.strerror}") from e
    # Checked before reading: opening a FIFO would block.
    if not stat.S_ISREG(st.st_mode):
        raise SinkError(f"the {what} file {path} is not a regular file")
    if st.st_uid != os.getuid():
        raise SinkError(f"the {what} file {path} belongs to someone else; it must be yours")
    if st.st_mode & 0o077:
        raise SinkError(f"the {what} file {path} is readable by others; run: chmod 600 {path}")
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as e:
        raise SinkError(f"cannot read the {what} file {path}: {e}") from e


def read_webhook(path: Path, *, prefix: str = SLACK_PREFIX) -> str:
    """Return the webhook URL in `path`, which must be the operator's, closed to others, and hold one Slack URL."""
    url = _read_secret(path, "webhook")
    if not url.startswith(prefix) or any(c.isspace() for c in url) or not _same_origin(url, prefix):
        raise SinkError(f"the webhook file {path} must hold one URL starting {prefix}")
    return url


def read_token(path: Path) -> str:
    """Return the token in `path`, which must be the operator's, closed to others, and hold one Slack bot token."""
    token = _read_secret(path, "token")
    # The message never quotes the file's text: it is a secret.
    # ASCII, since it goes in a header.
    if (
        not token.startswith(TOKEN_PREFIX)
        or not token.isascii()
        or any(c.isspace() or not c.isprintable() for c in token)
    ):
        raise SinkError(f"the token file {path} must hold one Slack bot token starting {TOKEN_PREFIX}")
    return token


def check_channel(channel: str) -> str:
    """Return `channel` if it is a Slack channel id or name."""
    if not _CHANNEL.fullmatch(channel):
        raise SinkError(f"--channel {channel!r} is not a Slack channel id or name")
    return channel


def check_username(username: str) -> str:
    """Return `username` if it is a display name: printable, not blank, at most 80 characters."""
    if not username.strip() or not username.isprintable() or len(username) > _MAX_USERNAME:
        raise SinkError(f"--username {username!r} must be printable, not blank, and at most {_MAX_USERNAME} characters")
    return username


def check_icon_emoji(icon_emoji: str) -> str:
    """Return `icon_emoji` if it is an emoji code such as `:robot_face:`."""
    if not _EMOJI.fullmatch(icon_emoji):
        raise SinkError(f"--icon-emoji {icon_emoji!r} is not an emoji code such as :robot_face:")
    return icon_emoji


def _same_origin(url: str, prefix: str) -> bool:
    """Whether `url` parses to the scheme and host of `prefix`, with no user part: a prefix match cannot hide a host."""
    try:
        got, want = urllib.parse.urlsplit(url), urllib.parse.urlsplit(prefix)
        _ = got.port  # raises on a malformed port
    except ValueError:
        return False
    return (got.scheme, got.hostname, got.username) == (want.scheme, want.hostname, None)


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
    # The header is one of the at most `_MAX_LINES` lines.
    if len(lines) > _MAX_LINES - 1:
        lines = [*lines[: _MAX_LINES - 2], f"_... and {len(lines) - _MAX_LINES + 2} more lines_"]
    header = f"*canopy* · {escape(repo)}" + (f": {', '.join(counts)}" if counts else "")
    return "\n".join([header, *lines])


def post(url: str, text: str) -> tuple[bool, str]:
    """Post `text` to the webhook. Returns whether Slack accepted it, and its reply."""
    # `read_webhook` checked the URL's scheme and host.
    return _post(url, {"text": text}, {"Content-Type": "application/json"})


def post_message(
    api_url: str, token: str, channel: str, text: str, *, username: str | None = None, icon_emoji: str | None = None
) -> tuple[bool, str]:
    """Post `text` to `channel` with `chat.postMessage`, as `username` with `icon_emoji` when given.

    Returns whether Slack accepted it, and its reply.
    """
    headers = {"Content-Type": "application/json; charset=utf-8", "Authorization": f"Bearer {token}"}
    payload = {"channel": channel, "text": text}
    if username is not None:
        payload["username"] = username
    if icon_emoji is not None:
        payload["icon_emoji"] = icon_emoji
    ok, reply = _post(api_url, payload, headers)
    if not ok:
        return ok, reply
    # The Web API answers 200 to a refused post, with `"ok": false` and an `error` such as `not_in_channel`.
    try:
        parsed: object = json.loads(reply)
    except json.JSONDecodeError:
        return False, reply
    return isinstance(parsed, dict) and parsed.get("ok") is True, reply


def _post(url: str, payload: dict[str, str], headers: dict[str, str]) -> tuple[bool, str]:
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")  # noqa: S310
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


def run(argv: list[str], stdin: TextIO, *, prefix: str = SLACK_PREFIX, api_url: str = SLACK_API_URL) -> int:
    """Post the message on `stdin`. Returns the exit code.

    `prefix` is what the webhook URL must start with; `api_url` is where a token posts.
    """
    parser = argparse.ArgumentParser(prog="canopy-notify-slack", description=__doc__.split("\n", 1)[0])
    parser.add_argument("--webhook-file", type=Path, default=None, help="default: " + str(default_webhook_file()))
    parser.add_argument("--channel", default=None, help="post with a bot token to this channel id, not a webhook")
    parser.add_argument("--token-file", type=Path, default=None, help="default: " + str(default_token_file()))
    parser.add_argument("--username", default=None, help="with --channel, the name to post as")
    parser.add_argument(
        "--icon-emoji", default=None, help="with --channel, the emoji to post with, such as :robot_face:"
    )
    args = parser.parse_args(argv)
    for given, flag in (
        (args.token_file, "--token-file"),
        (args.username, "--username"),
        (args.icon_emoji, "--icon-emoji"),
    ):
        if args.channel is None and given is not None:
            parser.error(f"{flag} needs --channel")
    if args.channel is not None and args.webhook_file is not None:
        parser.error("--webhook-file and --channel are two ways to post; give one")
    send: Callable[[str], tuple[bool, str]]
    try:
        if args.channel is None:
            send = functools.partial(post, read_webhook(args.webhook_file or default_webhook_file(), prefix=prefix))
        else:
            channel = check_channel(args.channel)
            send = functools.partial(
                post_message,
                api_url,
                read_token(args.token_file or default_token_file()),
                channel,
                username=None if args.username is None else check_username(args.username),
                icon_emoji=None if args.icon_emoji is None else check_icon_emoji(args.icon_emoji),
            )
        parsed = read_message(stdin.read())
    except SinkError as e:
        print(f"canopy-notify-slack: {e}", file=sys.stderr)  # noqa: T201
        return 2
    ok, reply = send(render(parsed))
    if not ok:
        print(f"canopy-notify-slack: Slack refused the post: {reply}", file=sys.stderr)  # noqa: T201
        return 1
    return 0


def main() -> int:
    """The `canopy-notify-slack` command."""
    return run(sys.argv[1:], sys.stdin)
