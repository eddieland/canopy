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

With `--channel` and `--threads`, what is about one ticket or review goes in its own thread, a new one each day,
recorded in the sink's own state file, `$XDG_STATE_HOME/canopy/slack-threads.json`; the rest, a chore's results among
it, goes in the channel. The file keeps each thread for a week, so `canopy-connect-slack` can read the replies in it.
Each thread starts with a post of the same shape, naming what it is about, and everything about it is a reply.
A reply stays in its thread, unless `--broadcast` names what it holds, such as `--broadcast blocked` for a worker's
question: then it is shown in the channel too.

Exit codes: 0 posted (a 2xx reply, and `"ok": true` from the Web API); 1 the post failed, with Slack's reply on stderr;
2 the command line, the secret file, the channel, the threads file, or the message on stdin is not usable, saying which.
canopy retries anything but 0 on its next tick.

click for its command line (D025), and nothing from canopy: canopy runs it as a command, so the process that holds
the journal and enforces the guards never opens a connection or reads this secret (D035).
"""

from __future__ import annotations

import fcntl
import functools
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol

import canopy_http
import click

SLACK_PREFIX = "https://hooks.slack.com/"
SLACK_API_URL = "https://slack.com/api/chat.postMessage"
# A bot token: a user token (`xoxp-`) acts as the operator, with every scope they granted it.
TOKEN_PREFIX = "xoxb-"  # noqa: S105
#: The pause before each new try of a request that never left, or that Slack's rate limit refused; and, for a read, of
#: one Slack failed to answer: one try, then one more for each pause. A post Slack may have made is never sent again
#: (canopy-http), and canopy's retry of the delivery skips the posts it knows were made.
RETRY_PAUSES: Sequence[float] = (1.0, 3.0)
# How much of Slack's reply a failure prints.
_MAX_REPLY = 500
_MAX_LINES = 45
# A channel id (`C0123ABCD`) or a name (`#canopy`, `canopy`).
_CHANNEL = re.compile(r"#?[A-Za-z0-9._-]{1,80}")
# An emoji code (`:robot_face:`), with an optional skin tone (`:wave::skin-tone-3:`).
_EMOJI = re.compile(r"(?::[a-z0-9_+'-]{1,100}:){1,2}")
_MAX_USERNAME = 80
# A name canopy gives a reason, such as `needs_reviewer`; a chore's finding names its own, which stays as written.
_SNAKE = re.compile(r"[a-z]+(?:_[a-z]+)+")


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
    return _escaped(" ".join(str(text).split()))


def _escaped(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _reason(reason: object) -> str:
    """An attention item's reason, escaped, a snake_case name such as `needs_reviewer` in words: `needs reviewer`.

    Returns:
        The escaped Slack text.
    """
    text = escape(reason)
    return text.replace("_", " ") if _SNAKE.fullmatch(text) else text


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
    """Return the Slack text for one canopy `json` message, what Slack shows in a notification.

    A line naming the repository with counts, then a line per item or event in the order the blocks show them, each as
    its block's first line shows it, and a digest. A message of one item or event leads with it, so the notification
    says what happened.

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
            what = _added_shown(a).lines[0]
            lines.append(f"{what}: {escape(a.get('detail'))}" if a.get("detail") else what)
    events = _dicts(message.get("events"))
    if events:
        counts.append(f"{len(events)} event{'s' if len(events) != 1 else ''}")
    lines += [_event_shown(e).lines[0] for e in events if _needs_you(e)]
    if isinstance(attention, dict):
        lines += [_resolved(r) for r in _dicts(attention.get("resolved"))]
    lines += [_event_shown(e).lines[0] for e in events if not _needs_you(e)]
    omitted = message.get("omitted")
    digest = message.get("digest")
    if len(lines) == 1 and not omitted and not isinstance(digest, dict):
        return "\n".join([lines[0], f"*canopy* · {escape(repo)}"])
    if isinstance(omitted, int) and omitted:
        lines.append(f"_... and {omitted} more: see `canopy status`_")
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
    ("tasks", "tasks"),
    ("dry_run", "dry runs"),
)
# A URL in journal text: it runs to a space or an angle bracket, and starts a word or follows punctuation.
_URL = re.compile(r"(?<![\w/])https?://[^\s<>]+")
# What ends a sentence or wraps a URL, never the URL's own last character.
_TRAILING = ".,:;!?'\"`*_~"
_CLOSING = {")": "(", "]": "["}
# A link canopy sends to a page of its web UI: a URL's own characters only, so it needs no escaping but `&`, and no `|`
# can put a label of its own in it. The same class as `serve.url`'s check in canopy's config (`_UI_URL_RE`).
_PAGE = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+")
_MAX_PAGE = 2000
#: Each status a run, a chore's run, or a review's run ends with, as the emoji that leads its line.
_STATUS_EMOJI = {
    "done": ":white_check_mark:",
    "ok": ":white_check_mark:",
    "blocked": ":raising_hand:",
    "failed": ":x:",
    "unknown": ":grey_question:",
    "unpushed": ":warning:",
    "crashed": ":boom:",
    "timeout": ":hourglass:",
    "abandoned": ":wastebasket:",
    "stopped": ":octagonal_sign:",
}

