"""`canopy-notify-slack`: canopy's Slack sink (DESIGN §20). Posts each message it reads on stdin to a Slack channel.

It reads canopy's `json` message format on stdin and posts one Slack message, to an incoming webhook or, given
`--channel`, with a bot token through `chat.postMessage`, optionally under its own `--username` and `--icon-emoji`.
Presentation is the sink's: the message is Block Kit built from the fields canopy sends, not from its text lines,
with the same message as lines for Slack's notifications.
The secret comes from a file that belongs to the operator and that nobody else can read, never from argv, the
environment, or canopy's config: `--webhook-file PATH`, by default
`$XDG_CONFIG_HOME/canopy/slack-webhook`, or `--token-file PATH`, by default `$XDG_CONFIG_HOME/canopy/slack-token`.
Text from the journal, which agents and org members wrote, is escaped for Slack's markup and set `verbatim`, so it
cannot mention a person or `@channel`, or show one link and point at another. The page of canopy's web UI the message
gives an item or event, while the loop serves one, is linked after it under the sink's own word, `open`.

With `--channel` and `--threads`, what is about one ticket, chore, or review goes in its own thread, a new one each
day, recorded in the sink's own state file, `$XDG_STATE_HOME/canopy/slack-threads.json`; the rest goes in the channel.
Each thread starts with a post of the same shape, naming what it is about, and everything about it is a reply.
A reply stays in its thread, unless `--broadcast` names what it holds, such as `--broadcast blocked` for a worker's
question: then it is shown in the channel too.

Exit codes: 0 posted (a 2xx reply, and `"ok": true` from the Web API); 1 the post failed, with Slack's reply on
stderr; 2 the secret file, the channel, the threads file, or the message on stdin is not usable, saying which. canopy
retries anything but 0 on its next tick.

Stdlib only, importing nothing from canopy: canopy runs it as a command, so the process that holds the journal and
enforces the guards never opens a connection or reads this secret (D035).
"""

from __future__ import annotations

import argparse
import fcntl
import functools
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, TextIO

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


def render(message: Mapping[str, object]) -> str:
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
#: Each kind of run a digest's `spend` names, as its field shows it.
_SPENT = (
    ("overseer", "overseer"),
    ("workers", "workers"),
    ("plans", "plans"),
    ("chores", "chores"),
    ("reviews", "reviews"),
    ("dry_run", "dry runs"),
)
_URL = re.compile(r"https?://[^\s|]+")
# A link canopy sends to a page of its web UI: a URL's own characters only, so it needs no escaping but `&`, and no `|`
# can put a label of its own in it. The same class as `serve.url`'s check in canopy's config (`_UI_URL_RE`).
_PAGE = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+")
_MAX_PAGE = 2000
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


def _open(page: object) -> str:
    """A link labelled `open` to `page`, the web UI's page canopy sent for an item or event, if it is a plain URL.

    The label is the sink's own word, never text from the message, so the link cannot show one address and open
    another.

    Returns:
        The Slack link, or nothing when `page` is missing or not a plain `http` or `https` URL.
    """
    if not isinstance(page, str) or len(page) > _MAX_PAGE or not _PAGE.fullmatch(page):
        return ""
    return f"<{page.replace('&', '&amp;')}|open>"


def _with_open(first: str, page: object) -> str:
    """`first`, then a link to `page` if there is one.

    Returns:
        The Slack text.
    """
    link = _open(page)
    return f"{first} · {link}" if link else first


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


def _ended(e: Mapping[str, object], what: str) -> str:
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


def _run_started(e: Mapping[str, object]) -> list[str]:
    return [
        (
            f":arrow_forward: {_named(e.get('ticket'), e.get('title'))} · {escape(e.get('run_kind'))} run "
            f"{escape(e.get('run'))} started"
        ),
        f"attempt {escape(e.get('attempt'))} of {escape(e.get('limit'))} on `{escape(e.get('branch') or '-')}`",
    ]


