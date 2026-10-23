"""`canopy-connect-slack`: reads the replies people wrote in the Slack sink's ticket threads (ROADMAP M64).

Run as `canopy-connect-slack --channel C0123ABCD`, on the channel the sink posts to with `--threads`, given as the
sink's own `--channel` is, since the sink files its threads under that: by its id, for both, as the Web API reads only
an id. It uses the sink's bot token file (`--token-file`, by default `$XDG_CONFIG_HOME/canopy/slack-token`), held to
the sink's checks; the bot needs the channel's history scope, `channels:history` or, for a private channel,
`groups:history`, beside the sink's `chat:write`.

On stdin, one JSON object: `repo`, the repository canopy's messages name, which with the channel picks the sink's
threads, and optionally `tickets`, the ticket keys to read; without it every ticket's threads are read. It reads the
sink's threads file and never writes it. For each ticket's threads started in the last `--days`, today's among them, it
calls `conversations.replies` to the last page and prints, in DESIGN §30's shape, a `reply` line for each message a
person wrote in the thread: the ticket, the thread's and the message's `ts`, the Slack user id, the time, and the text
as Slack holds it, its own escaping undone, whole. A thread's first post, the sink's own, is not printed, and neither is
a message with no user, from a bot (`bot_id`, which a bot posting under a person's name still carries), or with a
`subtype`, such as a join or a file comment. An edited message is printed as it reads now; canopy records a message by
its `ts`, once, so an edit after that changes nothing. A review's thread is not read, nor the channel itself.

Last, an `end` line naming the tickets whose threads were each read to the last page, `tickets`, and those it could
not read, `unread`. A thread that could not be read prints nothing for its ticket but its error on stderr, so a cut-off
read never looks like a thread nobody answered. A thread Slack no longer has, its first post deleted, is read as one
with no replies, so it does not fail every run until it ages out. Nothing is posted to Slack.

Exit codes: 0 everything was read; 1 something was not, and the `end` line names what was; 2 the command line, the
token file, the threads file, or stdin is not usable, and nothing was read.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TextIO

import click

from canopy_notify_slack import (
    KEEP_DAYS,
    TIMEOUT_SECONDS,
    SinkError,
    Threads,
    check_channel,
    default_threads_file,
    default_token_file,
    read_token,
)

SLACK_REPLIES_URL = "https://slack.com/api/conversations.replies"
#: How many of a thread's messages a page asks for: the most Slack recommends.
PAGE = 200
#: How many pages one thread may take before it counts as not read: a thread canopy started is not this long.
MAX_PAGES = 50
#: A ticket's key, as canopy reads one (DESIGN §17). A review's thread, `review:URL`, is not one.
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}")
#: A person's Slack user id: `U...`, or `W...` on an Enterprise Grid.
_USER = re.compile(r"[UW][A-Z0-9]{2,30}")
#: A message's `ts`.
_TS = re.compile(r"\d{1,20}\.\d{1,20}")
#: Slack's error for a thread it no longer has.
_GONE = "thread_not_found"
#: A link or a mention in a message's text, as Slack writes it: `<https://x|label>`, `<@U123>`, `<#C123|name>`.
_ANGLED = re.compile(r"<([^<>|]*)(?:\|([^<>]*))?>")


@dataclass(frozen=True)
class Reach:
    """Where the reader reads Slack, and what day it is: Slack's own and the clock's, unless a test gives its own."""

    #: The Web API's `conversations.replies`.
    replies_url: str = SLACK_REPLIES_URL
    #: Today's date, in the operator's time zone, as the sink names a thread's day.
    today: Callable[[], date] = lambda: datetime.now(UTC).astimezone().date()


@click.command("canopy-connect-slack", context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--channel", required=True, help="The sink's own --channel, the id of the channel it threads in.")
@click.option(
    "--token-file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="The sink's bot token. Default: $XDG_CONFIG_HOME/canopy/slack-token, or ~/.config/canopy/.",
)
@click.option(
    "--days",
    type=click.IntRange(1, KEEP_DAYS),
    default=3,
    show_default=True,
    help="Read the threads started this many days back, today's among them.",
)
@click.pass_context
def main(ctx: click.Context, channel: str, token_file: Path | None, days: int) -> None:
    """Read the replies in the Slack sink's ticket threads into canopy's journal (ROADMAP M64).

    The request is one JSON object on stdin; what was read is JSON lines on stdout, the `end` line last.
    """
    reach = ctx.find_object(Reach) or Reach()
    try:
        checked = check_channel(channel)
        repo, tickets = _request(sys.stdin.read())
        token = read_token(token_file or default_token_file())
        threads = Threads.load(default_threads_file(), checked, repo)
    except SinkError as e:
        _say(str(e))
        ctx.exit(2)
    asked = threads.recent(reach.today().isoformat(), days)
    reader = _Reader(reach.replies_url, token, checked, sys.stdout)
    for key, started in asked.items():
        if _KEY.fullmatch(key) and (tickets is None or key in tickets):
            reader.read(key, [ts for _, ts in started])
    _emit(sys.stdout, {"kind": "end", "tickets": reader.whole, "unread": reader.unread})
    ctx.exit(1 if reader.failed else 0)


def _request(stdin: str) -> tuple[str, AbstractSet[str] | None]:
    """Read the request: the repository, and the tickets to read, if it names them.

    Returns:
        The repository, and the tickets, or None for every ticket.

    Raises:
        SinkError: stdin is not a JSON object, or its `repo` or `tickets` is not usable.
    """
    try:
        raw: object = json.loads(stdin)
    except json.JSONDecodeError as e:
        raise SinkError(f"stdin is not a JSON object: {e}") from e
    if not isinstance(raw, dict):
        raise SinkError('stdin is not a JSON object: {"repo": "/path/to/workspace"}')
    repo = raw.get("repo")
    if not isinstance(repo, str):
        raise SinkError("stdin's repo must be a string: the repository canopy's messages name")
    tickets = raw.get("tickets")
    if tickets is None:
        return repo, None
    if not isinstance(tickets, list) or not all(isinstance(t, str) and _KEY.fullmatch(t) for t in tickets):
        raise SinkError('stdin\'s tickets must be a list of ticket keys: {"tickets": ["PROJ-1"]}')
    return repo, frozenset(tickets)


@dataclass
class _Reader:
    """One run's reads: the tickets it printed whole, and those it could not read."""

    url: str
    token: str
    channel: str
    stdout: TextIO
    #: The tickets each of whose threads was read to the last page, in the order read.
    whole: list[str] = field(default_factory=list[str])
    #: The tickets one of whose threads could not be read, in the order read.
    unread: list[str] = field(default_factory=list[str])

    @property
    def failed(self) -> bool:
        """Whether a ticket's threads could not be read."""
        return bool(self.unread)

    def read(self, key: str, threads: Sequence[str]) -> None:
        """Read each of a ticket's threads to the last page, and print its replies only if every one was."""
        lines: list[dict[str, object]] = []
        for thread in threads:
            try:
                lines += [line for m in self._messages(thread) if (line := _reply(key, thread, m)) is not None]
            except SinkError as e:
                self.unread.append(key)
                _say(f"cannot read {key}'s thread {thread}: {e}")
                return
        for line in lines:
            _emit(self.stdout, line)
        self.whole.append(key)

    def _messages(self, thread: str) -> list[Mapping[str, object]]:
        """Every message of a thread, page by page, to the last.

        Returns:
            The messages, the thread's first post among them, in Slack's order; none for a thread Slack no longer has.

        Raises:
            SinkError: A page could not be read, Slack refused it, or the pages never end.
        """
        found: list[Mapping[str, object]] = []
        cursor = ""
        for _ in range(MAX_PAGES):
            params = {"channel": self.channel, "ts": thread, "limit": str(PAGE)}
            if cursor:
                params["cursor"] = cursor
            try:
                reply = _get(self.url, params, self.token)
            except _GoneError:
                # Its first post was deleted: nobody can reply in it, and the replies it had are gone with it.
                return found
            messages = reply.get("messages")
            listed: list[object] = messages if isinstance(messages, list) else []
            found.extend({str(k): v for k, v in m.items()} for m in listed if isinstance(m, dict))
            meta = reply.get("response_metadata")
            cursor = str(meta.get("next_cursor") or "") if isinstance(meta, dict) else ""
            if reply.get("has_more") is not True or not cursor:
                return found
        raise SinkError(f"its pages never end: more than {MAX_PAGES} of them")


