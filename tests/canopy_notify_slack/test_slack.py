"""The Slack sink canopy ships (DESIGN §20), against a local HTTP server."""

import io
import json
import os
import shutil
import threading
from collections.abc import Generator, Iterable, Mapping
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar, Protocol, override
from unittest import mock

import canopy_notify_slack as slack
import pytest

MESSAGE: dict[str, Any] = {
    "version": 1,
    "sink": "slack",
    "repo": "/home/me/src/api",
    "sent_at": "2026-09-24T19:00:00Z",
    "attention": {
        "added": [
            {
                "ticket": "PROJ-3",
                "title": "Retry <@U1> checkout",
                "repo": None,
                "reason": "needs_reviewer",
                "detail": "<!channel> https://x.test/1",
                "since": "2026-09-24T18:00:00Z",
            }
        ],
        "resolved": [{"ticket": "PROJ-4", "title": None, "repo": "web", "reason": "ready_to_merge"}],
        "open": 4,
        "path": "/home/me/.canopy/attention.md",
    },
    "events": [
        {
            "id": 88,
            "kind": "run.ended",
            "ticket": "PROJ-12",
            "title": "Add retries",
            "run": 41,
            "run_kind": "implement",
            "status": "done",
            "pr": "https://x.test/pr/7",
            "prs": ["https://x.test/pr/7"],
            "summary": "<https://evil|click>",
            "question": None,
            "line": "< PROJ-12 run 41 implement ended done: <https://evil|click>",
        }
    ],
    "omitted": 0,
    "digest": None,
    "text": "canopy attention: 1 new, 1 resolved\n+ PROJ-3 needs_reviewer: x\nFull list: /home/me/attention.md\n",
}


# Slack


class _Hook(BaseHTTPRequestHandler):
    received: ClassVar[list[dict[str, Any]]] = []
    status: ClassVar[int] = 200

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        _Hook.received.append(json.loads(self.rfile.read(length)))
        self.send_response(_Hook.status)
        self.end_headers()
        self.wfile.write(b"ok" if _Hook.status == 200 else b"invalid_payload")

    @override
    def log_message(self, format: str, *args: Any) -> None:
        del format, args


@pytest.fixture
def hook() -> Generator[str]:
    """A local stand-in for Slack's incoming webhook. Yields its URL."""
    _Hook.received = []
    _Hook.status = 200
    server = HTTPServer(("127.0.0.1", 0), _Hook)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/services/T/B/x"
    server.shutdown()
    server.server_close()


def webhook_file(tmp_path: Path, url: str, mode: int = 0o600) -> Path:
    path = tmp_path / "slack-webhook"
    path.write_text(url + "\n")
    path.chmod(mode)
    return path


def test_the_slack_sink_posts_one_escaped_message(hook: str, tmp_path: Path) -> None:
    path = webhook_file(tmp_path, hook)
    assert slack.run(["--webhook-file", str(path)], io.StringIO(json.dumps(MESSAGE)), prefix="http://127.0.0.1:") == 0
    [posted] = _Hook.received
    assert set(posted) == {"text", "blocks"}
    assert posted["blocks"] == slack.blocks(MESSAGE)
    assert posted["text"].splitlines() == [
        "*canopy* · api: 1 new, 1 resolved, 4 open, 1 event",
        "+ *PROJ-3* Retry &lt;@U1&gt; checkout · needs_reviewer: &lt;!channel&gt; https://x.test/1",
        "- *PROJ-4 (web)* · ready_to_merge",
        "&lt; PROJ-12 run 41 implement ended done: &lt;https://evil|click&gt;",
    ]


def test_slack_refusing_a_post_is_exit_1(hook: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _Hook.status = 400
    path = webhook_file(tmp_path, hook)
    assert slack.run(["--webhook-file", str(path)], io.StringIO(json.dumps(MESSAGE)), prefix="http://127.0.0.1:") == 1
    assert "Slack refused the post: HTTP 400: invalid_payload" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("url", "mode", "message"),
    [
        ("https://hooks.slack.com/services/T/B/x", 0o644, "is readable by others; run: chmod 600"),
        ("https://example.test/hook", 0o600, "must hold one URL starting https://hooks.slack.com/"),
        ("https://hooks.slack.com/a https://hooks.slack.com/b", 0o600, "must hold one URL"),
    ],
)
def test_the_webhook_file_is_checked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], url: str, mode: int, message: str
) -> None:
    path = webhook_file(tmp_path, url, mode)
    assert slack.run(["--webhook-file", str(path)], io.StringIO(json.dumps(MESSAGE))) == 2
    assert message in capsys.readouterr().err


