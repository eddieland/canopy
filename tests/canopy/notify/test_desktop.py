"""The desktop sink canopy ships (DESIGN §20): `notify-send` on Linux, `osascript` on macOS."""

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Final
from unittest import mock

import pytest

from canopy.infra.procs import SubprocessRunner
from canopy.notify import desktop
from canopy.notify.desktop import Notifier
from tests.conftest import executable, invoke

# The fields of a `json` message the desktop sink reads; the rest of one it ignores.
MESSAGE: Final = {
    "version": 1,
    "sink": "desktop",
    "repo": "/home/me/src/api",
    "sent_at": "2026-09-24T19:00:00Z",
    "text": "canopy attention: 1 new, 1 resolved\n+ PROJ-3 needs_reviewer: x\nFull list: /home/me/attention.md\n",
}
#: The sink as it runs on Linux, its notifier run for real.
LINUX: Final = Notifier(SubprocessRunner(), "linux")


@pytest.fixture
def tools(tmp_path: Path) -> Iterator[Path]:
    """`notify-send` and `osascript` on PATH, each appending its argv as a JSON line to the returned file."""
    calls = tmp_path / "calls.jsonl"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("notify-send", "osascript"):
        tool = bin_dir / name
        record = f"open({str(calls)!r}, 'a').write(json.dumps(sys.argv) + '\\n')"
        executable(tool, f"#!/usr/bin/env python3\nimport json, sys\n{record}\n")
    with mock.patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}):
        yield calls


def test_the_desktop_sink_shows_a_json_message(tools: Path) -> None:
    assert invoke(desktop.main, stdin=json.dumps(MESSAGE), obj=LINUX).exit_code == 0
    [argv] = [json.loads(line) for line in tools.read_text().splitlines()]
    assert argv[1:4] == ["--app-name=canopy", "--", "canopy: api"]
    assert argv[4] == "canopy attention: 1 new, 1 resolved\n+ PROJ-3 needs_reviewer: x"


def test_the_desktop_sink_passes_text_to_osascript_as_arguments(tools: Path) -> None:
    text = 'canopy attention: 1 new, 0 resolved\n+ PROJ-1 crashed: "quoted" and \\ backslash\nFull list: /x\n'
    assert invoke(desktop.main, stdin=text, obj=Notifier(SubprocessRunner(), "darwin")).exit_code == 0
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


def test_the_desktop_sink_without_its_tool(tmp_path: Path) -> None:
    with mock.patch.dict(os.environ, {"PATH": str(tmp_path)}):
        shown = invoke(desktop.main, stdin="hello\n", obj=LINUX)
        assert shown.exit_code == 2
        assert "notify-send is not installed" in shown.stderr
        assert invoke(desktop.main, stdin="", obj=LINUX).exit_code == 2


def test_the_command_line_is_read_before_stdin() -> None:
    helped = invoke(desktop.main, ["--help"], stdin="hello\n", obj=LINUX)
    assert helped.exit_code == 0
    assert helped.stdout.startswith("Usage: canopy-notify-desktop [OPTIONS]")
    refused = invoke(desktop.main, ["--nope"], stdin="hello\n", obj=LINUX)
    assert refused.exit_code == 2
    assert "No such option '--nope'" in refused.stderr