def _run_ended(e: Mapping[str, object]) -> list[str]:
    prs = _lines(e.get("prs")) or ([str(e["pr"])] if e.get("pr") else [])
    run = f"{escape(e.get('run_kind'))} run {escape(e.get('run'))}"
    return [
        _ended(e, f"{_named(e.get('ticket'), e.get('title'))} · {run}"),
        *(_linked(pr) for pr in prs),
        _linked(e.get("summary")) if e.get("summary") else "",
        _quote("Question", e.get("question")),
    ]


def _chore_ended(e: Mapping[str, object]) -> list[str]:
    findings = e.get("findings") or 0
    return [
        _ended(e, f"*chore:{escape(e.get('chore'))}* · run {escape(e.get('run'))}")
        + f" · {escape(findings)} finding{'s' if findings != 1 else ''}",
        _linked(e.get("summary")) if e.get("summary") else "",
    ]


def _review_ended(e: Mapping[str, object]) -> list[str]:
    ticket = f"{_named(e.get('ticket'), e.get('title'))} · " if e.get("ticket") else ""
    verdict = " ".join(escape(x) for x in (e.get("verdict"), e.get("impact")) if x)
    findings = e.get("findings") or 0
    counted = f" · {escape(findings)} finding{'s' if findings != 1 else ''}" if verdict else ""
    return [
        _ended(e, f"{ticket}review run {escape(e.get('run'))}") + (f": {verdict}{counted}" if verdict else ""),
        _linked(e.get("pr")) if e.get("pr") else "",
    ]


def _loop_failing(e: Mapping[str, object]) -> list[str]:
    return [
        f":rotating_light: *The loop is failing:* {escape(e.get('count'))} ticks in a row ended other than ok",
        f"latest tick {escape(e.get('tick'))} ended {escape(e.get('status'))}; log `{escape(e.get('log'))}`",
    ]


def _loop_recovered(e: Mapping[str, object]) -> list[str]:
    return [f":white_check_mark: *The loop recovered* after {escape(e.get('failed'))} failed ticks"]


def _sink_failing(e: Mapping[str, object]) -> list[str]:
    return [
        f":warning: *Sink {escape(e.get('sink'))} is failing:* 3 deliveries in a row",
        f"`{escape(e.get('error'))}`",
    ]


def _test(e: Mapping[str, object]) -> list[str]:
    return [f":test_tube: {_linked(e.get('text'))}"]


# Each event kind's lines, the first naming what happened: the event's page in the web UI is linked after it.
_EVENTS: dict[str, Callable[[Mapping[str, object]], list[str]]] = {
    "run.started": _run_started,
    "run.ended": _run_ended,
    "chore.ended": _chore_ended,
    "review.ended": _review_ended,
    "loop.failing": _loop_failing,
    "loop.recovered": _loop_recovered,
    "loop.sink_failing": _sink_failing,
    "test": _test,
}


def _event(e: Mapping[str, object]) -> Block:
    """One event as a section built from its fields. A kind this sink does not know shows its text-format line.

    Returns:
        The section block, its first line linking to the event's page in the web UI when canopy sent one.
    """
    build = _EVENTS.get(str(e.get("kind")))
    first, *rest = build(e) if build is not None else [_linked(e.get("line") or e.get("kind"))]
    return _section(_with_open(first, e.get("ui")), *rest)


def _attention(attention: Mapping[str, object]) -> list[Block]:
    out = [_added(a) for a in _dicts(attention.get("added"))]
    resolved = [
        f":heavy_check_mark: ~{_titled(_subject(r.get('ticket'), r.get('repo')), r.get('title'))}~ "
        f"{escape(r.get('reason'))}" + (" (dismissed)" if r.get("dismissed") is True else "")
        for r in _dicts(attention.get("resolved"))
    ]
    if resolved:
        out.append(_section("*Resolved*", *resolved))
    return out