def test_a_webhook_that_only_looks_like_the_prefix_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # It starts with the prefix, but its host is evil.test: the part before `@` is a user name.
    path = webhook_file(tmp_path, "http://127.0.0.1:1@evil.test/hook")
    assert slack.run(["--webhook-file", str(path)], io.StringIO(json.dumps(MESSAGE)), prefix="http://127.0.0.1:") == 2
    assert "must hold one URL starting http://127.0.0.1:" in capsys.readouterr().err


def test_a_fifo_webhook_file_is_refused_without_opening_it(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "slack-webhook"
    os.mkfifo(path, 0o600)
    assert slack.run(["--webhook-file", str(path)], io.StringIO(json.dumps(MESSAGE))) == 2
    assert "is not a regular file" in capsys.readouterr().err


def test_a_long_slack_message_is_45_lines_with_its_header() -> None:
    events = [{"kind": "run.started", "line": f"event {n}"} for n in range(60)]
    text = slack.render({"repo": "/r/api", "events": events})
    lines = text.splitlines()
    assert len(lines) == 45
    assert lines[-1] == "_... and 17 more lines_"


def test_the_slack_sink_reads_its_default_file_and_needs_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path)}):
        assert slack.default_webhook_file() == tmp_path / "canopy" / "slack-webhook"
        assert slack.run([], io.StringIO(json.dumps(MESSAGE))) == 2
        assert f"cannot read the webhook file {tmp_path / 'canopy' / 'slack-webhook'}" in capsys.readouterr().err
        (tmp_path / "canopy").mkdir()
        webhook_file(tmp_path / "canopy", "https://hooks.slack.com/services/T/B/x")
        assert slack.run([], io.StringIO("canopy attention: 1 new\n")) == 2
        assert 'set format = "json" for this sink' in capsys.readouterr().err


def test_a_digest_is_a_short_block() -> None:
    text = slack.render(
        {
            "repo": "/r/api",
            "attention": None,
            "events": [],
            "digest": {"lines": ["Digest since x: 2 ticks", "  nothing ran"]},
        }
    )
    assert text.splitlines() == ["*canopy* · api: digest", "", "*Digest*", "Digest since x: 2 ticks", "nothing ran"]


def _texts(blocks: Iterable[Mapping[str, Any]]) -> list[str]:
    """Each section's text and each context's elements, in order: what a reader sees, as Slack markup."""
    out: list[str] = []
    for block in blocks:
        if block["type"] == "section":
            out.append(block["text"]["text"])
            out += [f["text"] for f in block.get("fields", [])]
        elif block["type"] == "context":
            out += [e["text"] for e in block["elements"]]
    return out


def test_slack_marks_a_finding_the_operator_dismissed() -> None:
    attention: dict[str, Any] = {
        **MESSAGE["attention"],
        "added": [],
        "resolved": [{"ticket": "chore:deps", "title": None, "repo": None, "reason": "lodash", "dismissed": True}],
    }
    message: dict[str, Any] = {**MESSAGE, "attention": attention, "events": []}
    assert "- *chore:deps* · lodash (dismissed)" in slack.render(message).splitlines()
    assert "*Resolved*\n:heavy_check_mark: ~chore:deps~ lodash (dismissed)" in _texts(slack.blocks(message))


def test_slack_blocks_are_built_from_the_fields() -> None:
    blocks = slack.blocks(MESSAGE)
    assert blocks[0] == {"type": "header", "text": {"type": "plain_text", "text": "canopy · api"}}
    assert _texts(blocks) == [
        "1 new · 1 resolved · 4 open · 1 event",
        (
            ":bell: *PROJ-3* Retry &lt;@U1&gt; checkout · needs_reviewer\n&lt;!channel&gt; <https://x.test/1>\n"
            "_open since <!date^1790272800^{date_short_pretty} {time}|2026-09-24T18:00:00Z>_"
        ),
        "*Resolved*\n:heavy_check_mark: ~PROJ-4 (web)~ ready_to_merge",
        (
            ":white_check_mark: *PROJ-12* Add retries · implement run 41 ended *done*\n<https://x.test/pr/7>\n"
            "&lt;https://evil|click&gt;"
        ),
    ]


