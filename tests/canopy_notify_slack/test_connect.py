"""The reader of the Slack sink's ticket threads (ROADMAP M64), against a local stand-in for the Web API."""

import json
import os
import threading
import urllib.parse
from collections.abc import Generator, Mapping, Sequence
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar, override
from unittest import mock

import pytest
from canopy_notify_slack import connect
from click.testing import Result

from tests.canopy_notify_slack.helpers import token_file
from tests.conftest import invoke

CHANNEL = "C0123ABCD"
REPO = "/r/api"
OPERATOR = "U0OPERATOR"
#: What a thread's first post, the sink's own, looks like when it is read back.
STARTER: dict[str, Any] = {"type": "message", "subtype": "bot_message", "bot_id": "B1", "text": "PROJ-1"}


class _Replies(BaseHTTPRequestHandler):
    """`conversations.replies`: each thread's messages after its first post, `per_page` a page, the first on each."""

    threads: ClassVar[dict[str, list[dict[str, Any]]]] = {}
    per_page: ClassVar[int] = 100
    # Threads Slack refuses to read, by `ts`, with the error it gives.
    refused: ClassVar[dict[str, str]] = {}
    received: ClassVar[list[tuple[str | None, dict[str, str]]]] = []

    def do_GET(self) -> None:
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
        _Replies.received.append((self.headers["Authorization"], query))
        ts = query["ts"]
        if ts in _Replies.refused:
            self._send({"ok": False, "error": _Replies.refused[ts]})
            return
        start = int(query.get("cursor") or 0)
        rest = _Replies.threads[ts]
        page = rest[start : start + _Replies.per_page]
        more = start + _Replies.per_page < len(rest)
        meta = {"next_cursor": str(start + _Replies.per_page) if more else ""}
        # Like the Web API: the thread's first post leads every page.
        first = {**STARTER, "ts": ts, "thread_ts": ts}
        self._send({"ok": True, "messages": [first, *page], "has_more": more, "response_metadata": meta})

    def _send(self, reply: Mapping[str, Any]) -> None:
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(reply).encode())

    @override
    def log_message(self, format: str, *args: Any) -> None:
        del format, args


@pytest.fixture
def replies() -> Generator[str]:
    """A local stand-in for Slack's `conversations.replies`. Yields its URL."""
    _Replies.threads = {}
    _Replies.per_page = 100
    _Replies.refused = {}
    _Replies.received = []
    server = HTTPServer(("127.0.0.1", 0), _Replies)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/api/conversations.replies"
    server.shutdown()
    server.server_close()


@pytest.fixture
def state(tmp_path: Path) -> Generator[Path]:
    """The sink's threads file, under a state directory of the test's own. Yields its path, not yet written."""
    with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(tmp_path / "state")}):
        yield tmp_path / "state" / "canopy" / "slack-threads.json"


def _threads(path: Path, threads: Mapping[str, Any], earlier: Mapping[str, Any] | None = None) -> None:
    """Write the sink's threads file, as of version 2, for the channel and repository the reader is asked about."""
    scope = {"threads": threads, "posted": list[str](), "earlier": earlier or dict[str, Any]()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 2, "scopes": {json.dumps([CHANNEL, REPO]): scope}}))


def _says(ts: str, text: str, user: str = OPERATOR, **more: object) -> dict[str, Any]:
    return {"type": "message", "ts": ts, "user": user, "text": text, **more}


def _read(
    url: str,
    tmp_path: Path,
    request: Mapping[str, Any] | None = None,
    *flags: str,
    today: date = date(2026, 9, 26),
) -> Result:
    argv = ["--channel", CHANNEL, "--token-file", str(token_file(tmp_path)), *flags]
    stdin = json.dumps({"repo": REPO} if request is None else request)
    return invoke(connect.main, argv, stdin=stdin, obj=connect.Reach(url, lambda: today))


def _lines(result: Result) -> list[dict[str, Any]]:
    return [json.loads(line) for line in result.stdout.splitlines()]


def _bodies(result: Result) -> list[tuple[str, str, str]]:
    """Each `reply` line's ticket, user, and body, in order."""
    return [(line["ticket"], line["user"], line["body"]) for line in _lines(result) if line["kind"] == "reply"]


