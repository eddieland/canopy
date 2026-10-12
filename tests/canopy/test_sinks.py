"""The sinks canopy ships (DESIGN §20): the desktop sink, and the Slack sink against a local HTTP server."""

import io
import json
import os
import threading
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar, override

import canopy_notify_slack as slack
import pytest

from canopy.infra.procs import SubprocessRunner
from canopy.notify import desktop

MESSAGE = {
    "version": 1,
    "sink": "slack",
    "repo": "/home/me/src/api",
    "sent_at": "2026-09-24T19:00:00Z",
    "attention": {
        "added": [
            {"ticket": "PROJ-3", "repo": None, "reason": "needs_reviewer", "detail": "<!channel> https://x.test/1"}
        ],
        "resolved": [{"ticket": "PROJ-4", "repo": "web", "reason": "ready_to_merge"}],
        "open": 4,
        "path": "/home/me/.canopy/attention.md",
    },
    "events": [{"id": 88, "kind": "run.ended", "line": "< PROJ-12 run 41 implement ended done: <https://evil|click>"}],
    "omitted": 0,
    "digest": None,
    "text": "canopy attention: 1 new, 1 resolved\n+ PROJ-3 needs_reviewer: x\nFull list: /home/me/attention.md\n",
}


# Desktop


@pytest.fixture
def tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return calls


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


def test_the_desktop_sink_without_its_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
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
    assert set(posted) == {"text"}
    assert posted["text"].splitlines() == [
        "*canopy* · api: 1 new, 1 resolved, 4 open, 1 event",
        "+ *PROJ-3* needs_reviewer: &lt;!channel&gt; https://x.test/1",
        "- *PROJ-4 (web)* ready_to_merge",
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
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
    assert set(posted) == {"channel", "text"}
    assert posted["channel"] == "C0123ABCD"
    assert posted["text"].splitlines()[1] == "+ *PROJ-3* needs_reviewer: &lt;!channel&gt; https://x.test/1"


def test_the_token_file_defaults_to_the_config_directory(
    api: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "canopy").mkdir()
    token_file(tmp_path / "canopy")
    assert slack.run(["--channel", "#canopy"], io.StringIO(json.dumps(MESSAGE)), api_url=api) == 0
    assert _Api.received[0][1]["channel"] == "#canopy"


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
    "argv",
    [["--token-file", "/x"], ["--channel", "C0123ABCD", "--webhook-file", "/x"]],
)
def test_a_token_and_a_webhook_are_not_mixed(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        slack.run(argv, io.StringIO(json.dumps(MESSAGE)))
    assert exited.value.code == 2
    assert "canopy-notify-slack: error:" in capsys.readouterr().err