def test_slack_blocks_parse_nothing_in_journal_text() -> None:
    # Set `verbatim`, Slack would otherwise turn a bare @here or #channel into a mention or a link.
    detail = "@here #general <!channel> https://ok.test/?a=1&b=2 https://evil.test|ok.test"
    added = [{"ticket": "T-1", "reason": "r", "detail": detail}]
    blocks: list[dict[str, Any]] = slack.blocks({"repo": "/r/api", "attention": {"added": added}})
    mrkdwn = [e for b in blocks for e in ([b["text"]] if b["type"] == "section" else b.get("elements", []))]
    assert all(m["verbatim"] for m in mrkdwn)
    # A URL is a link that shows itself; one holding `|` would show a label instead, so it stays text.
    assert _texts(blocks)[1] == (
        ":bell: *T-1* · r\n@here #general &lt;!channel&gt; <https://ok.test/?a=1&amp;b=2> https://evil.test|ok.test"
    )


def test_slack_blocks_for_each_event_kind() -> None:
    events: list[dict[str, Any]] = [
        {
            "kind": "run.started",
            "ticket": "P-1",
            "title": "Fix the build",
            "run": 2,
            "run_kind": "fix_ci",
            "branch": "agent/P-1",
            "attempt": 1,
            "limit": 3,
        },
        {
            "kind": "run.ended",
            "ticket": "P-2",
            "run": 3,
            "run_kind": "implement",
            "status": "blocked",
            "prs": [],
            "question": "Which table?",
        },
        {"kind": "chore.ended", "chore": "deps", "run": 4, "status": "failed", "findings": 1, "summary": None},
        {
            "kind": "review.ended",
            "pr": "https://x.test/pr/9",
            "ticket": None,
            "run": 5,
            "status": "done",
            "verdict": "findings",
            "impact": "low",
            "findings": 2,
        },
        {"kind": "loop.failing", "count": 3, "status": "error", "tick": 9, "log": "/w/.canopy/canopy.log"},
        {"kind": "loop.recovered", "failed": 3},
        {"kind": "loop.sink_failing", "sink": "phone", "error": "exit 7"},
        {"kind": "test", "text": "canopy test message"},
        {"kind": "kind.from.a.newer.canopy", "line": "x <y>"},
    ]
    assert _texts(slack.blocks({"repo": "/r/api", "events": events}))[1:] == [
        ":arrow_forward: *P-1* Fix the build · fix_ci run 2 started\nattempt 1 of 3 on `agent/P-1`",
        ":raising_hand: *P-2* · implement run 3 ended *blocked*\n> *Question:* Which table?",
        ":x: *chore:deps* · run 4 ended *failed* · 1 finding",
        ":white_check_mark: review run 5 ended *done*: findings low · 2 findings\n<https://x.test/pr/9>",
        (
            ":rotating_light: *The loop is failing:* 3 ticks in a row ended other than ok\n"
            "latest tick 9 ended error; log `/w/.canopy/canopy.log`"
        ),
        ":white_check_mark: *The loop recovered* after 3 failed ticks",
        ":warning: *Sink phone is failing:* 3 deliveries in a row\n`exit 7`",
        ":test_tube: canopy test message",
        "x &lt;y&gt;",
    ]


def test_a_slack_digest_is_fields() -> None:
    digest: dict[str, Any] = {
        "since": "2026-09-24T15:00:00Z",
        "ticks": {"ok": 23, "error": 1},
        "runs_started": {"implement": 2},
        "runs_ended": {},
        "done": [{"ticket": "P-1", "title": "Fix the build", "run": 1, "pr": "https://x.test/pr/1"}],
        "blocked": [{"ticket": "P-2", "run": 2}],
        "attention": {"open": 3, "by_reason": {"needs_reviewer": 3}, "oldest": "3h"},
        "running": 2,
        "lines": ["not used"],
    }
    assert _texts(slack.blocks({"repo": "/r/api", "digest": digest}))[1:] == [
        "*Digest* since <!date^1790262000^{date_short_pretty} {time}|2026-09-24T15:00:00Z>",
        "*Ticks*\n24 (error 1, ok 23)",
        "*Workers running*\n2",
        "*Runs started*\nimplement 2",
        "*Runs ended*\nnone",
        "*Needs you*\n3 open (needs_reviewer 3), oldest 3h",
        ":white_check_mark: *P-1* Fix the build <https://x.test/pr/1>\n:raising_hand: *P-2*",
    ]


