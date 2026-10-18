"""A session's transcript, read back from the events a run's log holds (DESIGN §13, §22)."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from canopy.core import agent_output, transcript
from canopy.core.transcript import Error, Step, Text, Tokens, ToolCall

SESSION = "ses_abc123"
T = 1_791_460_800_000  # 2026-10-08 12:00 UTC, in milliseconds
AT = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def event(kind: str, part: object, session: str = SESSION, ms: int = T, **extra: object) -> str:
    return json.dumps({"type": kind, "timestamp": ms, "sessionID": session, "part": part, **extra})


def tool(name: str, state: dict[str, object], session: str = SESSION) -> str:
    return event("tool_use", {"type": "tool", "callID": "call_1", "tool": name, "state": state}, session)


BASH: dict[str, object] = {
    "status": "completed",
    "input": {"command": "uv run pytest -q", "description": "Run the tests"},
    "output": "3 passed\n",
    "title": "Run the tests",
    "metadata": {"exit": 0},
    "time": {"start": T, "end": T + 2500},
}


def log(tmp_path: Path, *lines: str) -> Path:
    # As a run log holds them: setup output and the harness's markers around the agent's events, then its stderr.
    path = tmp_path / "1.log"
    body = ["--- setup web stdout ---", "ok", "--- worker stdout ---", *lines, "--- worker stderr ---", "warn"]
    path.write_text("\n".join(body) + "\n")
    return path


def test_a_session_reads_as_its_text_tool_calls_steps_and_errors_in_order(tmp_path: Path) -> None:
    path = log(
        tmp_path,
        event("step_start", {"type": "step-start"}),
        event("reasoning", {"type": "reasoning", "text": "The tests first."}),
        event("text", {"type": "text", "text": "Running the tests."}),
        tool("bash", BASH),
        tool("read", {"status": "error", "input": {"filePath": "/x"}, "error": "no such file", "time": {}}),
        event(
            "step_finish",
            {
                "type": "step-finish",
                "reason": "tool-calls",
                "cost": 0.25,
                "tokens": {"input": 100, "output": 20, "reasoning": 3, "cache": {"read": 400, "write": 50}},
            },
        ),
        json.dumps({"type": "error", "timestamp": T, "sessionID": SESSION, "error": {"name": "APIError"}}),
    )
    found = transcript.read(path, SESSION)
    assert found is not None
    assert found.entries == [
        Text(AT, "The tests first.", reasoning=True, call=1),
        Text(AT, "Running the tests.", call=1),
        ToolCall(
            AT,
            "bash",
            "completed",
            "Run the tests",
            '{\n  "command": "uv run pytest -q",\n  "description": "Run the tests"\n}',
            "3 passed\n",
            2500,
            call=1,
        ),
        ToolCall(AT, "read", "error", None, '{\n  "filePath": "/x"\n}', "no such file", None, call=1),
        Step(AT, "tool-calls", 0.25, Tokens(100, 20, 3, 400, 50), call=1),
        Error(AT, "APIError", "", call=1),
    ]
    assert (found.truncated, found.unreadable) == (False, 0)


def test_each_entry_is_numbered_by_the_model_call_the_runtime_started_it_in(tmp_path: Path) -> None:
    # Another session's calls do not count, and an entry before the first call has no number.
    path = log(
        tmp_path,
        json.dumps({"type": "error", "timestamp": T, "sessionID": SESSION, "error": {"name": "early"}}),
        event("step_start", {"type": "step-start"}),
        event("text", {"type": "text", "text": "one"}),
        event("step_start", {"type": "step-start"}, session="ses_other"),
        event("step_finish", {"type": "step-finish", "reason": "tool-calls"}),
        event("step_start", {"type": "step-start"}),
        event("text", {"type": "text", "text": "two"}),
    )
    found = transcript.read(path, SESSION)
    assert found is not None
    assert [e.call for e in found.entries] == [None, 1, 1, 2]


def test_only_the_recorded_sessions_events_are_read(tmp_path: Path) -> None:
    # A subagent's session, a stray line shaped like an event, and plain output are not this session's.
    path = log(
        tmp_path,
        event("text", {"type": "text", "text": "mine"}),
        event("text", {"type": "text", "text": "a subagent's"}, session="ses_child"),
        '{"type": "text", "part": {"text": "no session"}}',
        "not json at all",
    )
    found = transcript.read(path, SESSION)
    assert found is not None
    assert [e.text for e in found.entries if isinstance(e, Text)] == ["mine"]


def test_reasoning_with_no_text_is_left_out(tmp_path: Path) -> None:
    # A provider's redacted thinking arrives as reasoning with no text.
    path = log(
        tmp_path,
        event("reasoning", {"type": "reasoning", "text": ""}),
        event("reasoning", {"type": "reasoning", "text": " \n"}),
        event("text", {"type": "text", "text": "done"}),
    )
    found = transcript.read(path, SESSION)
    assert found is not None
    assert found.entries == [Text(AT, "done")]
    assert found.unreadable == 0


def test_an_event_that_does_not_validate_is_counted_and_left_out(tmp_path: Path) -> None:
    path = log(
        tmp_path,
        event("text", {"type": "text", "text": 7}),
        tool("bash", {**BASH, "status": "running"}),
        event("step_finish", {"cost": -1}),
        event("text", {"type": "text", "text": "fine"}),
    )
    found = transcript.read(path, SESSION)
    assert found is not None
    assert found.entries == [Text(AT, "fine")]
    assert found.unreadable == 3


def test_text_is_shown_without_control_characters_and_cut(tmp_path: Path) -> None:
    long = "x" * (transcript.MAX_TEXT + 10)
    path = log(
        tmp_path,
        event("text", {"type": "text", "text": "a\x1b[31mred\x07\r\nline"}),
        tool("bash", {**BASH, "output": long, "title": "two\nlines"}),
    )
    found = transcript.read(path, SESSION)
    assert found is not None
    first, second = found.entries
    assert first == Text(AT, "a [31mred \nline")
    assert isinstance(second, ToolCall)
    assert (len(second.output), second.cut, second.title) == (transcript.MAX_TEXT, True, "two lines")
    assert found.truncated


def test_a_bad_timestamp_is_no_time(tmp_path: Path) -> None:
    path = log(tmp_path, event("text", {"type": "text", "text": "when?"}, ms=-1))
    found = transcript.read(path, SESSION)
    assert found is not None
    assert found.entries == [Text(None, "when?")]


def test_entries_past_the_bounds_are_left_out_and_say_so(tmp_path: Path) -> None:
    with mock.patch.object(transcript, "MAX_ENTRIES", 2):
        path = log(tmp_path, *(event("text", {"type": "text", "text": str(i)}) for i in range(5)))
        found = transcript.read(path, SESSION)
        assert found is not None
        assert ([e.text for e in found.entries if isinstance(e, Text)], found.truncated) == (["0", "1"], True)

    with mock.patch.object(transcript, "MAX_ENTRIES", 100), mock.patch.object(transcript, "MAX_CHARS", 5):
        lines = (event("text", {"type": "text", "text": "abc"}) for _ in range(3))
        found = transcript.read(log(tmp_path, *lines), SESSION)
        assert found is not None
        assert (len(found.entries), found.truncated) == (1, True)


def test_a_log_past_the_byte_bound_is_read_to_its_last_whole_line(tmp_path: Path) -> None:
    lines = [event("text", {"type": "text", "text": str(i)}) for i in range(3)]
    path = tmp_path / "1.log"
    path.write_text("\n".join(lines) + "\n")
    with mock.patch.object(transcript, "MAX_BYTES", len(lines[0]) + len(lines[1]) + 10):
        found = transcript.read(path, SESSION)
    assert found is not None
    assert ([e.text for e in found.entries if isinstance(e, Text)], found.truncated) == (["0", "1"], True)


def test_a_missing_log_a_symlink_a_directory_and_a_fifo_are_not_read(tmp_path: Path) -> None:
    target = log(tmp_path, event("text", {"type": "text", "text": "secret"}))
    link = tmp_path / "link.log"
    link.symlink_to(target)
    assert transcript.read(tmp_path / "missing.log", SESSION) is None
    assert transcript.read(link, SESSION) is None
    assert transcript.read(tmp_path, SESSION) is None
    # Nothing writes to it: reading it would wait forever.
    fifo = tmp_path / "fifo.log"
    os.mkfifo(fifo)
    assert transcript.read(fifo, SESSION) is None


def test_a_files_tail_is_its_end_as_written_from_a_whole_line_without_control_characters(tmp_path: Path) -> None:
    path = tmp_path / "1.log"
    path.write_bytes("first line\nsecond, ünïcode\n--- stderr ---\nbell\x07 and \x1b escape\n".encode())
    found = transcript.tail(path)
    assert found == transcript.Tail(
        "first line\nsecond, ünïcode\n--- stderr ---\nbell  and   escape\n", path.stat().st_size, truncated=False
    )
    # Past the bound, the cut lands inside a character, and the text starts at the next whole line.
    with mock.patch.object(transcript, "MAX_TAIL", path.stat().st_size - len("first line\nsecond, ü")):
        cut = transcript.tail(path)
    assert cut is not None
    assert (cut.text, cut.size, cut.truncated) == ("--- stderr ---\nbell  and   escape\n", path.stat().st_size, True)


def test_a_missing_file_a_symlink_a_directory_and_a_fifo_have_no_tail(tmp_path: Path) -> None:
    target = log(tmp_path, "secret")
    link = tmp_path / "link.log"
    link.symlink_to(target)
    fifo = tmp_path / "fifo.log"
    os.mkfifo(fifo)
    for path in (tmp_path / "missing.log", link, tmp_path, fifo):
        assert transcript.tail(path) is None


def test_a_prompt_is_kept_beside_its_log_and_read_whole_without_control_characters(tmp_path: Path) -> None:
    path = transcript.prompt_path(tmp_path / "7.log")
    assert path == tmp_path / "7.prompt"
    path.write_text("# canopy worker\x1b[2J\n\nWork ABC-1.\n")
    assert transcript.prompt(path) == transcript.Prompt("# canopy worker [2J\n\nWork ABC-1.\n", truncated=False)


def test_a_prompt_past_its_bound_is_cut_and_says_so(tmp_path: Path) -> None:
    path = tmp_path / "7.prompt"
    path.write_text("x" * 12)
    with mock.patch.object(transcript, "MAX_PROMPT", 10):
        assert transcript.prompt(path) == transcript.Prompt("x" * 10, truncated=True)


def test_a_missing_prompt_a_symlink_and_a_directory_are_not_read(tmp_path: Path) -> None:
    real = tmp_path / "real.prompt"
    real.write_text("hi")
    (tmp_path / "link.prompt").symlink_to(real)
    (tmp_path / "dir.prompt").mkdir()
    for name in ("missing.prompt", "link.prompt", "dir.prompt"):
        assert transcript.prompt(tmp_path / name) is None


def test_what_a_tool_call_did_is_its_command_else_its_title_on_one_line() -> None:
    def did(line: str) -> tuple[str, str] | None:
        found = agent_output.parse_event(line)
        assert found is not None
        return transcript.did(found)

    assert did(tool("bash", BASH)) == ("bash", "uv run pytest -q")  # not what the agent said it was for
    read: dict[str, object] = {
        "status": "completed",
        "input": {"filePath": "/w/a.py"},
        "output": "",
        "title": "a.py\nb",
    }
    assert did(tool("read", read)) == ("read", "a.py b")
    assert did(tool("todowrite", {"status": "error", "input": {}, "error": "no"})) == ("todowrite", "")
    assert did(tool("bash", {"status": "running"})) is None  # printed only once it ends
    assert did(event("text", {"type": "text", "text": "hi"})) is None
