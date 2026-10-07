"""The sinks canopy ships (DESIGN §20): the desktop sink, and the Slack sink against a local HTTP server."""

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
    assert desktop.run([], json.dumps(MESSAGE), runner=SubprocessRunner(), platform="linux") == 0
    [argv] = [json.loads(line) for line in tools.read_text().splitlines()]
    assert argv[1:4] == ["--app-name=canopy", "--", "canopy: api"]
    assert argv[4] == "canopy attention: 1 new, 1 resolved\n+ PROJ-3 needs_reviewer: x"


def test_the_desktop_sink_passes_text_to_osascript_as_arguments(tools: Path) -> None:
    text = 'canopy attention: 1 new, 0 resolved\n+ PROJ-1 crashed: "quoted" and \\ backslash\nFull list: /x\n'
    assert desktop.run([], text, runner=SubprocessRunner(), platform="darwin") == 0
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
    assert desktop.run([], "hello\n", runner=SubprocessRunner(), platform="linux") == 2
    assert "notify-send is not installed" in capsys.readouterr().err
    assert desktop.run([], "", runner=SubprocessRunner(), platform="linux") == 2


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


def webhook_file(tmp_path: Path, url: str, mode: int = 0o600) -> Path:
    path = tmp_path / "slack-webhook"
    path.write_text(url + "\n")
    path.chmod(mode)
    return path


def test_the_slack_sink_posts_one_escaped_message(hook: str, tmp_path: Path) -> None:
    path = webhook_file(tmp_path, hook)
    assert slack.run(["--webhook-file", str(path)], json.dumps(MESSAGE), prefix="http://127.0.0.1:") == 0
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
    assert slack.run(["--webhook-file", str(path)], json.dumps(MESSAGE), prefix="http://127.0.0.1:") == 1
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
    assert slack.run(["--webhook-file", str(path)], json.dumps(MESSAGE)) == 2
    assert message in capsys.readouterr().err


def test_the_slack_sink_reads_its_default_file_and_needs_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert slack.default_webhook_file() == tmp_path / "canopy" / "slack-webhook"
    assert slack.run([], json.dumps(MESSAGE)) == 2
    assert f"cannot read the webhook file {tmp_path / 'canopy' / 'slack-webhook'}" in capsys.readouterr().err
    (tmp_path / "canopy").mkdir()
    webhook_file(tmp_path / "canopy", "https://hooks.slack.com/services/T/B/x")
    assert slack.run([], "canopy attention: 1 new\n") == 2
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