def test_slack_blocks_stay_within_slacks_limit() -> None:
    events = [{"kind": "test", "text": f"event {n}"} for n in range(60)]
    blocks = slack.blocks({"repo": "/r/api", "events": events, "omitted": 3})
    assert len(blocks) == 50
    # The header, the counts, 47 events; 13 events and the 3 canopy left out are counted.
    assert _texts(blocks)[-1] == "_… and 16 more: see `canopy status`_"


class _Unread(io.StringIO):
    @override
    def read(self, size: int | None = -1, /) -> str:
        raise AssertionError(f"--help read stdin ({size})")


def test_help_never_waits_for_stdin(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_:
        slack.run(["--help"], _Unread())
    assert exit_.value.code == 0
    assert "usage: canopy-notify-slack" in capsys.readouterr().out


# Slack with a bot token


class _Api(BaseHTTPRequestHandler):
    received: ClassVar[list[tuple[str | None, dict[str, Any]]]] = []
    reply: ClassVar[dict[str, Any]] = {"ok": True}
    # The posts, counted from 1, refused as `not_in_channel`.
    refuse: ClassVar[set[int]] = set()

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        _Api.received.append((self.headers["Authorization"], json.loads(self.rfile.read(length))))
        n = len(_Api.received)
        # Each post's `ts` says which it was, as the Web API names a message by its time.
        reply = {"ok": False, "error": "not_in_channel"} if n in _Api.refuse else {**_Api.reply, "ts": f"1790.{n:06d}"}
        # Like the Web API: 200 even when the post is refused.
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(reply).encode())

    @override
    def log_message(self, format: str, *args: Any) -> None:
        del format, args


@pytest.fixture
def api() -> Generator[str]:
    """A local stand-in for Slack's `chat.postMessage`. Yields its URL."""
    _Api.received = []
    _Api.reply = {"ok": True}
    _Api.refuse = set()
    server = HTTPServer(("127.0.0.1", 0), _Api)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/api/chat.postMessage"
    server.shutdown()
    server.server_close()


def token_file(tmp_path: Path, token: str = "xoxb-1-2-secret", mode: int = 0o600) -> Path:  # noqa: S107
    path = tmp_path / "slack-token"
    path.write_text(token + "\n")
    path.chmod(mode)
    return path


def test_the_slack_sink_posts_with_a_bot_token(api: str, tmp_path: Path) -> None:
    argv = ["--channel", "C0123ABCD", "--token-file", str(token_file(tmp_path))]
    assert slack.run(argv, io.StringIO(json.dumps(MESSAGE)), api_url=api) == 0
    [(authorization, posted)] = _Api.received
    assert authorization == "Bearer xoxb-1-2-secret"
    assert set(posted) == {"channel", "text", "blocks"}
    assert posted["channel"] == "C0123ABCD"
    assert posted["text"].splitlines()[1] == (
        "+ *PROJ-3* Retry &lt;@U1&gt; checkout · needs_reviewer: &lt;!channel&gt; https://x.test/1"
    )


def test_the_slack_sink_posts_with_a_name_and_an_icon(api: str, tmp_path: Path) -> None:
    argv = ["--channel", "C0123ABCD", "--token-file", str(token_file(tmp_path))]
    argv += ["--username", "canopy (api)", "--icon-emoji", ":wave::skin-tone-3:"]
    assert slack.run(argv, io.StringIO(json.dumps(MESSAGE)), api_url=api) == 0
    [(_, posted)] = _Api.received
    assert set(posted) == {"channel", "text", "blocks", "username", "icon_emoji"}
    assert (posted["username"], posted["icon_emoji"]) == ("canopy (api)", ":wave::skin-tone-3:")