def _added(a: Mapping[str, object]) -> Block:
    """A new attention item: what it is about and why, linking to its page in the web UI, then its detail and age.

    Returns:
        The section block.
    """
    what = f":bell: {_named(_subject(a.get('ticket'), a.get('repo')), a.get('title'))} · {escape(a.get('reason'))}"
    return _section(
        _with_open(what, a.get("ui")),
        _linked(a.get("detail")) if a.get("detail") else "",
        f"_open since {_when(a.get('since'))}_" if a.get("since") else "",
    )


def _digest(digest: Mapping[str, object]) -> list[Block]:
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
    spent = digest.get("spend")
    # A canopy from before digests carried spend sends none, and gets no field for it.
    if isinstance(spent, dict):
        fields.append(f"*Spent*\n{_spent({str(k): v for k, v in spent.items()})}")
    out: list[Block] = [
        {
            "type": "section",
            "text": _mrkdwn(f"*Digest* since {_when(digest.get('since'))}"),
            "fields": [_mrkdwn(f) for f in fields],
        },
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


# What the digest's span cost: the total, then each kind that reported a cost, in the order canopy's text lists them.
def _spent(spent: Mapping[str, object]) -> str:
    total = spent.get("total")
    if not isinstance(total, int | float):
        return "none reported"
    parts = [f"{name} {_usd(usd)}" for kind, name in _SPENT if isinstance(usd := spent.get(kind), int | float)]
    return f"{_usd(total)} ({', '.join(parts)})"


def _usd(usd: float) -> str:
    return f"${usd:.2f}"


def blocks(message: Mapping[str, object], *, header: bool = True) -> list[Block]:
    """Return Block Kit blocks for one canopy `json` message, built from its fields rather than its text lines.

    A header with the repository directory name and counts, a section per attention item and per event, the resolved
    items together, and the digest as fields. At most Slack's 50 blocks, the last saying how many were left out.
    Without `header`, as a post in a ticket's thread is, the message starts at its first item.

    Returns:
        The blocks, in the order Slack shows them.
    """
    repo = Path(str(message.get("repo") or "")).name or "canopy"
    title: Block = {"type": "plain_text", "text": f"canopy · {repo}"[:_MAX_HEADER]}
    out: list[Block] = [{"type": "header", "text": title}] if header else []
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
    if counts and header:
        out.append(_context(_with_open(" · ".join(counts), message.get("ui"))))
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
    thread_ts: str | None = None,
    reply_broadcast: bool = False,
) -> tuple[bool, str]:
    """Post `blocks` to `channel` with `chat.postMessage`, as `username` with `icon_emoji` when given.

    `text` is what Slack shows in a notification, and where blocks cannot be shown. Given `thread_ts`, the post is a
    reply in that message's thread, also shown in the channel with `reply_broadcast`.

    Returns:
        Whether Slack accepted it, and its reply. A 2xx reply without `"ok": true` is not accepted.
    """
    headers = {"Content-Type": "application/json; charset=utf-8", "Authorization": f"Bearer {token}"}
    payload: dict[str, object] = {"channel": channel, "text": text, "blocks": blocks}
    if username is not None:
        payload["username"] = username
    if icon_emoji is not None:
        payload["icon_emoji"] = icon_emoji
    if thread_ts is not None:
        payload["thread_ts"] = thread_ts
        if reply_broadcast:
            payload["reply_broadcast"] = True
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


# Threads, with `--threads`

#: What `--broadcast` can show in the channel from a thread's reply, and what each is.
BROADCASTS: Mapping[str, str] = {
    "attention": "a new attention item",
    "plan": "a plan to approve",
    "blocked": "a run that ended blocked, waiting on an answer",
}

# A message's `ts`, which names it to reply in its thread.
_TS = re.compile(r"\d{1,20}\.\d{1,20}")


def default_threads_file() -> Path:
    """`$XDG_STATE_HOME/canopy/slack-threads.json`, or `~/.local/state/canopy/slack-threads.json`.

    Returns:
        The path, whether or not the file exists.
    """
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base).expanduser() / "canopy" / "slack-threads.json"


