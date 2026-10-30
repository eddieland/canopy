"""A session's transcript read from OpenCode's JSON events: what a running run's row says a tool call did."""

import json

from canopy.runtime.opencode import events, transcript
from canopy.runtime.report import Called

BASH: dict[str, object] = {
    "status": "completed",
    "input": {"command": "uv run pytest -q", "description": "Run the tests"},
    "output": "3 passed\n",
    "title": "Run the tests",
}


def event(kind: str, part: object) -> str:
    return json.dumps({"type": kind, "timestamp": 1, "sessionID": "ses_abc123", "part": part})


def tool(name: str, state: dict[str, object]) -> str:
    return event("tool_use", {"type": "tool", "callID": "call_1", "tool": name, "state": state})


def test_what_a_tool_call_did_is_its_command_else_its_title_on_one_line() -> None:
    def did(line: str) -> tuple[str, str] | None:
        found = events.parse_event(line)
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


def test_a_tool_call_as_the_agent_made_it_is_its_exact_name_how_it_ended_and_its_input() -> None:
    def called(line: str) -> Called | None:
        found = events.parse_event(line)
        assert found is not None
        return transcript.called(found)

    card = {"summary": "Half done.", "now": "testing"}
    assert called(tool("canopy_run_status", {"status": "completed", "input": card, "output": "ok"})) == Called(
        "canopy_run_status",
        completed=True,
        input=card,
    )
    refused = called(tool("canopy_run_status", {"status": "error", "input": {}, "error": "no"}))
    assert refused == Called("canopy_run_status", completed=False, input={})
    assert called(tool("bash", {"status": "running"})) is None  # printed only once it ends
    assert called(event("text", {"type": "text", "text": "hi"})) is None