def test_the_token_file_defaults_to_the_config_directory(api: str, tmp_path: Path) -> None:
    with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path)}):
        (tmp_path / "canopy").mkdir()
        token_file(tmp_path / "canopy")
        assert slack.run(["--channel", "#canopy"], io.StringIO(json.dumps(MESSAGE)), api_url=api) == 0
        assert _Api.received[0][1]["channel"] == "#canopy"


def test_a_long_successful_reply_is_exit_0(api: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # A real reply echoes the message, with its `bot_profile`, and runs past the 500 characters a failure prints.
    _Api.reply = {"ok": True, "channel": "C0123ABCD", "message": {"bot_profile": {"name": "canopy" * 100}}}
    assert len(json.dumps(_Api.reply)) > 500
    argv = ["--channel", "C0123ABCD", "--token-file", str(token_file(tmp_path))]
    assert slack.run(argv, io.StringIO(json.dumps(MESSAGE)), api_url=api) == 0
    assert capsys.readouterr().err == ""


def test_a_long_refusal_prints_only_its_start(api: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _Api.reply = {"ok": False, "error": "not_in_channel", "detail": "x" * 1000}
    argv = ["--channel", "C0123ABCD", "--token-file", str(token_file(tmp_path))]
    assert slack.run(argv, io.StringIO(json.dumps(MESSAGE)), api_url=api) == 1
    err = capsys.readouterr().err
    assert "not_in_channel" in err
    assert "x" * 1000 not in err


def test_a_web_api_error_is_exit_1(api: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _Api.reply = {"ok": False, "error": "not_in_channel"}
    argv = ["--channel", "C0123ABCD", "--token-file", str(token_file(tmp_path))]
    assert slack.run(argv, io.StringIO(json.dumps(MESSAGE)), api_url=api) == 1
    assert "Slack refused the post" in (err := capsys.readouterr().err)
    assert "not_in_channel" in err


@pytest.mark.parametrize(
    ("token", "mode", "channel", "message"),
    [
        ("xoxb-1-2-secret", 0o640, "C0123ABCD", "is readable by others; run: chmod 600"),
        ("https://hooks.slack.com/services/T/B/x", 0o600, "C0123ABCD", "must hold one Slack bot token starting xoxb-"),
        ("xoxp-1-2-secret", 0o600, "C0123ABCD", "must hold one Slack bot token"),
        ("xoxb-1 xoxb-2", 0o600, "C0123ABCD", "must hold one Slack bot token"),
        ("xoxb-1-2-sécret", 0o600, "C0123ABCD", "must hold one Slack bot token"),
        ("xoxb-1-2-secret", 0o600, "C01 <!channel>", "is not a Slack channel id or name"),
    ],
)
def test_the_token_file_and_channel_are_checked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], token: str, mode: int, channel: str, message: str
) -> None:
    argv = ["--channel", channel, "--token-file", str(token_file(tmp_path, token, mode))]
    assert slack.run(argv, io.StringIO(json.dumps(MESSAGE)), api_url="http://127.0.0.1:1/") == 2
    err = capsys.readouterr().err
    assert message in err
    assert "secret" not in err.replace(str(tmp_path), "")


@pytest.mark.parametrize(
    ("flags", "message"),
    [
        (["--username", "  "], "must be printable, not blank"),
        (["--username", "a\nb"], "must be printable, not blank"),
        (["--username", "x" * 81], "at most 80 characters"),
        (["--icon-emoji", "robot_face"], "is not an emoji code"),
        (["--icon-emoji", "https://x.test/i.png"], "is not an emoji code"),
    ],
)
def test_the_name_and_icon_are_checked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], flags: list[str], message: str
) -> None:
    argv = ["--channel", "C0123ABCD", "--token-file", str(token_file(tmp_path)), *flags]
    assert slack.run(argv, io.StringIO(json.dumps(MESSAGE)), api_url="http://127.0.0.1:1/") == 2
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["--token-file", "/x"],
        ["--channel", "C0123ABCD", "--webhook-file", "/x"],
        ["--username", "canopy"],
        ["--icon-emoji", ":robot_face:"],
        ["--threads"],
        ["--channel", "C0123ABCD", "--broadcast", "plan"],
    ],
)
def test_a_token_and_a_webhook_are_not_mixed(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        slack.run(argv, io.StringIO(json.dumps(MESSAGE)))
    assert exited.value.code == 2
    assert "canopy-notify-slack: error:" in capsys.readouterr().err


# Slack with a bot token, in threads


def _delivery(sent_at: str, events: list[dict[str, Any]], added: list[dict[str, Any]] | None = None) -> str:
    attention: dict[str, Any] = {"added": added or [], "resolved": [], "open": len(added or []), "path": "/a.md"}
    return json.dumps({"repo": "/r/api", "sent_at": sent_at, "attention": attention, "events": events, "omitted": 0})


def _run(ticket: str, run: int, status: str | None = None) -> dict[str, Any]:
    if status is None:
        started = {"attempt": 1, "limit": 3, "branch": f"agent/{ticket}"}
        return {"id": run, "kind": "run.started", "ticket": ticket, "run": run, "run_kind": "implement", **started}
    return {"id": run, "kind": "run.ended", "ticket": ticket, "run": run, "run_kind": "implement", "status": status}


class _Threaded(Protocol):
    """Run the sink with `--threads` and any more `flags` on `delivery`, returning its exit code."""

    def __call__(self, delivery: str, *flags: str) -> int: ...


@pytest.fixture
def threaded(api: str, tmp_path: Path) -> Generator[_Threaded]:
    """Run the sink with `--threads`, its state under `tmp_path`. Yields the call."""
    argv = ["--channel", "C0123ABCD", "--token-file", str(token_file(tmp_path)), "--threads"]

    def deliver(delivery: str, *flags: str) -> int:
        return slack.run([*argv, *flags], io.StringIO(delivery), api_url=api)

    with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(tmp_path / "state")}):
        yield deliver