class Send(Protocol):
    """Post one message to the channel, as a reply in a thread when given its `ts`: `post_message`, its target bound."""

    def __call__(
        self,
        text: str,
        blocks: list[Block],
        *,
        thread_ts: str | None = None,
        reply_broadcast: bool = False,
    ) -> tuple[bool, str]:
        """Post it.

        Returns:
            Whether Slack accepted it, and its reply.
        """
        ...


@dataclass
class Threads:
    """For one channel and repository: each thread the sink posts in today, and what a failed delivery posted.

    The file holds a scope for each channel and repository, so sinks and workspaces sharing it keep their own, and a
    save replaces only its own scope. Losing the file costs nothing worse than new threads.
    """

    path: Path
    # The channel and repository, as a JSON list: the key of this record's part of the file.
    scope: str
    # What a thread is about, such as a ticket key, to the day it was started and its first message's `ts`.
    threads: dict[str, tuple[str, str]]
    # Fingerprints of the items posted by a delivery that has not yet posted whole, so canopy's retry skips them.
    posted: set[str]

    @classmethod
    def load(cls, path: Path, channel: str, repo: str) -> Threads:
        """Read the scope of `channel` and `repo` from `path`: empty if missing or not what this sink wrote.

        Returns:
            The threads and fingerprints the scope holds.

        Raises:
            SinkError: `path` is there but cannot be read, or is not a regular file.
        """
        scope = json.dumps([channel, repo])
        given = _scopes(path).get(scope)
        mine: dict[str, object] = {str(k): v for k, v in given.items()} if isinstance(given, dict) else {}
        threads: dict[str, tuple[str, str]] = {}
        recorded = mine.get("threads")
        for key, thread in recorded.items() if isinstance(recorded, dict) else ():
            day, ts = (thread.get("day"), thread.get("ts")) if isinstance(thread, dict) else (None, None)
            if isinstance(day, str) and isinstance(ts, str) and _TS.fullmatch(ts):
                threads[str(key)] = (day, ts)
        fingerprints = mine.get("posted")
        posted = {f for f in fingerprints if isinstance(f, str)} if isinstance(fingerprints, list) else set()
        return cls(path, scope, threads, posted)

    def save(self) -> None:
        """Replace this scope in the file, leaving the others as another sink last wrote them.

        Under a lock, so two sinks saving at once each keep the other's scope; the file is replaced whole, so a sink
        killed mid-write leaves the last one.

        Raises:
            SinkError: The file or its directory cannot be read or written.
        """
        mine = {
            "threads": {key: {"day": day, "ts": ts} for key, (day, ts) in sorted(self.threads.items())},
            "posted": sorted(self.posted),
        }
        tmp: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lock = os.open(self.path.with_name(self.path.name + ".lock"), os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX)
                scopes = _scopes(self.path)
                scopes[self.scope] = mine
                with tempfile.NamedTemporaryFile(
                    "w",
                    encoding="utf-8",
                    dir=self.path.parent,
                    prefix=".slack-threads-",
                    delete=False,
                ) as f:
                    tmp = Path(f.name)
                    json.dump({"version": 1, "scopes": dict(sorted(scopes.items()))}, f)
                    f.write("\n")
                tmp.replace(self.path)
            finally:
                os.close(lock)
        except OSError as e:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
            raise SinkError(f"cannot write the threads file {self.path}: {e.strerror or e}") from e

    def finish(self, day: str) -> None:
        """A delivery has posted whole: forget what it posted, and every thread started before `day`.

        Raises:
            SinkError: The file cannot be written.
        """
        self.posted.clear()
        # ISO dates order as strings. A later day's thread stays, should a delivery carry an earlier clock.
        self.threads = {key: thread for key, thread in self.threads.items() if thread[0] >= day}
        self.save()