# A pull request on GitHub, which its link shows by the name its own URL spells, `acme/api#7`: an owner, a repository,
# and a number, in characters that need no escaping, so the label cannot say anything the URL does not.
_GITHUB_PR = re.compile(r"https://github\.com/([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100})/pull/([0-9]{1,10})/?")

#: The events that need the operator, shown before the rest: the loop or a sink failing, a plan waiting on them, and a
#: forced push canopy made. The same as canopy sends a batching sink at once (DESIGN §20), with a new attention item
#: and a blocked run.
_NEEDS_YOU = frozenset({"loop.failing", "loop.sink_failing", "plan.proposed", "ci.kicked"})
#: The events whose `blocked` run asked the operator a question: a ticket's run's, and a task's.
_ASKING = frozenset({"run.ended", "task.ended"})

type Block = dict[str, object]
_DIVIDER: Block = {"type": "divider"}


@dataclass(frozen=True)
class _Shown:
    """One attention item or event as the message shows it."""

    #: Its lines, the first naming what happened, each escaped; an empty one is left out.
    lines: Sequence[str]
    #: What only adds to it, such as how long it has been open or which branch a run is on: in smaller type under the
    #: lines, each part escaped; an empty one is left out.
    aside: Sequence[str] = ()
    #: Whether it is routine, such as a run starting: one line in small type, so what needs the operator stands out.
    quiet: bool = False


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

    The punctuation around a URL stays out of its link: a trailing `.`, `:` or quote, and a `)` or `]` the URL does
    not open. A URL holding `|` stays text: in a link, what follows `|` is a label shown in the URL's place.

    Returns:
        The escaped Slack text.
    """
    flat = " ".join(str(text).split())
    out: list[str] = []
    at = 0
    for match in _URL.finditer(flat):
        url = _trimmed(match.group())
        if "|" in match.group() or url.endswith("//"):
            continue
        out += [_escaped(flat[at : match.start()]), f"<{_escaped(url)}>"]
        at = match.start() + len(url)
    return "".join([*out, _escaped(flat[at:])])


def _trimmed(url: str) -> str:
    """`url` without the punctuation that ends it in prose: what `_TRAILING` names, and an unopened `)` or `]`.

    Returns:
        The URL as it was meant.
    """
    while url:
        last = url[-1]
        if last in _TRAILING or (last in _CLOSING and url.count(last) > url.count(_CLOSING[last])):
            url = url[:-1]
        else:
            break
    return url


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


def _pr(url: object) -> str:
    """A link to a pull request: one on GitHub shows the name its URL spells, `acme/api#7`; another shows its URL.

    Returns:
        The Slack link, or `url` as `_linked` shows text when it is no GitHub PR.
    """
    text = str(url)
    if (match := _GITHUB_PR.fullmatch(text)) is None:
        return _linked(text)
    owner, repo, number = match.groups()
    return f"<{text}|{owner}/{repo}#{number}>"


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
    """Each name in `counts` after its count, the largest first: `23 ok, 1 error`.

    Returns:
        The escaped Slack text, or `none` when there are no counts.
    """
    if not isinstance(counts, dict) or not counts:
        return "none"
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1] if isinstance(kv[1], int) else 0, str(kv[0])))
    return ", ".join(f"{escape(v)} {_reason(k)}" for k, v in ordered)


def _run_started(e: Mapping[str, object]) -> _Shown:
    return _Shown(
        [
            (
                f":arrow_forward: {_named(e.get('ticket'), e.get('title'))} · {escape(e.get('run_kind'))} run "
                f"{escape(e.get('run'))} started"
            ),
        ],
        [f"attempt {escape(e.get('attempt'))} of {escape(e.get('limit'))}", f"`{escape(e.get('branch') or '-')}`"],
        quiet=True,
    )


def _run_ended(e: Mapping[str, object]) -> _Shown:
    prs = _lines(e.get("prs")) or ([str(e["pr"])] if e.get("pr") else [])
    run = f"{escape(e.get('run_kind'))} run {escape(e.get('run'))}"
    return _Shown(
        [
            _ended(e, f"{_named(e.get('ticket'), e.get('title'))} · {run}"),
            " · ".join(_pr(pr) for pr in prs),
            _linked(e.get("summary")) if e.get("summary") else "",
            _quote("Question", e.get("question")),
        ],
    )


def _findings(count: object) -> str:
    if not count:
        return "no findings"
    return f"{escape(count)} finding{'s' if count != 1 else ''}"


def _plan_proposed(e: Mapping[str, object]) -> _Shown:
    what = f"{_named(e.get('ticket'), e.get('title'))} · plan {escape(e.get('plan'))}"
    return _Shown(
        [f":clipboard: {what} waits on your approval"],
        [f"read it with `canopy show {escape(e.get('ticket'))}`"],
    )


def _plan_approved(e: Mapping[str, object]) -> _Shown:
    which = "feedback plan" if e.get("feedback") is True else "plan"
    return _Shown(
        [
            (
                f":ballot_box_with_check: {_named(e.get('ticket'), e.get('title'))} · {which} {escape(e.get('plan'))} "
                "approved by its planner"
            ),
            _quote("Why", e.get("reason")),
        ],
    )


def _follow_ups_filed(e: Mapping[str, object]) -> _Shown:
    given = e.get("follow_ups")
    filed: list[tuple[str, object]] = [(str(k), v) for k, v in given.items()] if isinstance(given, dict) else []
    count = e.get("count")
    total = count if isinstance(count, int) and count > len(filed) else len(filed)
    named = [f"*{escape(k)}*" + (f" ({escape(v)})" if v else "") for k, v in filed]
    if total > len(filed):
        named.append(f"{total - len(filed)} more")
    return _Shown(
        [
            (
                f":seedling: {_named(e.get('ticket'), e.get('title'))} · run {escape(e.get('run'))} filed {total} "
                f"follow-up{'s' if total != 1 else ''}"
            ),
            ", ".join(named),
        ],
        ["label or `canopy start` each one you want worked"],
    )


#: How a `ci.flaky` event's `cause`, the worker's estimate of where the check failed, reads.
_FLAKY_CAUSES = {
    "test": "likely a flaky test",
    "runner": "likely the CI runner",
    "service": "likely a service the job calls",
}


def _ci_flaky(e: Mapping[str, object]) -> _Shown:
    kicked = _lines(e.get("kicked"))
    what = f"{_named(e.get('ticket'), e.get('title'))} · run {escape(e.get('run'))} left a failed check as flaky"
    cause = e.get("cause")
    if isinstance(cause, str) and cause in _FLAKY_CAUSES:
        what = f"{what}, {_FLAKY_CAUSES[cause]}"
    elif e.get("other_cause"):
        what = f"{what}, cause given as '{escape(e.get('other_cause'))}', not one canopy knows"
    if kicked:
        first = f":repeat: {what}; canopy pushed {', '.join(f'`{escape(r)}`' for r in kicked)} again to rerun it"
        aside = [_linked(e.get("note")) if e.get("note") else ""]
    else:
        first = f":grey_question: {what}"
        aside = ["rerun it, or `canopy reply` that it is real", _linked(e.get("note")) if e.get("note") else ""]
    return _Shown(
        [first, " · ".join(_pr(pr) for pr in _lines(e.get("prs"))), _quote("Why", e.get("estimate"))],
        aside,
    )


def _ci_kicked(e: Mapping[str, object]) -> _Shown:
    what = f"{_named(e.get('ticket'), e.get('title'))} · run {escape(e.get('run'))}"
    moved = f"`{escape(str(e.get('from_head'))[:12])}` → `{escape(str(e.get('to_head'))[:12])}`"
    return _Shown(
        [
            (
                f":warning: {what}: canopy force-pushed `{escape(e.get('branch'))}` in `{escape(e.get('repo'))}` "
                "to rerun a check left as flaky"
            ),
            _pr(e.get("pr")) if e.get("pr") else "",
        ],
        [moved, f"kick {escape(e.get('kick'))} of {escape(e.get('limit'))}"],
    )


def _task_ended(e: Mapping[str, object]) -> _Shown:
    head = str(e.get("head") or "")[:12]
    tickets = _lines(e.get("tickets"))
    return _Shown(
        [
            _ended(e, f"*task {escape(e.get('task'))}* · run {escape(e.get('run'))}"),
            _pr(e.get("pr")) if e.get("pr") else "",
            _linked(e.get("summary")) if e.get("summary") else "",
            _quote("Question", e.get("question")),
            f"filed {', '.join(f'*{escape(t)}*' for t in tickets)}" if tickets else "",
        ],
        [f"`{escape(e.get('branch'))}` at `{escape(head)}`" if e.get("branch") and head else ""],
    )


def _chore_ended(e: Mapping[str, object]) -> _Shown:
    return _Shown(
        [
            _ended(e, f"*chore:{escape(e.get('chore'))}* · run {escape(e.get('run'))}")
            + f" · {_findings(e.get('findings'))}",
            _linked(e.get("summary")) if e.get("summary") else "",
        ],
    )


def _review_ended(e: Mapping[str, object]) -> _Shown:
    ticket = f"{_named(e.get('ticket'), e.get('title'))} · " if e.get("ticket") else ""
    verdict = " ".join(escape(x) for x in (e.get("verdict"), e.get("impact")) if x)
    counted = f" · {_findings(e.get('findings'))}" if verdict else ""
    return _Shown(
        [
            _ended(e, f"{ticket}review run {escape(e.get('run'))}") + (f": {verdict}{counted}" if verdict else ""),
            _pr(e.get("pr")) if e.get("pr") else "",
        ],
    )


def _loop_failing(e: Mapping[str, object]) -> _Shown:
    return _Shown(
        [f":rotating_light: *The loop is failing:* {escape(e.get('count'))} ticks in a row ended other than ok"],
        [f"latest tick {escape(e.get('tick'))} ended {escape(e.get('status'))}", f"log `{escape(e.get('log'))}`"],
    )


def _loop_recovered(e: Mapping[str, object]) -> _Shown:
    return _Shown([f":white_check_mark: *The loop recovered* after {escape(e.get('failed'))} failed ticks"])


def _sink_failing(e: Mapping[str, object]) -> _Shown:
    return _Shown(
        [f":warning: *Sink {escape(e.get('sink'))} is failing:* 3 deliveries in a row"],
        [f"`{escape(e.get('error'))}`"],
    )


def _budget_reached(e: Mapping[str, object]) -> _Shown:
    spent, projected, percent = e.get("spent"), e.get("projected"), e.get("percent")
    so_far = _usd(spent) if isinstance(spent, int | float) else "-"
    pace = f"; on pace for {_usd(projected)}" if isinstance(projected, int | float) else ""
    month, budget = escape(e.get("month")), escape(e.get("budget"))
    what = "its budget" if percent == 100 else f"{escape(percent)}% of its budget"  # noqa: PLR2004  (the budget whole)
    return _Shown([f":moneybag: *Spend for {month} reached {what}:* {so_far} of ${budget}{pace}"], _budget_parts(e))


def _budget_parts(e: Mapping[str, object]) -> list[str]:
    """What a `loop.budget_reached` event's spend is made of: canopy's runs, and the sessions outside canopy.

    Returns:
        Canopy's runs' part, then the part outside canopy with when canopy last read the runtime's sessions, or last
        tried to when that read failed, or that it has not; none for an event from a canopy that did not send the parts.
    """
    runs, outside, read = e.get("runs"), e.get("outside"), e.get("sessions_read_at")
    if not isinstance(runs, int | float):
        return []
    if read is None or not isinstance(outside, int | float):
        return [f"canopy's runs {_usd(runs)}", "outside canopy not read yet"]
    how = "the last read of sessions failed" if e.get("sessions_read") == "failed" else "sessions read"
    return [f"canopy's runs {_usd(runs)}", f"outside canopy {_usd(outside)}", f"{how} {_when(read)}"]


def _test(e: Mapping[str, object]) -> _Shown:
    return _Shown([f":test_tube: {_linked(e.get('text'))}"])


def _reply_recorded(e: Mapping[str, object]) -> _Shown:
    return _Shown(
        [
            f":speech_balloon: Your reply from Slack is on {_named(e.get('ticket'), e.get('title'))}",
            _quote("Reply", e.get("body")),
        ],
    )


def _reply_refused(e: Mapping[str, object]) -> _Shown:
    on = f" on *{escape(e.get('ticket'))}*" if e.get("ticket") else ""
    return _Shown(
        [f":no_entry_sign: canopy took nothing from this reply{on}: {_linked(e.get('reason'))}"],
        [f"({escape(e.get('guard'))})"],
    )


# Each event kind as shown, its first line naming what happened: the event's page in the web UI is linked after it.
_EVENTS: dict[str, Callable[[Mapping[str, object]], _Shown]] = {
    "run.started": _run_started,
    "run.ended": _run_ended,
    "plan.proposed": _plan_proposed,
    "plan.approved": _plan_approved,
    "follow_ups.filed": _follow_ups_filed,
    "ci.flaky": _ci_flaky,
    "ci.kicked": _ci_kicked,
    "task.ended": _task_ended,
    "chore.ended": _chore_ended,
    "review.ended": _review_ended,
    "loop.failing": _loop_failing,
    "loop.recovered": _loop_recovered,
    "loop.sink_failing": _sink_failing,
    "loop.budget_reached": _budget_reached,
    "reply.recorded": _reply_recorded,
    "reply.refused": _reply_refused,
    "test": _test,
}


def _event(e: Mapping[str, object], *, fold: bool) -> list[Block]:
    """One event as blocks built from its fields. A kind this sink does not know shows its text-format line.

    Returns:
        The blocks, the first line linking to the event's page in the web UI when canopy sent one.
    """
    return _shown_blocks(_event_shown(e), e.get("ui"), fold=fold)


def _event_shown(e: Mapping[str, object]) -> _Shown:
    """One event as shown, its first line naming what happened. A kind this sink does not know shows its text line.

    Returns:
        The escaped Slack lines, at least one, and what is set aside under them.
    """
    build = _EVENTS.get(str(e.get("kind")))
    return build(e) if build is not None else _Shown([_linked(e.get("line") or e.get("kind"))])


def _shown_blocks(shown: _Shown, page: object, *, fold: bool) -> list[Block]:
    """`shown` as a section, its aside as a context under it in smaller type, or, with `fold`, its section's last line.

    A quiet one is a context alone, its aside on its first line.

    Returns:
        The section, and the context when there is an aside and it is not folded; or, quiet, the context.
    """
    first, *rest = shown.lines
    aside = " · ".join(part for part in shown.aside if part)
    if shown.quiet:
        return [_context("\n".join([_with_open(" · ".join(x for x in (first, aside) if x), page), *rest]))]
    section = _section(_with_open(first, page), *rest, *([aside] if aside and fold else []))
    return [section, _context(aside)] if aside and not fold else [section]


def _needs_you(e: Mapping[str, object]) -> bool:
    """Whether an event needs the operator: the loop or a sink failing, a plan to approve, or a run's question.

    Returns:
        True when it does.
    """
    kind = e.get("kind")
    return kind in _NEEDS_YOU or (kind in _ASKING and e.get("status") == "blocked")


def _resolved(r: Mapping[str, object]) -> str:
    """A resolved attention item, struck through, `(dismissed)` when the operator dismissed it.

    Returns:
        The escaped Slack line.
    """
    subject = _titled(_subject(r.get("ticket"), r.get("repo")), r.get("title"))
    dismissed = " (dismissed)" if r.get("dismissed") is True else ""
    return f":heavy_check_mark: ~{subject}~ {_reason(r.get('reason'))}{dismissed}"


def _added(a: Mapping[str, object], *, fold: bool) -> list[Block]:
    """A new attention item: what it is about and why, linking to its page in the web UI, then its detail and age.

    Returns:
        The blocks.
    """
    return _shown_blocks(_added_shown(a), a.get("ui"), fold=fold)


def _added_shown(a: Mapping[str, object]) -> _Shown:
    what = f":bell: {_named(_subject(a.get('ticket'), a.get('repo')), a.get('title'))} · {_reason(a.get('reason'))}"
    return _Shown(
        [what, _linked(a.get("detail")) if a.get("detail") else ""],
        [f"open since {_when(a.get('since'))}" if a.get("since") else ""],
    )


def _digest(digest: Mapping[str, object]) -> list[Block]:
    ticks = digest.get("ticks")
    total = sum(n for n in ticks.values() if isinstance(n, int)) if isinstance(ticks, dict) else 0
    given = digest.get("attention")
    attention: dict[str, object] = {str(k): v for k, v in given.items()} if isinstance(given, dict) else {}
    needs_you = "nothing"
    if attention.get("open"):
        needs_you = f"{escape(attention.get('open'))} open"
        needs_you += f", oldest {escape(attention.get('oldest'))}" if attention.get("oldest") else ""
        needs_you += f"\n{_counted(attention.get('by_reason'))}"
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
            "text": _mrkdwn(f":bar_chart: *Digest* since {_when(digest.get('since'))}"),
            "fields": [_mrkdwn(f) for f in fields],
        },
    ]
    runs = [
        f"{_STATUS_EMOJI['done']} {_named(d.get('ticket'), d.get('title'))}"
        + (f" · {_pr(d.get('pr'))}" if d.get("pr") else "")
        for d in _dicts(digest.get("done"))[:_DIGEST_LISTED]
    ]
    runs += [
        f"{_STATUS_EMOJI['blocked']} {_named(b.get('ticket'), b.get('title'))} · blocked"
        for b in _dicts(digest.get("blocked"))[:_DIGEST_LISTED]
    ]
    if runs:
        out.append(_section(*runs))
    return out


# What the digest's span cost: the total, then each kind that reported a cost, in the order canopy's text lists them,
# the idle ticks' part of the overseer's beside it.
def _spent(spent: Mapping[str, object]) -> str:
    total = spent.get("total")
    if not isinstance(total, int | float):
        return "none reported"
    idle = spent.get("idle")
    parts = [
        f"{name} {_usd(usd)}"
        + (f" (idle {_usd(idle)})" if kind == "overseer" and isinstance(idle, int | float) and idle else "")
        for kind, name in _SPENT
        if isinstance(usd := spent.get(kind), int | float)
    ]
    return f"*{_usd(total)}*" + (f"\n{', '.join(parts)}" if parts else "")


def _usd(usd: float) -> str:
    return f"${usd:.2f}"


def blocks(message: Mapping[str, object], *, header: bool = True) -> list[Block]:
    """Return Block Kit blocks for one canopy `json` message, built from its fields rather than its text lines.

    A line in small type naming the repository directory and counting what follows, a section per attention item and
    per event with what only adds to it in small type under it, the resolved items together, and the digest as
    fields. At most Slack's 50 blocks: what would be set under an item goes in its section instead when that keeps
    every item, and the last block says how many were left out when nothing does. Without `header`, as a post in a
    ticket's thread is, the message starts at its first item.

    Returns:
        The blocks, in the order Slack shows them.
    """
    counts, body = _body(message, fold=False)
    if len(body) + 1 > _MAX_BLOCKS:
        counts, body = _body(message, fold=True)
    repo = Path(str(message.get("repo") or "")).name or "canopy"
    byline = _with_open(" · ".join([f"*canopy* · {escape(repo)}", *counts]), message.get("ui"))
    out = [_context(byline), *body] if header else body
    omitted = message.get("omitted")
    more = omitted if isinstance(omitted, int) else 0
    if len(out) + (1 if more else 0) > _MAX_BLOCKS:
        more += len(out) - (_MAX_BLOCKS - 1)
        out = out[: _MAX_BLOCKS - 1]
    if more:
        out.append(_context(f"_… and {more} more: see `canopy status`_"))
    return out


def _body(message: Mapping[str, object], *, fold: bool) -> tuple[list[str], list[Block]]:
    """The counts the byline shows, and the blocks after it: what needs the operator, the rest, then the digest.

    What needs the operator is the new attention items, then the events `_needs_you` names, in the order canopy sent
    them; the rest is the resolved items, then the other events.

    Returns:
        The counts, and the blocks, each item's aside folded into its section with `fold`.
    """
    counts: list[str] = []
    given = message.get("attention")
    attention: dict[str, object] = {str(k): v for k, v in given.items()} if isinstance(given, dict) else {}
    added, resolved = _dicts(attention.get("added")), _dicts(attention.get("resolved"))
    if added or resolved:
        counts.append(f"{len(added)} new · {len(resolved)} resolved · {escape(attention.get('open', 0))} open")
    events = _dicts(message.get("events"))
    if events:
        counts.append(f"{len(events)} event{'s' if len(events) != 1 else ''}")
    first = [block for a in added for block in _added(a, fold=fold)]
    first += [block for e in events if _needs_you(e) for block in _event(e, fold=fold)]
    rest = [_section("*Resolved*", *(_resolved(r) for r in resolved))] if resolved else []
    rest += [block for e in events if not _needs_you(e) for block in _event(e, fold=fold)]
    body = [*first, *([_DIVIDER] if first and rest else []), *rest]
    digest = message.get("digest")
    if isinstance(digest, dict):
        counts.append("digest")
        body += [_DIVIDER] if body else []
        body += _digest({str(k): v for k, v in digest.items()})
    return counts, body


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
    client = slack_client(url, headers)
    try:
        # The whole reply: `post_message` parses it, and a successful `chat.postMessage` reply runs long.
        return True, client.send("POST", url, body=payload).text
    except canopy_http.HttpError as e:
        return False, str(e)


def slack_client(url: str, headers: Mapping[str, str]) -> canopy_http.Client:
    """A client for Slack at `url`'s origin, a webhook's or the Web API's, sending `headers` there alone (canopy-http).

    Returns:
        The client.
    """
    return canopy_http.Client(url, name="Slack", headers=headers, retry=canopy_http.Retry(pauses=RETRY_PAUSES))


# Threads, with `--threads`

#: What `--broadcast` can show in the channel from a thread's reply, and what each is.
BROADCASTS: Mapping[str, str] = {
    "attention": "a new attention item",
    "plan": "a plan to approve",
    "blocked": "a run that ended blocked, waiting on an answer",
}

#: What a chore's findings' attention items name as their ticket, before the chore's name.
_CHORE = "chore:"
#: What `_thread` names a part answering the operator's own message by, before its `ts`: never a ticket's key.
_ANSWER = "answer:"
#: How many days, today's among them, the threads file keeps a thread: as far back as `canopy-connect-slack` reads.
KEEP_DAYS = 7
#: The threads file's format: 2 added each subject's earlier threads, which a sink that writes 1 drops.
_VERSION = 2
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
    """For one channel and repository: each thread the sink posts in, its earlier ones, and what a delivery posted.

    The file holds a scope for each channel and repository, so sinks and workspaces sharing it keep their own, and a
    save replaces only its own scope. Losing the file costs nothing worse than new threads, and replies in the old ones
    no longer read.
    """

    path: Path
    #: The channel and repository, as a JSON list: the key of this record's part of the file.
    scope: str
    #: What a thread is about, such as a ticket key, to the day its latest thread was started and its first `ts`.
    threads: dict[str, tuple[str, str]]
    #: Fingerprints of the items posted by a delivery that has not yet posted whole, so canopy's retry skips them.
    posted: set[str]
    #: What a thread is about to its threads before the latest, each its day and first `ts`, oldest first, for
    #: `KEEP_DAYS`.
    earlier: dict[str, list[tuple[str, str]]] = field(default_factory=dict[str, list[tuple[str, str]]])

    @classmethod
    def load(cls, path: Path, channel: str, repo: str) -> Threads:
        """Read the scope of `channel` and `repo` from `path`: empty if missing or not what this sink wrote.

        A version 1 file, which has no earlier threads, reads as one whose earlier threads are none.

        Returns:
            The threads and fingerprints the scope holds.

        Raises:
            SinkError: `path` is there but cannot be read, or is not a regular file.
        """
        scope = json.dumps([channel, repo])
        given = _scopes(path).get(scope)
        mine: dict[str, object] = {str(k): v for k, v in given.items()} if isinstance(given, dict) else {}
        recorded = mine.get("threads")
        threads = {
            str(key): started
            for key, thread in (recorded.items() if isinstance(recorded, dict) else ())
            if (started := _started(thread)) is not None
        }
        before = mine.get("earlier")
        earlier = {
            str(key): kept
            for key, listed in (before.items() if isinstance(before, dict) else ())
            if (kept := [s for t in (listed if isinstance(listed, list) else ()) if (s := _started(t)) is not None])
        }
        fingerprints = mine.get("posted")
        posted = {f for f in fingerprints if isinstance(f, str)} if isinstance(fingerprints, list) else set()
        return cls(path, scope, threads, posted, earlier)

    def start(self, key: str, day: str, ts: str) -> None:
        """Record the thread started for `key` on `day`, keeping the one it replaces among the earlier."""
        replaced = self.threads.get(key)
        if replaced is not None and replaced != (day, ts):
            self.earlier.setdefault(key, []).append(replaced)
        self.threads[key] = (day, ts)

    def recent(self, today: str, days: int) -> dict[str, list[tuple[str, str]]]:
        """Each subject's threads started in the `days` up to `today`, today's among them.

        Returns:
            Each subject's threads, each its day and first `ts`, oldest first; a subject with none is left out.
        """
        since = _days_before(today, days - 1)
        found: dict[str, list[tuple[str, str]]] = {}
        for key in sorted({*self.threads, *self.earlier}):
            listed = [*self.earlier.get(key, ()), *([self.threads[key]] if key in self.threads else [])]
            if kept := [thread for thread in listed if since <= thread[0] <= today]:
                found[key] = kept
        return found

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
            "earlier": {
                key: [{"day": day, "ts": ts} for day, ts in listed] for key, listed in sorted(self.earlier.items())
            },
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
                    json.dump({"version": _VERSION, "scopes": dict(sorted(scopes.items()))}, f)
                    f.write("\n")
                tmp.replace(self.path)
            finally:
                os.close(lock)
        except OSError as e:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
            raise SinkError(f"cannot write the threads file {self.path}: {e.strerror or e}") from e

    def finish(self, day: str) -> None:
        """A delivery has posted whole: forget what it posted, and keep each thread started before `day` as an earlier.

        An earlier thread started before the `KEEP_DAYS` up to `day` is forgotten.

        Raises:
            SinkError: The file cannot be written.
        """
        self.posted.clear()
        # ISO dates order as strings. A later day's thread stays, should a delivery carry an earlier clock.
        for key, thread in sorted(self.threads.items()):
            if thread[0] < day:
                del self.threads[key]
                if thread not in self.earlier.get(key, ()):
                    self.earlier.setdefault(key, []).append(thread)
        since = _days_before(day, KEEP_DAYS - 1)
        self.earlier = {
            key: kept for key, listed in self.earlier.items() if (kept := [t for t in listed if t[0] >= since])
        }
        self.save()


def _started(thread: object) -> tuple[str, str] | None:
    """A thread as the file records it, `{"day": ..., "ts": ...}`: its day and first `ts`, if both are what they seem.

    Returns:
        The day and `ts`, or None.
    """
    day, ts = (thread.get("day"), thread.get("ts")) if isinstance(thread, dict) else (None, None)
    if not isinstance(day, str) or not isinstance(ts, str) or not _TS.fullmatch(ts):
        return None
    try:
        date.fromisoformat(day)
    except ValueError:
        return None
    return day, ts


def _days_before(day: str, days: int) -> str:
    return (date.fromisoformat(day) - timedelta(days=days)).isoformat()


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

    What is about a ticket or a review's PR goes in its thread for the day, which a post of its own starts in the
    channel, naming what the thread is about, before the first item. A reply stays in its thread, unless it holds one
    of `broadcast` (`BROADCASTS` names them): then it is shown in the channel too. A reply canopy refused is answered
    under the operator's own message, in no thread of the sink's. The rest, loop events, chores' results, and the
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
        answered = _answered(part.thread)
        started = threads.threads.get(part.thread) if part.thread is not None and answered is None else None
        ts = answered or (started[1] if started is not None and started[0] == day else None)
        if part.thread is not None and ts is None:
            ok, reply = send(*_starter(part, message, day))
            if not ok:
                return ok, reply
            # Recorded at once, so a retry after a refused reply posts in this thread rather than starting another.
            if (ts := _ts(reply)) is not None:
                threads.start(part.thread, day, ts)
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

    A header names the ticket and its title, or the review; a line under it the repository, the day, and a review's
    PR. Everything about it that day, the first item included, is a reply under it.

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
    about = [f"*canopy* · {escape(repo)} · updates from {_day_named(day)} in the thread", _pr(pr) if pr else ""]
    header: Block = {"type": "header", "text": {"type": "plain_text", "text": named[:_MAX_HEADER]}}
    return escape(named), [header, _context(*(a for a in about if a))]


def _day_named(day: str) -> str:
    """`day`, an ISO date, as a person names it: `Thu, Sep 24`.

    Returns:
        The day, or `day` escaped if it is not an ISO date.
    """
    try:
        named = date.fromisoformat(day)
    except ValueError:
        return escape(day)
    # The C locale's names, since the sink never sets one: the same words on every machine.
    return f"{named:%a, %b} {named.day}"


def split(message: Mapping[str, object], skip: AbstractSet[str] = frozenset()) -> list[Part]:
    """Divide `message` into posts: the channel's first, then a thread's each, in the order the message names them.

    An item goes in its ticket's thread, and a review's run in its PR's; anything else, such as a loop event, a chore's
    run or its findings' attention items, a repository's attention item, or the digest, in the channel. An item whose
    fingerprint is in `skip` is left out, and so is a post left with nothing.

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
    answered = item.get("ts")
    if kind == "reply.refused" and isinstance(answered, str) and _TS.fullmatch(answered):
        return _ANSWER + answered
    if kind == "review.ended":
        return f"review:{item['pr']}" if item.get("pr") else None
    ticket = item.get("ticket")
    # A chore's results stay in the channel: the operator reads them as they come, not in a thread of their own.
    if kind == "chore.ended" or not ticket or str(ticket).startswith(_CHORE):
        return None
    return str(ticket)