def _posts() -> list[tuple[str | None, bool, list[str]]]:
    """Each post's thread, whether it is also shown in the channel, and its text, in the order made."""
    return [(p.get("thread_ts"), p.get("reply_broadcast", False), _texts(p["blocks"])) for _, p in _Api.received]


def test_threads_hold_a_tickets_chores_and_reviews_posts_for_a_day(threaded: _Threaded, tmp_path: Path) -> None:
    first = [
        _run("PROJ-1", 1),
        {"id": 2, "kind": "chore.ended", "chore": "deps", "run": 2, "status": "done", "findings": 0},
        {"id": 3, "kind": "loop.recovered", "failed": 3},
        {"id": 4, "kind": "review.ended", "pr": "https://x.test/pr/9", "ticket": "PROJ-1", "run": 4, "status": "done"},
    ]
    assert threaded(_delivery("2026-09-24T12:30:00Z", first)) == 0
    # The channel's own post first, with the header; then one post starting each thread, in the order named.
    assert _posts() == [
        (None, False, ["1 event", ":white_check_mark: *The loop recovered* after 3 failed ticks"]),
        (None, False, [":arrow_forward: *PROJ-1* · implement run 1 started\nattempt 1 of 3 on `agent/PROJ-1`"]),
        (None, False, [":white_check_mark: *chore:deps* · run 2 ended *done* · 0 findings"]),
        (None, False, [":white_check_mark: *PROJ-1* · review run 4 ended *done*\n<https://x.test/pr/9>"]),
    ]
    assert _Api.received[0][1]["blocks"][0]["type"] == "header"
    assert all(p["blocks"][0]["type"] == "section" for _, p in _Api.received[1:])

    _Api.received.clear()
    later = [
        _run("PROJ-1", 5, "blocked"),
        {"id": 6, "kind": "chore.ended", "chore": "deps", "run": 6, "status": "failed", "findings": 1},
        _run("PROJ-2", 7),
    ]
    added = [{"ticket": "chore:deps", "reason": "lodash", "detail": "CVE"}]
    assert threaded(_delivery("2026-09-24T12:31:00Z", later, added)) == 0
    # The same day: replies in each thread, none shown in the channel unasked. The chore's thread first: attention
    # items come before events.
    assert [(ts, shown) for ts, shown, _ in _posts()] == [("1790.000003", False), ("1790.000002", False), (None, False)]
    assert _posts()[0][2] == [
        ":bell: *chore:deps* · lodash\nCVE",
        ":x: *chore:deps* · run 6 ended *failed* · 1 finding",
    ]

    _Api.received.clear()
    assert threaded(_delivery("2026-09-26T12:30:00Z", [_run("PROJ-1", 8, "done")])) == 0
    # A new day starts a new thread, and forgets the old day's.
    assert [(ts, shown) for ts, shown, _ in _posts()] == [(None, False)]
    state = json.loads((tmp_path / "state" / "canopy" / "slack-threads.json").read_text())
    assert state == {
        "version": 1,
        "scopes": {
            '["C0123ABCD", "/r/api"]': {"threads": {"PROJ-1": {"day": "2026-09-26", "ts": "1790.000001"}}, "posted": []}
        },
    }