def _scopes(path: Path) -> dict[str, object]:
    """The scopes the threads file at `path` holds, as written: none if it is missing or not one this sink wrote.

    Returns:
        Each scope's key and its record, unchecked.

    Raises:
        SinkError: `path` is there but cannot be read, or is not a regular file.
    """
    try:
        st = path.stat()
    except FileNotFoundError:
        return {}
    except OSError as e:
        raise SinkError(f"cannot read the threads file {path}: {e.strerror}") from e
    # Checked before reading: opening a FIFO would block.
    if not stat.S_ISREG(st.st_mode):
        raise SinkError(f"the threads file {path} is not a regular file")
    try:
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise SinkError(f"cannot read the threads file {path}: {e.strerror}") from e
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    scopes = parsed.get("scopes") if isinstance(parsed, dict) else None
    return {str(k): v for k, v in scopes.items()} if isinstance(scopes, dict) else {}


@dataclass
class Part:
    """What one post of a threaded delivery holds: one thread's items, or, with no `thread`, the channel's."""

    thread: str | None
    added: list[dict[str, object]] = field(default_factory=list)
    resolved: list[dict[str, object]] = field(default_factory=list)
    events: list[dict[str, object]] = field(default_factory=list)
    digest: dict[str, object] | None = None
    omitted: int = 0

    def items(self) -> list[object]:
        """Everything the post shows, one item each, as fingerprinted.

        Returns:
            The attention items, the events, the digest, and the count of what canopy left out, those it has.
        """
        return [
            *self.added,
            *self.resolved,
            *self.events,
            *([self.digest] if self.digest is not None else []),
            *([{"omitted": self.omitted}] if self.omitted else []),
        ]

    def message(self, message: Mapping[str, object]) -> dict[str, object]:
        """`message` cut down to this part's items, for `blocks` and `render`.

        Returns:
            The message, its attention, events, digest, and count of what was left out replaced by this part's.
        """
        out: dict[str, object] = {**message, "events": self.events, "digest": self.digest, "omitted": self.omitted}
        attention = message.get("attention")
        if isinstance(attention, dict):
            out["attention"] = {**attention, "added": self.added, "resolved": self.resolved}
        return out

    def holds(self, what: AbstractSet[str]) -> bool:
        """Whether the post holds any of `what`, named as `BROADCASTS` names them.

        Returns:
            True when it does.
        """
        return ("attention" in what and bool(self.added)) or any(
            ("plan" in what and e.get("kind") == "plan.proposed")
            or ("blocked" in what and e.get("kind") == "run.ended" and e.get("status") == "blocked")
            for e in self.events
        )


def post_threaded(
    message: Mapping[str, object],
    send: Send,
    threads: Threads,
    broadcast: AbstractSet[str] = frozenset(),
) -> tuple[bool, str]:
    """Post `message` as `split` divides it, recording in `threads` each thread it starts and each post it makes.

    What is about a ticket, a chore, or a review's PR goes in its thread for the day, which a post of its own starts in
    the channel, naming what the thread is about, before the first item. A reply stays in its thread, unless it holds
    one of `broadcast` (`BROADCASTS` names them): then it is shown in the channel too. The rest, loop events and the
    digest among it, is posted in the channel first, with the header.

    Returns:
        Whether Slack accepted every post, and its reply to the last one tried. The first refused post ends the
        delivery: canopy retries it whole, and the posts already made are skipped.

    Raises:
        SinkError: `threads` cannot be saved.
    """
    day = _day(message.get("sent_at"))
    ok, reply = True, ""
    for part in split(message, threads.posted):
        started = threads.threads.get(part.thread) if part.thread is not None else None
        ts = started[1] if started is not None and started[0] == day else None
        if part.thread is not None and ts is None:
            ok, reply = send(*_starter(part, message, day))
            if not ok:
                return ok, reply
            # Recorded at once, so a retry after a refused reply posts in this thread rather than starting another.
            if (ts := _ts(reply)) is not None:
                threads.threads[part.thread] = (day, ts)
                threads.save()
        cut = part.message(message)
        ok, reply = send(
            render(cut),
            blocks(cut, header=part.thread is None),
            thread_ts=ts,
            reply_broadcast=ts is not None and part.holds(broadcast),
        )
        if not ok:
            return ok, reply
        threads.posted.update(_fingerprint(item) for item in part.items())
        threads.save()
    threads.finish(day)
    return ok, reply