def _answered(thread: str | None) -> str | None:
    """The `ts` of the operator's message a part answers, when it is one `_thread` names so, else None.

    Returns:
        The `ts`.
    """
    if thread is None or not thread.startswith(_ANSWER):
        return None
    return thread.removeprefix(_ANSWER)


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


@dataclass(frozen=True)
class Slack:
    """Where the sink may post: Slack's own, unless a test gives its own."""

    #: What the webhook URL must start with.
    prefix: str = SLACK_PREFIX
    #: Where a token posts.
    api_url: str = SLACK_API_URL


@click.command("canopy-notify-slack", context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--webhook-file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="The incoming webhook's URL. Default: $XDG_CONFIG_HOME/canopy/slack-webhook, or ~/.config/canopy/.",
)
@click.option("--channel", default=None, help="Post with a bot token to this channel id, not a webhook.")
@click.option(
    "--token-file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="With --channel, the bot token. Default: $XDG_CONFIG_HOME/canopy/slack-token, or ~/.config/canopy/.",
)
@click.option("--username", default=None, help="With --channel, the name to post as.")
@click.option("--icon-emoji", default=None, help="With --channel, the emoji to post with, such as :robot_face:.")
@click.option(
    "--threads",
    is_flag=True,
    help="With --channel, post each ticket's and review's messages in its own thread, a new one each day.",
)
@click.option(
    "--broadcast",
    "broadcasts",
    multiple=True,
    type=click.Choice(list(BROADCASTS)),
    help="With --threads, also show in the channel a reply holding this; give it again for another: "
    + "; ".join(f"{k}, {v}" for k, v in BROADCASTS.items())
    + ".",
)
@click.pass_context
def main(
    ctx: click.Context,
    *,
    webhook_file: Path | None,
    channel: str | None,
    token_file: Path | None,
    username: str | None,
    icon_emoji: str | None,
    threads: bool,
    broadcasts: tuple[str, ...],
) -> None:
    """Post the canopy message on stdin to Slack: canopy's Slack sink (DESIGN §20).

    It posts to an incoming webhook, or with --channel, with a bot token. Each secret is read from a file that is
    yours alone.
    """
    slack = ctx.find_object(Slack) or Slack()
    _check_options(ctx.params)
    send: Callable[[str, list[Block]], tuple[bool, str]]
    threaded: tuple[Send, str] | None = None
    try:
        if channel is None:
            send = functools.partial(post, read_webhook(webhook_file or default_webhook_file(), prefix=slack.prefix))
        else:
            checked = check_channel(channel)
            to_channel = functools.partial(
                post_message,
                slack.api_url,
                read_token(token_file or default_token_file()),
                checked,
                username=None if username is None else check_username(username),
                icon_emoji=None if icon_emoji is None else check_icon_emoji(icon_emoji),
            )
            send = to_channel
            threaded = (to_channel, checked) if threads else None
        parsed = read_message(sys.stdin.read())
        if threaded is None:
            ok, reply = send(render(parsed), blocks(parsed))
        else:
            to_channel, checked = threaded
            recorded = Threads.load(default_threads_file(), checked, str(parsed.get("repo") or ""))
            # Saved before anything is posted, so a file that cannot be written refuses the delivery whole.
            recorded.save()
            ok, reply = post_threaded(parsed, to_channel, recorded, frozenset(broadcasts))
    except SinkError as e:
        print(f"canopy-notify-slack: {e}", file=sys.stderr)  # noqa: T201
        ctx.exit(2)
    if not ok:
        print(f"canopy-notify-slack: Slack refused the post: {reply[:_MAX_REPLY]}", file=sys.stderr)  # noqa: T201
        ctx.exit(1)


def _check_options(given: Mapping[str, object]) -> None:
    """Refuse an option given without the one it needs, and a webhook given with a channel.

    Raises:
        UsageError: One is.
    """
    channel = given.get("channel")
    for name, flag in (("token_file", "--token-file"), ("username", "--username"), ("icon_emoji", "--icon-emoji")):
        if channel is None and given.get(name) is not None:
            raise click.UsageError(f"{flag} needs --channel")
    if channel is None and given.get("threads"):
        raise click.UsageError("--threads needs --channel")
    if given.get("broadcasts") and not given.get("threads"):
        raise click.UsageError("--broadcast needs --threads")
    if channel is not None and given.get("webhook_file") is not None:
        raise click.UsageError("--webhook-file and --channel are two ways to post; give one")