def test_a_reply_a_person_wrote_in_a_tickets_thread_is_printed(replies: str, tmp_path: Path, state: Path) -> None:
    _threads(state, {"PROJ-1": {"day": "2026-09-26", "ts": "1790.000001"}})
    _Replies.threads["1790.000001"] = [_says("1790.000005", "Use the staging config, not prod.")]
    result = _read(replies, tmp_path)
    assert result.exit_code == 0, result.stderr
    assert _lines(result) == [
        {
            "kind": "reply",
            "ticket": "PROJ-1",
            "thread": "1790.000001",
            "ts": "1790.000005",
            "user": OPERATOR,
            "time": "1970-01-01T00:29:50.000005+00:00",
            "body": "Use the staging config, not prod.",
        },
        {"kind": "end", "tickets": ["PROJ-1"]},
    ]
    # The bot token, as the sink sends it, and the channel and thread asked for by name.
    [(authorization, query)] = _Replies.received
    assert authorization == "Bearer xoxb-1-2-secret"
    assert query == {"channel": CHANNEL, "ts": "1790.000001", "limit": "200"}


def test_only_what_a_person_wrote_is_printed(replies: str, tmp_path: Path, state: Path) -> None:
    _threads(state, {"PROJ-1": {"day": "2026-09-26", "ts": "1790.000001"}})
    _Replies.threads["1790.000001"] = [
        _says("1790.000002", "a bot, under the operator's name", bot_id="B9"),
        _says("1790.000003", "joined", subtype="channel_join"),
        {"type": "message", "ts": "1790.000004", "text": "no user"},
        _says("1790.000005", "a file, and nothing said", subtype="file_share"),
        _says("1790.000006", "   "),
        _says("1790.000007", "it reads like this now", edited={"user": OPERATOR, "ts": "1790.000009"}),
        _says("1790.000008", "LGTM from me", user="U0COWORKER"),
    ]
    result = _read(replies, tmp_path)
    assert result.exit_code == 0, result.stderr
    # An edited message as it reads now; a coworker's too, for canopy to decide whose words count (stage 2).
    assert _bodies(result) == [("PROJ-1", OPERATOR, "it reads like this now"), ("PROJ-1", "U0COWORKER", "LGTM from me")]


def test_the_threads_of_the_last_days_are_read_and_no_review_thread(
    replies: str,
    tmp_path: Path,
    state: Path,
) -> None:
    _threads(
        state,
        {
            "PROJ-1": {"day": "2026-09-26", "ts": "1790.000001"},
            "PROJ-2": {"day": "2026-09-23", "ts": "1790.000002"},
            "review:https://x.test/pr/9": {"day": "2026-09-26", "ts": "1790.000003"},
        },
        earlier={"PROJ-1": [{"day": "2026-09-25", "ts": "1790.000000"}]},
    )
    _Replies.threads = {
        "1790.000000": [_says("1790.000010", "yesterday's answer")],
        "1790.000001": [_says("1790.000011", "today's answer")],
        "1790.000002": [_says("1790.000012", "too old")],
    }
    result = _read(replies, tmp_path)
    assert result.exit_code == 0, result.stderr
    assert _bodies(result) == [("PROJ-1", OPERATOR, "yesterday's answer"), ("PROJ-1", OPERATOR, "today's answer")]
    assert _lines(result)[-1] == {"kind": "end", "tickets": ["PROJ-1"]}
    # Four days back, PROJ-2's thread is read too.
    assert ("PROJ-2", OPERATOR, "too old") in _bodies(_read(replies, tmp_path, None, "--days", "4"))


def test_only_the_tickets_asked_are_read(replies: str, tmp_path: Path, state: Path) -> None:
    _threads(
        state,
        {"PROJ-1": {"day": "2026-09-26", "ts": "1790.000001"}, "PROJ-2": {"day": "2026-09-26", "ts": "1790.000002"}},
    )
    _Replies.threads = {"1790.000001": [], "1790.000002": [_says("1790.000003", "on two")]}
    result = _read(replies, tmp_path, {"repo": REPO, "tickets": ["PROJ-2", "PROJ-9"]})
    assert _bodies(result) == [("PROJ-2", OPERATOR, "on two")]
    assert _lines(result)[-1] == {"kind": "end", "tickets": ["PROJ-2"]}
    assert [q["ts"] for _, q in _Replies.received] == ["1790.000002"]