def _starter(part: Part, message: Mapping[str, object], day: str) -> tuple[str, list[Block]]:
    """The post that starts `part`'s thread for `day`: what the thread is about, the same shape for every thread.

    A header names the ticket and its title, the chore, or the review; a line under it the repository, the day, and a
    review's PR. Everything about it that day, the first item included, is a reply under it.

    Returns:
        The text for notifications, and the blocks.
    """
    items = [*part.added, *part.resolved, *part.events]
    title = next((i["title"] for i in items if i.get("title")), None)
    # Every item of a part shares its thread, so the first says which kind it is.
    first: Mapping[str, object] = items[0] if items else {}
    pr = first.get("pr") if first.get("kind") == "review.ended" else None
    ticket = first.get("ticket")
    subject = (f"review of {ticket}" if ticket else "review") if pr else str(part.thread)
    named = " ".join((f"{subject} · {title}" if title else subject).split()) or "canopy"
    repo = Path(str(message.get("repo") or "")).name or "canopy"
    about = [f"canopy · {escape(repo)} · updates from {escape(day)} in the thread", _linked(pr) if pr else ""]
    header: Block = {"type": "header", "text": {"type": "plain_text", "text": named[:_MAX_HEADER]}}
    return escape(named), [header, _context(*(a for a in about if a))]


def split(message: Mapping[str, object], skip: AbstractSet[str] = frozenset()) -> list[Part]:
    """Divide `message` into posts: the channel's first, then a thread's each, in the order the message names them.

    An item goes in its ticket's thread, a chore's run in `chore:NAME`'s (where its findings' attention items go too),
    and a review's run in its PR's; anything else, such as a loop event, a repository's attention item, or the digest,
    in the channel. An item whose fingerprint is in `skip` is left out, and so is a post left with nothing.

    Returns:
        The posts, each with at least one item.
    """
    channel = Part(None)
    parts: dict[str | None, Part] = {None: channel}

    def part(item: Mapping[str, object]) -> Part:
        thread = _thread(item)
        return parts.setdefault(thread, Part(thread))

    given = message.get("attention")
    attention: dict[str, object] = {str(k): v for k, v in given.items()} if isinstance(given, dict) else {}
    for a in _dicts(attention.get("added")):
        if _fingerprint(a) not in skip:
            part(a).added.append(a)
    for r in _dicts(attention.get("resolved")):
        if _fingerprint(r) not in skip:
            part(r).resolved.append(r)
    for e in _dicts(message.get("events")):
        if _fingerprint(e) not in skip:
            part(e).events.append(e)
    digest = message.get("digest")
    if isinstance(digest, dict) and _fingerprint(digest) not in skip:
        channel.digest = {str(k): v for k, v in digest.items()}
    omitted = message.get("omitted")
    if isinstance(omitted, int) and omitted and _fingerprint({"omitted": omitted}) not in skip:
        channel.omitted = omitted
    return [p for p in parts.values() if p.items()]


def _thread(item: Mapping[str, object]) -> str | None:
    kind = item.get("kind")
    if kind == "chore.ended":
        return f"chore:{item['chore']}" if item.get("chore") else None
    if kind == "review.ended":
        return f"review:{item['pr']}" if item.get("pr") else None
    return str(item["ticket"]) if item.get("ticket") else None


def _fingerprint(item: object) -> str:
    return hashlib.sha256(json.dumps(item, sort_keys=True, default=str).encode()).hexdigest()


