"""The desktop sink canopy ships (DESIGN §20): `notify-send` on Linux, `osascript` on macOS."""

import io
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import override
from unittest import mock

import pytest

from canopy.infra.procs import SubprocessRunner
from canopy.notify import desktop
from tests.conftest import executable

# The fields of a `json` message the desktop sink reads; the rest of one it ignores.
MESSAGE = {
    "version": 1,
    "sink": "desktop",
    "repo": "/home/me/src/api",
    "sent_at": "2026-09-24T19:00:00Z",
    "text": "canopy attention: 1 new, 1 resolved\n+ PROJ-3 needs_reviewer: x\nFull list: /home/me/attention.md\n",
}


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


def test_help_never_waits_for_stdin(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_:
        desktop.run(["--help"], _Unread(), runner=SubprocessRunner(), platform="linux")
    assert exit_.value.code == 0
    assert "usage: canopy-notify-desktop" in capsys.readouterr().out


class _Unread(io.StringIO):
    @override
    def read(self, size: int | None = -1, /) -> str:
        raise AssertionError(f"--help read stdin ({size})")