@pytest.mark.parametrize(
    ("flags", "shown"),
    [
        ([], [False, False, False]),
        (["--broadcast", "blocked"], [True, False, False]),
        (["--broadcast", "attention", "--broadcast", "plan"], [False, True, True]),
    ],
)
def test_a_reply_is_shown_in_the_channel_only_for_what_broadcast_names(
    threaded: _Threaded, flags: list[str], shown: list[bool]
) -> None:
    started = [_run("PROJ-1", 1), _run("PROJ-2", 2), _run("PROJ-3", 3)]
    assert threaded(_delivery("2026-09-24T12:30:00Z", started), *flags) == 0
    _Api.received.clear()
    later = [
        _run("PROJ-1", 4, "blocked"),
        {"id": 5, "kind": "plan.proposed", "ticket": "PROJ-2", "run": 2, "plan": 1},
    ]
    added = [{"ticket": "PROJ-3", "reason": "ci_red", "detail": "lint"}]
    assert threaded(_delivery("2026-09-24T12:31:00Z", later, added), *flags) == 0
    assert {ts: on for ts, on, _ in _posts()} == dict(
        zip(["1790.000001", "1790.000002", "1790.000003"], shown, strict=True)
    )


def test_a_threaded_delivery_refused_partway_posts_the_rest_on_retry(threaded: _Threaded) -> None:
    delivery = _delivery("2026-09-24T12:30:00Z", [_run("PROJ-1", 1), _run("PROJ-2", 2), _run("PROJ-3", 3)])
    _Api.refuse = {2}
    assert threaded(delivery) == 1
    _Api.refuse = set()
    assert threaded(delivery) == 0
    # PROJ-1 was posted once; PROJ-2, refused, and PROJ-3, never tried, were posted on the retry.
    tickets = [p["blocks"][0]["text"]["text"].split("*")[1] for _, p in _Api.received]
    assert tickets == ["PROJ-1", "PROJ-2", "PROJ-2", "PROJ-3"]
    assert threaded(delivery) == 0
    # Once a delivery posts whole, the same items are new again: canopy sends an item once.
    assert len(_Api.received) == 7


def test_a_threads_file_that_is_not_the_sinks_starts_over(threaded: _Threaded, tmp_path: Path) -> None:
    path = tmp_path / "state" / "canopy" / "slack-threads.json"
    path.parent.mkdir(parents=True)
    scope = '["C0123ABCD", "/r/api"]'
    path.write_text(json.dumps({"scopes": {scope: {"threads": {"PROJ-1": {"day": "2026-09-24", "ts": "<!channel>"}}}}}))
    assert threaded(_delivery("2026-09-24T12:30:00Z", [_run("PROJ-1", 1)])) == 0
    assert _Api.received[-1][1].get("thread_ts") is None
    assert json.loads(path.read_text())["scopes"][scope]["threads"] == {
        "PROJ-1": {"day": "2026-09-24", "ts": "1790.000001"}
    }
    path.write_text("not json")
    assert threaded(_delivery("2026-09-24T12:31:00Z", [_run("PROJ-1", 2)])) == 0
    assert _Api.received[-1][1].get("thread_ts") is None


