"""A session's transcript read from OpenCode 2's JSON events, and what a running run's row says a tool call did."""

import json
from pathlib import Path

from canopy.runtime.entries import Error, Step, Text, ToolCall
from canopy.runtime.opencode2 import events, transcript

RECORDED = Path(__file__).parent / "recorded"
SESSION = "ses_e9efac2adffehb60wAIBaOM6if"


def event(kind: str, part: object) -> str:
    return json.dumps({"type": kind, "timestamp": 1, "sessionID": SESSION, "part": part})


def tool(name: str, state: dict[str, object]) -> str:
    return event("tool_use", {"type": "tool", "tool": name, "state": state})


def test_a_recorded_run_reads_as_its_entries_each_numbered_by_its_model_call() -> None:
    lines = (RECORDED / "run.jsonl").read_text().splitlines()
    found = list(transcript.read(["stderr chatter", *lines], SESSION))
    assert None not in found
    kinds = [(type(e).__name__, e.call) for e in found if e is not None]
    assert kinds == [
        ("Text", 1),  # its reasoning
        ("ToolCall", 1),
        ("Step", 1),
        ("ToolCall", 2),
        ("Step", 2),
        ("ToolCall", 3),
        ("Step", 3),
        ("ToolCall", 4),
        ("Step", 4),
        ("Text", 5),
        ("Text", 5),
    ]
    reasoning, shell, step = found[0], found[1], found[2]
    assert isinstance(reasoning, Text)
    assert (reasoning.text, reasoning.reasoning) == ("Plan.", True)
    assert isinstance(shell, ToolCall)
    assert (shell.tool, shell.title, shell.status, shell.output) == ("shell", "echo hi", "completed", "hi\n")
    assert shell.duration_ms == 113
    assert isinstance(step, Step)
    assert (step.reason, step.cost_usd) == ("tool-calls", 0.00103625)
    denied = found[5]
    assert isinstance(denied, ToolCall)
    assert (denied.status, denied.output) == ("error", "Permission denied: shell")


def test_another_sessions_events_are_left_out() -> None:
    assert list(transcript.read((RECORDED / "run.jsonl").read_text().splitlines(), "ses_other")) == []


def test_an_error_reads_as_its_type_and_message() -> None:
    lines = (RECORDED / "failed.jsonl").read_text().splitlines()
    session = json.loads(lines[0])["sessionID"]
    last = list(transcript.read(lines, session))[-1]
    assert isinstance(last, Error)
    assert (last.name, last.message) == (
        "provider.invalid-request",
        "prompt is too long: 250000 tokens > 200000 maximum",
    )


def test_what_a_tool_call_did_is_its_command_else_what_its_input_names_on_one_line() -> None:
    def did(line: str) -> tuple[str, str] | None:
        found = events.parse_event(line)
        assert found is not None
        return transcript.did(found)

    shell: dict[str, object] = {
        "status": "completed",
        "input": {"command": "uv run pytest -q", "description": "Run the tests"},
    }
    assert did(tool("shell", shell)) == ("shell", "uv run pytest -q")  # not what the agent said it was for
    assert did(tool("read", {"status": "completed", "input": {"path": "/w/a.py\nb"}})) == ("read", "/w/a.py b")
    assert did(tool("grep", {"status": "completed", "input": {"pattern": "TODO", "path": ""}})) == ("grep", "TODO")
    assert did(tool("skill", {"status": "completed", "input": {"id": "tracker-jira"}})) == ("skill", "tracker-jira")
    assert did(tool("todowrite", {"status": "error", "input": {}, "error": "no"})) == ("todowrite", "")
    assert did(tool("shell", {"status": "running"})) is None  # printed only once it ends
    assert did(event("text", {"type": "text", "text": "hi"})) is None