def test_a_long_thread_is_read_page_by_page(replies: str, tmp_path: Path, state: Path) -> None:
    _threads(state, {"PROJ-1": {"day": "2026-09-26", "ts": "1790.000001"}})
    _Replies.threads["1790.000001"] = [_says(f"1790.00001{n}", f"part {n}") for n in range(5)]
    _Replies.per_page = 2
    result = _read(replies, tmp_path)
    assert [body for _, _, body in _bodies(result)] == [f"part {n}" for n in range(5)]
    assert [q.get("cursor") for _, q in _Replies.received] == [None, "2", "4"]


def test_a_thread_that_cannot_be_read_leaves_its_ticket_out_of_the_end(
    replies: str,
    tmp_path: Path,
    state: Path,
) -> None:
    _threads(
        state,
        {"PROJ-1": {"day": "2026-09-26", "ts": "1790.000001"}, "PROJ-2": {"day": "2026-09-26", "ts": "1790.000002"}},
        earlier={"PROJ-1": [{"day": "2026-09-25", "ts": "1790.000000"}]},
    )
    _Replies.threads = {"1790.000000": [_says("1790.000010", "read")], "1790.000002": [_says("1790.000012", "two")]}
    _Replies.refused = {"1790.000001": "missing_scope"}
    result = _read(replies, tmp_path)
    assert result.exit_code == 1
    # PROJ-1's other thread was read, but a ticket is printed whole or not at all.
    assert _bodies(result) == [("PROJ-2", OPERATOR, "two")]
    assert _lines(result)[-1] == {"kind": "end", "tickets": ["PROJ-2"]}
    assert "cannot read PROJ-1's thread 1790.000001: Slack refused it: missing_scope" in result.stderr


@pytest.mark.parametrize(
    ("stdin", "said"),
    [
        ("not json", "stdin is not a JSON object"),
        ('["/r/api"]', "stdin is not a JSON object"),
        ("{}", "stdin's repo must be a string"),
        ('{"repo": "/r/api", "tickets": ["review:x"]}', "stdin's tickets must be a list of ticket keys"),
    ],
)
def test_a_request_that_is_not_usable_is_exit_2(
    replies: str,
    tmp_path: Path,
    state: Path,
    stdin: str,
    said: str,
) -> None:
    del state
    argv = ["--channel", CHANNEL, "--token-file", str(token_file(tmp_path))]
    result = invoke(connect.main, argv, stdin=stdin, obj=connect.Reach(replies))
    assert result.exit_code == 2
    assert said in result.stderr
    assert _Replies.received == []


def test_a_token_file_others_can_read_is_exit_2(replies: str, tmp_path: Path, state: Path) -> None:
    del state
    argv = ["--channel", CHANNEL, "--token-file", str(token_file(tmp_path, mode=0o644))]
    result = invoke(connect.main, argv, stdin=json.dumps({"repo": REPO}), obj=connect.Reach(replies))
    assert result.exit_code == 2
    assert "readable by others" in result.stderr


def test_no_threads_file_reads_nothing(replies: str, tmp_path: Path, state: Path) -> None:
    del state
    result = _read(replies, tmp_path)
    assert (result.exit_code, _lines(result)) == (0, [{"kind": "end", "tickets": []}])


@pytest.mark.parametrize(
    ("text", "typed"),
    [
        ("a &lt;b&gt; &amp; c", "a <b> & c"),
        ("see <https://x.test/a?b=1&amp;c=2>", "see https://x.test/a?b=1&c=2"),
        ("see <https://x.test|the docs>", "see the docs (https://x.test)"),
        ("ask <@U0123> in <#C0123|general>", "ask @U0123 in #general"),
        ("<!here> by <!date^1790^{date_short}|Sep 26>", "@here by Sep 26"),
    ],
)
def test_a_message_reads_as_its_writer_typed_it(text: str, typed: str) -> None:
    assert connect.plain(text) == typed


def _argv(*more: str) -> Sequence[str]:
    return ["--channel", CHANNEL, *more]


@pytest.mark.parametrize("argv", [_argv("--days", "0"), _argv("--days", "8"), ["--days", "3"]])
def test_the_command_line_is_checked(argv: Sequence[str]) -> None:
    assert invoke(connect.main, argv).exit_code == 2