def _day(sent_at: object) -> str:
    """The operator's local date when canopy sent the message, or now if it sent no time with a time zone.

    Returns:
        The date, as `YYYY-MM-DD`.
    """
    try:
        at = datetime.fromisoformat(str(sent_at))
    except ValueError:
        at = None
    if at is None or at.tzinfo is None:
        at = datetime.now(UTC)
    return at.astimezone().date().isoformat()


def _ts(reply: str) -> str | None:
    try:
        parsed: object = json.loads(reply)
    except json.JSONDecodeError:
        return None
    ts = parsed.get("ts") if isinstance(parsed, dict) else None
    return ts if isinstance(ts, str) and _TS.fullmatch(ts) else None


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


def run(argv: Sequence[str], stdin: TextIO, *, prefix: str = SLACK_PREFIX, api_url: str = SLACK_API_URL) -> int:
    """Post the message on `stdin`.

    `prefix` is what the webhook URL must start with; `api_url` is where a token posts.

    Returns:
        The exit code: 0 posted, 1 Slack refused the post, 2 the secret file, the channel, or the message is not
        usable.
    """
    parser = argparse.ArgumentParser(
        prog="canopy-notify-slack",
        description=__doc__.split("\n", 1)[0],
    )
    parser.add_argument("--webhook-file", type=Path, default=None, help="default: " + str(default_webhook_file()))
    parser.add_argument("--channel", default=None, help="post with a bot token to this channel id, not a webhook")
    parser.add_argument("--token-file", type=Path, default=None, help="default: " + str(default_token_file()))
    parser.add_argument("--username", default=None, help="with --channel, the name to post as")
    parser.add_argument(
        "--icon-emoji",
        default=None,
        help="with --channel, the emoji to post with, such as :robot_face:",
    )
    parser.add_argument(
        "--threads",
        action="store_true",
        help="with --channel, post each ticket's, chore's, and review's messages in its own thread, a new one each day",
    )
    parser.add_argument(
        "--broadcast",
        action="append",
        choices=list(BROADCASTS),
        default=[],
        help="with --threads, also show in the channel a reply holding this; give it again for another: "
        + "; ".join(f"{k}, {v}" for k, v in BROADCASTS.items()),
    )
    args = parser.parse_args(argv)
    for given, flag in (
        (args.token_file, "--token-file"),
        (args.username, "--username"),
        (args.icon_emoji, "--icon-emoji"),
    ):
        if args.channel is None and given is not None:
            parser.error(f"{flag} needs --channel")
    if args.channel is None and args.threads:
        parser.error("--threads needs --channel")
    if args.broadcast and not args.threads:
        parser.error("--broadcast needs --threads")
    if args.channel is not None and args.webhook_file is not None:
        parser.error("--webhook-file and --channel are two ways to post; give one")
    send: Callable[[str, list[Block]], tuple[bool, str]]
    threaded: tuple[Send, str] | None = None
    try:
        if args.channel is None:
            send = functools.partial(post, read_webhook(args.webhook_file or default_webhook_file(), prefix=prefix))
        else:
            channel = check_channel(args.channel)
            to_channel = functools.partial(
                post_message,
                api_url,
                read_token(args.token_file or default_token_file()),
                channel,
                username=None if args.username is None else check_username(args.username),
                icon_emoji=None if args.icon_emoji is None else check_icon_emoji(args.icon_emoji),
            )
            send = to_channel
            threaded = (to_channel, channel) if args.threads else None
        parsed = read_message(stdin.read())
        if threaded is None:
            ok, reply = send(render(parsed), blocks(parsed))
        else:
            to_channel, channel = threaded
            threads = Threads.load(default_threads_file(), channel, str(parsed.get("repo") or ""))
            # Saved before anything is posted, so a file that cannot be written refuses the delivery whole.
            threads.save()
            ok, reply = post_threaded(parsed, to_channel, threads, frozenset(args.broadcast))
    except SinkError as e:
        print(f"canopy-notify-slack: {e}", file=sys.stderr)  # noqa: T201
        return 2
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