def test_a_threads_file_that_cannot_be_used_refuses_before_posting(
    threaded: _Threaded, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "state" / "canopy" / "slack-threads.json"
    path.parent.mkdir(parents=True)
    os.mkfifo(path, 0o600)
    assert threaded(_delivery("2026-09-24T12:30:00Z", [_run("PROJ-1", 1)])) == 2
    assert "is not a regular file" in capsys.readouterr().err
    shutil.rmtree(tmp_path / "state")
    # Its directory cannot be made: a file stands where it would be.
    (tmp_path / "state").write_text("")
    assert threaded(_delivery("2026-09-24T12:30:00Z", [_run("PROJ-1", 1)])) == 2
    assert "the threads file" in capsys.readouterr().err
    assert _Api.received == []


def test_a_save_keeps_the_scopes_of_other_channels_and_repositories(tmp_path: Path) -> None:
    path = tmp_path / "slack-threads.json"
    mine = slack.Threads.load(path, "C1", "/r/api")
    # Another sink, on another channel, saves after this one loaded and before it saves.
    theirs = slack.Threads.load(path, "C2", "/r/api")
    theirs.threads["PROJ-9"] = ("2026-09-24", "1790.000009")
    theirs.posted.add("f" * 64)
    theirs.save()
    mine.threads["PROJ-1"] = ("2026-09-24", "1790.000001")
    mine.save()
    assert slack.Threads.load(path, "C2", "/r/api") == theirs
    assert slack.Threads.load(path, "C1", "/r/api").threads == {"PROJ-1": ("2026-09-24", "1790.000001")}
    # The other scope's fingerprints are not this one's to skip.
    assert slack.Threads.load(path, "C1", "/r/api").posted == set()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["slack-threads.json", "slack-threads.json.lock"]


def test_finishing_forgets_only_earlier_days(tmp_path: Path) -> None:
    threads = slack.Threads.load(tmp_path / "slack-threads.json", "C1", "/r/api")
    threads.threads = {"OLD": ("2026-09-23", "1.1"), "NOW": ("2026-09-24", "1.2"), "LATER": ("2026-09-25", "1.3")}
    threads.posted = {"f" * 64}
    threads.finish("2026-09-24")
    assert threads.threads == {"NOW": ("2026-09-24", "1.2"), "LATER": ("2026-09-25", "1.3")}
    assert threads.posted == set()


def test_slack_links_each_item_and_event_to_its_page_in_the_web_ui() -> None:
    ui = "http://localhost:9000/canopy/"
    query, escaped = "pr?url=https%3A%2F%2Fx.test&a=1", "pr?url=https%3A%2F%2Fx.test&amp;a=1"
    added = [{"ticket": "P-1", "reason": "needs_reviewer", "ui": f"{ui}tickets/P-1"}]
    events = [
        {"kind": "test", "text": "canopy test message", "ui": None},
        {"kind": "loop.recovered", "failed": 3, "ui": f"{ui}pull-requests/{query}"},
        {
            "kind": "run.ended",
            "ticket": "P-2",
            "run": 3,
            "run_kind": "implement",
            "status": "done",
            "ui": f"{ui}runs/3",
        },
    ]
    message: dict[str, Any] = {"repo": "/r/api", "ui": ui, "attention": {"added": added, "open": 1}, "events": events}
    assert _texts(slack.blocks(message))[:5] == [
        f"1 new · 0 resolved · 1 open · 3 events · <{ui}|open>",
        f":bell: *P-1* · needs_reviewer · <{ui}tickets/P-1|open>",
        ":test_tube: canopy test message",
        # `&` is escaped in a link, as in any of Slack's text.
        f":white_check_mark: *The loop recovered* after 3 failed ticks · <{ui}pull-requests/{escaped}|open>",
        f":white_check_mark: *P-2* · implement run 3 ended *done* · <{ui}runs/3|open>",
    ]
    # The fallback text for Slack's notifications links nothing.
    assert "open>" not in slack.render(message)


@pytest.mark.parametrize(
    "page",
    [
        "javascript:alert(1)",
        "http://localhost/x|label",
        "http://localhost/<!channel>",
        "http://localhost/a b",
        "ftp://localhost/",
        "http://localhost/" + "x" * 2000,
        42,
    ],
)
def test_a_page_that_is_not_a_plain_url_is_not_linked(page: object) -> None:
    added = [{"ticket": "P-1", "reason": "r", "ui": page}]
    assert _texts(slack.blocks({"repo": "/r/api", "attention": {"added": added}}))[1] == ":bell: *P-1* · r"
