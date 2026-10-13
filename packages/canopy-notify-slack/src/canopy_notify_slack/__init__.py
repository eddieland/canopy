"""`canopy-notify-slack`: canopy's Slack sink (DESIGN §20). Posts each message it reads on stdin to a Slack channel.

It reads canopy's `json` message format on stdin and posts one Slack message, to an incoming webhook or, given
`--channel`, with a bot token through `chat.postMessage`, optionally under its own `--username` and `--icon-emoji`.
Presentation is the sink's: the message is Block Kit built from the fields canopy sends, not from its text lines,
with the same message as lines for Slack's notifications.
The secret comes from a file that belongs to the operator and that nobody else can read, never from argv, the
environment, or canopy's config: `--webhook-file PATH`, by default
`$XDG_CONFIG_HOME/canopy/slack-webhook`, or `--token-file PATH`, by default `$XDG_CONFIG_HOME/canopy/slack-token`.
Text from the journal, which agents and org members wrote, is escaped for Slack's markup and set `verbatim`, so it
cannot mention a person or `@channel`, or show one link and point at another.

Exit codes: 0 posted (a 2xx reply, and `"ok": true` from the Web API); 1 the post failed, with Slack's reply on
stderr; 2 the secret file, the channel, or the message on stdin is not usable, saying which. canopy retries anything
but 0 on its next tick.

Stdlib only, importing nothing from canopy: canopy runs it as a command, so the process that holds the journal and
enforces the guards never opens a connection or reads this secret (D035).

In a release's single executable (D067), run a sink with `SCIE_BOOT` set to its name; `RELEASE_HELP`, below, which
`--help` prints, has a wrapper script for `PATH`.
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
from datetime import datetime
from pathlib import Path
from typing import TextIO

RELEASE_HELP = """\
In a release's single executable, run this sink with SCIE_BOOT set to its name: SCIE_BOOT=canopy-notify-slack
/path/to/canopy. A link named canopy-notify-slack can run canopy itself instead. So that a sink's cmd can name
canopy-notify-slack, put this script on PATH under that name, with the path to your canopy, and make it executable:

    #!/bin/sh
    exec env SCIE_BOOT=canopy-notify-slack /path/to/canopy "$@"