def _get(url: str, params: Mapping[str, str], token: str) -> dict[str, object]:
    """Call a Web API method with a GET, its arguments in the query.

    Returns:
        Slack's reply, which said `"ok": true`.

    Raises:
        SinkError: Slack could not be reached, answered other than 2xx, or refused the call.
    """
    request = urllib.request.Request(  # noqa: S310
        f"{url}?{urllib.parse.urlencode(params)}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            body = response.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        # 429 is Slack's rate limit: the next run reads it again.
        raise SinkError(f"HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SinkError(f"cannot reach Slack: {e}") from e
    try:
        parsed: object = json.loads(body)
    except json.JSONDecodeError as e:
        raise SinkError("Slack's reply is not JSON") from e
    if not isinstance(parsed, dict):
        raise SinkError("Slack's reply is not a JSON object")
    reply = {str(k): v for k, v in parsed.items()}
    if reply.get("ok") is not True:
        # `error` is Slack's own code, such as `missing_scope` or `thread_not_found`, never the token.
        error = str(reply.get("error"))[:100]
        raise (_GoneError if error == _GONE else SinkError)(f"Slack refused it: {error}")
    return reply


class _GoneError(SinkError):
    """Slack no longer has the thread asked for."""


def _reply(key: str, thread: str, message: Mapping[str, object]) -> dict[str, object] | None:
    """A message's `reply` line, if a person wrote it in the thread: not its first post, a bot's, or a `subtype`'s.

    Returns:
        The line, or None.
    """
    ts, user, text = message.get("ts"), message.get("user"), message.get("text")
    if not isinstance(ts, str) or not _TS.fullmatch(ts) or ts == thread:
        return None
    if "bot_id" in message or "subtype" in message:
        return None
    if not isinstance(user, str) or not _USER.fullmatch(user) or not isinstance(text, str) or not text.strip():
        return None
    return {
        "kind": "reply",
        "ticket": key,
        "thread": thread,
        "ts": ts,
        "user": user,
        "time": _time(ts),
        "body": plain(text),
    }


def _time(ts: str) -> str:
    """When a message was posted, from its `ts`: seconds since the epoch, then its microseconds.

    Returns:
        The time, in ISO 8601, in UTC.
    """
    seconds, _, fraction = ts.partition(".")
    at = datetime.fromtimestamp(int(seconds), UTC)
    return at.replace(microsecond=int(fraction[:6].ljust(6, "0"))).isoformat()


def plain(text: str) -> str:
    """A message's text as its writer typed it: Slack's links and mentions as text, and its escaping undone.

    `<https://x|label>` reads `label (https://x)` and `<https://x>` the URL; a person `<@U123>` reads `@U123`, a
    channel `<#C123|general>` `#general`, and `<!here>` `@here`, or what Slack shows for it, such as a date's text.

    Returns:
        The text.
    """

    def unangled(match: re.Match[str]) -> str:
        target, label = match.group(1), match.group(2)
        if target.startswith("@"):
            return target
        if target.startswith("#"):
            return f"#{label}" if label else target
        if target.startswith("!"):
            return label or f"@{target[1:]}"
        return f"{label} ({target})" if label and label != target else target

    unescaped = _ANGLED.sub(unangled, text)
    return unescaped.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def _emit(stdout: TextIO, line: Mapping[str, object]) -> None:
    stdout.write(json.dumps(line, ensure_ascii=False) + "\n")


def _say(message: str) -> None:
    click.echo(f"canopy-connect-slack: {message}", err=True)
