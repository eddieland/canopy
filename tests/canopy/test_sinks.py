"""The sinks canopy ships (DESIGN §20): the desktop sink, and the Slack sink against a local HTTP server."""

import io
import json
import os
import threading
from collections.abc import Generator, Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar, override
from unittest import mock

import canopy_notify_slack as slack
import pytest

from canopy.infra.procs import SubprocessRunner
from canopy.notify import desktop

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


# Desktop


@pytest.fixture
def tools(tmp_path: Path) -> Iterator[Path]:
    """`notify-send` and `osascript` on PATH, each appending its argv as a JSON line to the returned file."""
    calls = tmp_path / "calls.jsonl"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("notify-send", "osascript"):
        tool = bin_dir / name
        tool.write_text(
            f"#!/usr/bin/env python3\nimport json, sys\nopen({str(calls)!r}, 'a').write(json.dumps(sys.argv) + '\\n')\n"
        )
        tool.chmod(0o755)
    with mock.patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}):
        yield calls


def test_the_desktop_sink_shows_a_json_message(tools: Path) -> None:
    assert desktop.run([], io.StringIO(json.dumps(MESSAGE)), runner=SubprocessRunner(), platform="linux") == 0
    [argv] = [json.loads(line) for line in tools.read_text().splitlines()]
    assert argv[1:4] == ["--app-name=canopy", "--", "canopy: api"]
    assert argv[4] == "canopy attention: 1 new, 1 resolved\n+ PROJ-3 needs_reviewer: x"


def test_the_desktop_sink_passes_text_to_osascript_as_arguments(tools: Path) -> None:
    text = 'canopy attention: 1 new, 0 resolved\n+ PROJ-1 crashed: "quoted" and \\ backslash\nFull list: /x\n'
    assert desktop.run([], io.StringIO(text), runner=SubprocessRunner(), platform="darwin") == 0
    [argv] = [json.loads(line) for line in tools.read_text().splitlines()]
    assert argv[1:7] == [
        "-e",
        "on run argv",
        "-e",
        "display notification (item 2 of argv) with title (item 1 of argv)",
        "-e",
        "end run",
    ]
    assert argv[7:] == ["canopy", 'canopy attention: 1 new, 0 resolved\n+ PROJ-1 crashed: "quoted" and \\ backslash']


def test_the_desktop_sink_bounds_its_body() -> None:
    title, body = desktop.message("\n".join(f"line {n}" for n in range(30)))
    assert title == "canopy"
    assert body.splitlines()[-1] == "... and 19 more lines"
    assert len(body.splitlines()) == desktop.MAX_LINES


def test_the_desktop_sink_without_its_tool(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with mock.patch.dict(os.environ, {"PATH": str(tmp_path)}):
        assert desktop.run([], io.StringIO("hello\n"), runner=SubprocessRunner(), platform="linux") == 2
        assert "notify-send is not installed" in capsys.readouterr().err
        assert desktop.run([], io.StringIO(""), runner=SubprocessRunner(), platform="linux") == 2


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


def _texts(blocks: list[dict[str, Any]]) -> list[str]:
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
    with pytest.raises(SystemExit) as desktop_exit:
        desktop.run(["--help"], _Unread(), runner=SubprocessRunner(), platform="linux")
    with pytest.raises(SystemExit) as slack_exit:
        slack.run(["--help"], _Unread())
    assert (desktop_exit.value.code, slack_exit.value.code) == (0, 0)
    out = capsys.readouterr().out
    assert "usage: canopy-notify-desktop" in out
    assert "usage: canopy-notify-slack" in out
    # How to run each from a release's single executable (D067).
    assert "exec env SCIE_BOOT=canopy-notify-desktop /path/to/canopy" in out
    assert "exec env SCIE_BOOT=canopy-notify-slack /path/to/canopy" in out


# Slack with a bot token


class _Api(BaseHTTPRequestHandler):
    received: ClassVar[list[tuple[str | None, dict[str, Any]]]] = []
    reply: ClassVar[dict[str, Any]] = {"ok": True}

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        _Api.received.append((self.headers["Authorization"], json.loads(self.rfile.read(length))))
        # Like the Web API: 200 even when the post is refused.
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(_Api.reply).encode())

    @override
    def log_message(self, format: str, *args: Any) -> None:
        del format, args


@pytest.fixture
def api() -> Generator[str]:
    """A local stand-in for Slack's `chat.postMessage`. Yields its URL."""
    _Api.received = []
    _Api.reply = {"ok": True}
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
    ],
)
def test_a_token_and_a_webhook_are_not_mixed(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        slack.run(argv, io.StringIO(json.dumps(MESSAGE)))
    assert exited.value.code == 2
    assert "canopy-notify-slack: error:" in capsys.readouterr().err