"""
SLACK_PREFIX = "https://hooks.slack.com/"
SLACK_API_URL = "https://slack.com/api/chat.postMessage"
# A bot token: a user token (`xoxp-`) acts as the operator, with every scope they granted it.
TOKEN_PREFIX = "xoxb-"  # noqa: S105
TIMEOUT_SECONDS = 30
# How much of Slack's reply a failure prints.
_MAX_REPLY = 500
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
    """`$XDG_CONFIG_HOME/canopy/slack-webhook`, or `~/.config/canopy/slack-webhook`.

    Returns:
        The path, whether or not the file exists.
    """
    return _config_file("slack-webhook")


def default_token_file() -> Path:
    """`$XDG_CONFIG_HOME/canopy/slack-token`, or `~/.config/canopy/slack-token`.

    Returns:
        The path, whether or not the file exists.
    """
    return _config_file("slack-token")


def _read_secret(path: Path, what: str) -> str:
    """Return the stripped text of `path`, which must be a regular file of the operator's, closed to others.

    Returns:
        The file's text, without leading or trailing whitespace.

    Raises:
        SinkError: The file cannot be read, is not a regular file, belongs to someone else, is readable by others,
            or is not UTF-8.
    """
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
    """Return the webhook URL in `path`, which must be the operator's, closed to others, and hold one Slack URL.

    Returns:
        The URL, which starts with `prefix` and has its scheme and host.

    Raises:
        SinkError: The file is not usable, or does not hold one URL starting with `prefix`.
    """
    url = _read_secret(path, "webhook")
    if not url.startswith(prefix) or any(c.isspace() for c in url) or not _same_origin(url, prefix):
        raise SinkError(f"the webhook file {path} must hold one URL starting {prefix}")
    return url


def read_token(path: Path) -> str:
    """Return the token in `path`, which must be the operator's, closed to others, and hold one Slack bot token.

    Returns:
        The token, printable ASCII starting with `xoxb-`.

    Raises:
        SinkError: The file is not usable, or does not hold one bot token.
    """
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
    """Return `channel` if it is a Slack channel id or name.

    Returns:
        `channel`, unchanged.

    Raises:
        SinkError: `channel` is not a channel id or name.
    """
    if not _CHANNEL.fullmatch(channel):
        raise SinkError(f"--channel {channel!r} is not a Slack channel id or name")
    return channel


def check_username(username: str) -> str:
    """Return `username` if it is a display name: printable, not blank, at most 80 characters.

    Returns:
        `username`, unchanged.

    Raises:
        SinkError: `username` is blank, not printable, or longer than 80 characters.
    """
    if not username.strip() or not username.isprintable() or len(username) > _MAX_USERNAME:
        raise SinkError(f"--username {username!r} must be printable, not blank, and at most {_MAX_USERNAME} characters")
    return username


def check_icon_emoji(icon_emoji: str) -> str:
    """Return `icon_emoji` if it is an emoji code such as `:robot_face:`.

    Returns:
        `icon_emoji`, unchanged.

    Raises:
        SinkError: `icon_emoji` is not an emoji code.
    """
    if not _EMOJI.fullmatch(icon_emoji):
        raise SinkError(f"--icon-emoji {icon_emoji!r} is not an emoji code such as :robot_face:")
    return icon_emoji


def _same_origin(url: str, prefix: str) -> bool:
    """Whether `url` parses to the scheme and host of `prefix`, with no user part: a prefix match cannot hide a host.

    Returns:
        True if the scheme and host match and `url` has no user part. False otherwise, or if `url` does not parse.
    """
    try:
        got, want = urllib.parse.urlsplit(url), urllib.parse.urlsplit(prefix)
        _ = got.port  # raises on a malformed port
    except ValueError:
        return False
    return (got.scheme, got.hostname, got.username) == (want.scheme, want.hostname, None)


def escape(text: object) -> str:
    """Escape Slack's markup characters, so text cannot mention anyone or disguise a link. Bare URLs stay clickable.

    Returns:
        `text` as a string on one line, its runs of whitespace made single spaces, and `&`, `<` and `>` escaped.
    """
    return " ".join(str(text).split()).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _subject(ticket: object, repo: object) -> str:
    if ticket is None:
        return str(repo or "-")
    return f"{ticket} ({repo})" if repo else str(ticket)


def _named(subject: object, title: object) -> str:
    """`subject` in bold, then the ticket's `title` if canopy sent one: `*PROJ-1* Add retries to checkout`.

    Returns:
        The escaped Slack text.
    """
    return f"*{escape(subject)}*" + (f" {escape(title)}" if title else "")


def _titled(subject: object, title: object) -> str:
    """`subject`, then the ticket's `title` if canopy sent one, unmarked.

    Returns:
        The escaped Slack text.
    """
    return escape(subject) + (f" {escape(title)}" if title else "")


def _dicts(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [{str(k): v for k, v in item.items()} for item in value if isinstance(item, dict)]


def _lines(value: object) -> list[str]:
    return [str(line) for line in value] if isinstance(value, list) else []


def render(message: dict[str, object]) -> str:
    """Return the Slack text for one canopy `json` message: a header with counts, a line per item or event, a digest.

    Returns:
        The escaped text, its lines joined by newlines, at most 45 lines, the last saying how many were left out.
    """
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
            what = _named(_subject(a.get("ticket"), a.get("repo")), a.get("title"))
            lines.append(f"+ {what} · {escape(a.get('reason'))}: {escape(a.get('detail'))}")
        lines += [
            f"- {_named(_subject(r.get('ticket'), r.get('repo')), r.get('title'))} · {escape(r.get('reason'))}"
            + (" (dismissed)" if r.get("dismissed") is True else "")
            for r in resolved
        ]
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


# Block Kit's limits: blocks in a message, characters in a section's text and in a header, elements in a context.
_MAX_BLOCKS = 50
_MAX_SECTION = 3000
_MAX_HEADER = 150
_MAX_CONTEXT = 10
# Digest runs listed by name, as the text format lists them.
_DIGEST_LISTED = 10
_URL = re.compile(r"https?://[^\s|]+")
_STATUS_EMOJI = {
    "done": ":white_check_mark:",
    "blocked": ":raising_hand:",
    "failed": ":x:",
    "crashed": ":boom:",
    "timeout": ":hourglass:",
    "abandoned": ":wastebasket:",
    "stopped": ":octagonal_sign:",
}

type Block = dict[str, object]
_DIVIDER: Block = {"type": "divider"}


def _mrkdwn(text: str) -> Block:
    # `verbatim`: Slack parses nothing in it, so journal text that says @channel or #general stays text. Links are
    # made explicit by `_linked`, and dates by `_when`.
    if len(text) > _MAX_SECTION:
        text = text[: _MAX_SECTION - 1] + "…"
    return {"type": "mrkdwn", "text": text, "verbatim": True}


def _section(*lines: str) -> Block:
    return {"type": "section", "text": _mrkdwn("\n".join(line for line in lines if line))}


def _context(*parts: str) -> Block:
    return {"type": "context", "elements": [_mrkdwn(part) for part in parts[:_MAX_CONTEXT]]}


def _linked(text: object) -> str:
    """`text`, escaped, each URL in it a link that shows the URL itself.

    A URL holding `|` stays text: in a link, what follows `|` is a label shown in the URL's place.

    Returns:
        The escaped Slack text.
    """
    return " ".join(f"<{word}>" if _URL.fullmatch(word) else word for word in escape(text).split(" "))


def _when(at: object) -> str:
    """`at`, an ISO time, as a Slack date in the reader's own time zone, falling back to `at` as written.

    Returns:
        A Slack date token, or `at` escaped if it is not an ISO time with a time zone.
    """
    try:
        parsed = datetime.fromisoformat(str(at))
    except ValueError:
        return escape(at)
    if parsed.tzinfo is None:
        return escape(at)
    return f"<!date^{int(parsed.timestamp())}^{{date_short_pretty}} {{time}}|{escape(at)}>"


def _ended(e: dict[str, object], what: str) -> str:
    """`what` ended with the event's status: led by the status's emoji, so a channel scans by outcome.

    Returns:
        The Slack text.
    """
    status = e.get("status")
    return f"{_STATUS_EMOJI.get(str(status), ':black_small_square:')} {what} ended *{escape(status)}*"


def _quote(label: str, text: object) -> str:
    return f"> *{label}:* {_linked(text)}" if text else ""


def _counted(counts: object) -> str:
    if not isinstance(counts, dict) or not counts:
        return "none"
    return ", ".join(f"{escape(k)} {escape(v)}" for k, v in sorted(counts.items(), key=lambda kv: str(kv[0])))


def _run_started(e: dict[str, object]) -> Block:
    return _section(
        f":arrow_forward: {_named(e.get('ticket'), e.get('title'))} · {escape(e.get('run_kind'))} run "
        f"{escape(e.get('run'))} started",
        f"attempt {escape(e.get('attempt'))} of {escape(e.get('limit'))} on `{escape(e.get('branch') or '-')}`",
    )


def _run_ended(e: dict[str, object]) -> Block:
    prs = _lines(e.get("prs")) or ([str(e["pr"])] if e.get("pr") else [])
    run = f"{escape(e.get('run_kind'))} run {escape(e.get('run'))}"
    return _section(
        _ended(e, f"{_named(e.get('ticket'), e.get('title'))} · {run}"),
        *(_linked(pr) for pr in prs),
        _linked(e.get("summary")) if e.get("summary") else "",
        _quote("Question", e.get("question")),
    )


def _chore_ended(e: dict[str, object]) -> Block:
    findings = e.get("findings") or 0
    return _section(
        _ended(e, f"*chore:{escape(e.get('chore'))}* · run {escape(e.get('run'))}")
        + f" · {escape(findings)} finding{'s' if findings != 1 else ''}",
        _linked(e.get("summary")) if e.get("summary") else "",
    )


def _review_ended(e: dict[str, object]) -> Block:
    ticket = f"{_named(e.get('ticket'), e.get('title'))} · " if e.get("ticket") else ""
    verdict = " ".join(escape(x) for x in (e.get("verdict"), e.get("impact")) if x)
    findings = e.get("findings") or 0
    counted = f" · {escape(findings)} finding{'s' if findings != 1 else ''}" if verdict else ""
    return _section(
        _ended(e, f"{ticket}review run {escape(e.get('run'))}") + (f": {verdict}{counted}" if verdict else ""),
        _linked(e.get("pr")) if e.get("pr") else "",
    )


def _loop_failing(e: dict[str, object]) -> Block:
    return _section(
        f":rotating_light: *The loop is failing:* {escape(e.get('count'))} ticks in a row ended other than ok",
        f"latest tick {escape(e.get('tick'))} ended {escape(e.get('status'))}; log `{escape(e.get('log'))}`",
    )


def _loop_recovered(e: dict[str, object]) -> Block:
    return _section(f":white_check_mark: *The loop recovered* after {escape(e.get('failed'))} failed ticks")


def _sink_failing(e: dict[str, object]) -> Block:
    return _section(
        f":warning: *Sink {escape(e.get('sink'))} is failing:* 3 deliveries in a row", f"`{escape(e.get('error'))}`"
    )


def _test(e: dict[str, object]) -> Block:
    return _section(f":test_tube: {_linked(e.get('text'))}")


_EVENTS: dict[str, Callable[[dict[str, object]], Block]] = {
    "run.started": _run_started,
    "run.ended": _run_ended,
    "chore.ended": _chore_ended,
    "review.ended": _review_ended,
    "loop.failing": _loop_failing,
    "loop.recovered": _loop_recovered,
    "loop.sink_failing": _sink_failing,
    "test": _test,
}


def _event(e: dict[str, object]) -> Block:
    """One event as a section built from its fields. A kind this sink does not know shows its text-format line.

    Returns:
        The section block.
    """
    build = _EVENTS.get(str(e.get("kind")))
    return build(e) if build is not None else _section(_linked(e.get("line") or e.get("kind")))


def _attention(attention: dict[str, object]) -> list[Block]:
    out = [
        _section(
            f":bell: {_named(_subject(a.get('ticket'), a.get('repo')), a.get('title'))} · {escape(a.get('reason'))}",
            _linked(a.get("detail")) if a.get("detail") else "",
            f"_open since {_when(a.get('since'))}_" if a.get("since") else "",
        )
        for a in _dicts(attention.get("added"))
    ]
    resolved = [
        f":heavy_check_mark: ~{_titled(_subject(r.get('ticket'), r.get('repo')), r.get('title'))}~ "
        f"{escape(r.get('reason'))}" + (" (dismissed)" if r.get("dismissed") is True else "")
        for r in _dicts(attention.get("resolved"))
    ]
    if resolved:
        out.append(_section("*Resolved*", *resolved))
    return out


def _digest(digest: dict[str, object]) -> list[Block]:
    ticks = digest.get("ticks")
    total = sum(n for n in ticks.values() if isinstance(n, int)) if isinstance(ticks, dict) else 0
    given = digest.get("attention")
    attention: dict[str, object] = {str(k): v for k, v in given.items()} if isinstance(given, dict) else {}
    needs_you = "nothing"
    if attention.get("open"):
        needs_you = f"{escape(attention.get('open'))} open ({_counted(attention.get('by_reason'))})"
        needs_you += f", oldest {escape(attention.get('oldest'))}" if attention.get("oldest") else ""
    fields = [
        f"*Ticks*\n{total} ({_counted(ticks)})",
        f"*Workers running*\n{escape(digest.get('running', 0))}",
        f"*Runs started*\n{_counted(digest.get('runs_started'))}",
        f"*Runs ended*\n{_counted(digest.get('runs_ended'))}",
        f"*Needs you*\n{needs_you}",
    ]
    out: list[Block] = [
        {
            "type": "section",
            "text": _mrkdwn(f"*Digest* since {_when(digest.get('since'))}"),
            "fields": [_mrkdwn(f) for f in fields],
        }
    ]
    runs = [
        f"{_STATUS_EMOJI['done']} {_named(d.get('ticket'), d.get('title'))} "
        f"{_linked(d.get('pr')) if d.get('pr') else ''}".rstrip()
        for d in _dicts(digest.get("done"))[:_DIGEST_LISTED]
    ]
    runs += [
        f"{_STATUS_EMOJI['blocked']} {_named(b.get('ticket'), b.get('title'))}" for b in _dicts(digest.get("blocked"))
    ]
    if runs:
        out.append(_section(*runs[: 2 * _DIGEST_LISTED]))
    return out


def blocks(message: dict[str, object]) -> list[Block]:
    """Return Block Kit blocks for one canopy `json` message, built from its fields rather than its text lines.

    A header with the repository directory name and counts, a section per attention item and per event, the resolved
    items together, and the digest as fields. At most Slack's 50 blocks, the last saying how many were left out.

    Returns:
        The blocks, in the order Slack shows them.
    """
    repo = Path(str(message.get("repo") or "")).name or "canopy"
    header: Block = {"type": "plain_text", "text": f"canopy · {repo}"[:_MAX_HEADER]}
    out: list[Block] = [{"type": "header", "text": header}]
    counts: list[str] = []
    given = message.get("attention")
    body: list[Block] = []
    if isinstance(given, dict):
        attention: dict[str, object] = {str(k): v for k, v in given.items()}
        added, resolved = _dicts(attention.get("added")), _dicts(attention.get("resolved"))
        if added or resolved:
            counts.append(f"{len(added)} new · {len(resolved)} resolved · {escape(attention.get('open', 0))} open")
        body = _attention(attention)
    events = _dicts(message.get("events"))
    if events:
        counts.append(f"{len(events)} event{'s' if len(events) != 1 else ''}")
        body += [_DIVIDER] if body else []
        body += [_event(e) for e in events]
    digest = message.get("digest")
    if isinstance(digest, dict):
        counts.append("digest")
        body += [_DIVIDER] if body else []
        body += _digest({str(k): v for k, v in digest.items()})
    if counts:
        out.append(_context(" · ".join(counts)))
    out += body
    omitted = message.get("omitted")
    more = omitted if isinstance(omitted, int) else 0
    if len(out) + (1 if more else 0) > _MAX_BLOCKS:
        more += len(out) - (_MAX_BLOCKS - 1)
        out = out[: _MAX_BLOCKS - 1]
    if more:
        out.append(_context(f"_… and {more} more: see `canopy status`_"))
    return out


def post(url: str, text: str, blocks: list[Block]) -> tuple[bool, str]:
    """Post `blocks` to the webhook, with `text` for notifications.

    Returns:
        Whether Slack accepted it, and its reply.
    """
    # `read_webhook` checked the URL's scheme and host.
    return _post(url, {"text": text, "blocks": blocks}, {"Content-Type": "application/json"})


def post_message(
    api_url: str,
    token: str,
    channel: str,
    text: str,
    blocks: list[Block],
    *,
    username: str | None = None,
    icon_emoji: str | None = None,
) -> tuple[bool, str]:
    """Post `blocks` to `channel` with `chat.postMessage`, as `username` with `icon_emoji` when given.

    `text` is what Slack shows in a notification, and where blocks cannot be shown.

    Returns:
        Whether Slack accepted it, and its reply. A 2xx reply without `"ok": true` is not accepted.
    """
    headers = {"Content-Type": "application/json; charset=utf-8", "Authorization": f"Bearer {token}"}
    payload: dict[str, object] = {"channel": channel, "text": text, "blocks": blocks}
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


def _post(url: str, payload: dict[str, object], headers: dict[str, str]) -> tuple[bool, str]:
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            # The whole reply: `post_message` parses it, and a successful `chat.postMessage` reply runs long.
            return 200 <= response.status < 300, response.read().decode(errors="replace")  # noqa: PLR2004
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode(errors='replace')[:_MAX_REPLY]}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return False, f"cannot reach Slack: {e}"


def read_message(stdin: str) -> dict[str, object]:
    """Read canopy's `json` message format from `stdin`.

    Returns:
        The message, a JSON object, with string keys.

    Raises:
        SinkError: `stdin` is not JSON, or not a JSON object.
    """
    hint = 'set format = "json" for this sink'
    try:
        parsed: object = json.loads(stdin)
    except json.JSONDecodeError as e:
        raise SinkError(f"stdin is not a canopy json message: {e}; {hint}") from e
    if not isinstance(parsed, dict):
        raise SinkError(f"stdin is not a canopy json message; {hint}")
    return {str(k): v for k, v in parsed.items()}


def run(argv: list[str], stdin: TextIO, *, prefix: str = SLACK_PREFIX, api_url: str = SLACK_API_URL) -> int:
    """Post the message on `stdin`.

    `prefix` is what the webhook URL must start with; `api_url` is where a token posts.

    Returns:
        The exit code: 0 posted, 1 Slack refused the post, 2 the secret file, the channel, or the message is not
        usable.
    """
    parser = argparse.ArgumentParser(
        prog="canopy-notify-slack",
        description=__doc__.split("\n", 1)[0],
        epilog=RELEASE_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
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
    send: Callable[[str, list[Block]], tuple[bool, str]]
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
    ok, reply = send(render(parsed), blocks(parsed))
    if not ok:
        print(f"canopy-notify-slack: Slack refused the post: {reply[:_MAX_REPLY]}", file=sys.stderr)  # noqa: T201
        return 1
    return 0


def main() -> int:
    """The `canopy-notify-slack` command.

    Returns:
        The exit code.
    """
    return run(sys.argv[1:], sys.stdin)
