"""A session's transcript read from OpenCode 2's JSON events, and what a running run's row says a tool call did."""

import json
from datetime import UTC, datetime
from pathlib import Path

from canopy.runtime.entries import Error, Step, Text, ToolCall
from canopy.runtime.opencode2 import events, transcript
from canopy.runtime.report import Called, Returned, Touch

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


def test_each_step_names_the_reply_it_wrote_as_the_sessions_record_names_it() -> None:
    """The recorded run's calls are replies of the recorded export of the same session, by their message's id."""
    lines = (RECORDED / "run.jsonl").read_text().splitlines()
    steps = [e for e in transcript.read(lines, SESSION) if isinstance(e, Step)]
    exported = json.loads((RECORDED / "export.json").read_text())["messages"]
    replies = [m["id"] for m in exported if m["type"] == "assistant"]
    # The last call's `step_finish` is lost to 2.1.2's race (`canopy.runtime.opencode2.events`).
    assert [s.message for s in steps] == replies[:-1]


def test_a_reply_id_canopy_would_not_keep_is_none() -> None:
    finished = {"type": "step-finish", "reason": "stop", "cost": 0.5}
    for named in ("msg 1", "x" * 101, ""):
        [step] = transcript.read([event("step_finish", {**finished, "messageID": named})], SESSION)
        assert isinstance(step, Step)
        assert step.message is None, named
    [step] = transcript.read([event("step_finish", finished)], SESSION)
    assert isinstance(step, Step)
    assert step.message is None


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
    # When it started, as the runtime printed it, which says what a `messages` call fetched (DESIGN §44).
    timed: dict[str, object] = {"status": "completed", "input": {}, "time": {"start": 1_762_423_200_500, "end": 1}}
    found = called(tool("canopy_run_messages", timed))
    assert found is not None
    assert found.started_at == datetime(2025, 11, 6, 10, 0, 0, 500_000, UTC)


def test_what_a_tool_call_did_to_files_is_its_act_and_the_files_it_named() -> None:
    """2's tools name a file by `path`, a session moved from 1 by `filePath`; `patch` and `shell` are 2's names."""

    def touched(tool: str, given: dict[str, object]) -> Touch:
        return transcript.touched(Called(tool, completed=True, input=given))

    assert touched("read", {"path": "/w/src/a.py"}) == Touch("read", ("/w/src/a.py",))
    assert touched("read", {"filePath": "/w/src/a.py"}) == Touch("read", ("/w/src/a.py",))
    assert touched("edit", {"path": "src/a.py", "oldString": "a", "newString": "b"}) == Touch("edit", ("src/a.py",))
    assert touched("write", {"path": "b.py", "content": ""}) == Touch("edit", ("b.py",))
    patch = "*** Begin Patch\n*** Delete File: old.py\n*** Update File: src/a.py\n@@\n-a\n+b\n*** End Patch"
    assert touched("patch", {"patchText": patch}) == Touch("edit", ("old.py", "src/a.py"))
    assert touched("grep", {"pattern": "parse"}) == Touch("search")
    assert touched("glob", {"pattern": "**/*.py"}) == Touch("search")
    assert touched("shell", {"command": "git grep parse"}) == Touch("search")
    assert touched("shell", {"command": "uv run pytest"}) == Touch("other")
    assert touched("bash", {"command": "rg parse"}) == Touch("other")  # 1's name for the shell
    assert touched("edit", {}) == Touch("other")


def test_what_a_call_returned_is_its_output_or_error_and_whether_its_tools_metadata_says_it_was_cut() -> None:
    """2.1.4 nests the tool's metadata under the call's, as the recorded run shows; a session moved from 1 does not."""

    def returned(line: str) -> Returned | None:
        found = events.parse_event(line)
        assert found is not None
        return transcript.returned(found)

    recorded = [
        transcript.returned(found)
        for line in (RECORDED / "run.jsonl").read_text().splitlines()
        if (found := events.parse_event(line)) is not None and found["type"] == events.TOOL_USE
    ]
    # Its shell call and its skill's say they were not cut; its refused shell and its failed read say nothing.
    assert [r.cut if r is not None else "?" for r in recorded] == [False, False, None, None]
    shell: dict[str, object] = {"status": "completed", "input": {"command": "gh run view 7"}, "output": "x" * 50}
    nested = {"metadata": {"status": "completed", "truncated": True, "exit": 0}, "rawInput": "{}"}
    assert returned(tool("shell", {**shell, "metadata": nested})) == Returned(50, cut=True)
    assert returned(tool("shell", {**shell, "metadata": {"truncated": False}})) == Returned(50, cut=False)
    assert returned(tool("shell", {**shell, "metadata": {"rawInput": "{}"}})) == Returned(50, cut=None)
    assert returned(tool("read", {"status": "error", "input": {}, "error": "no such file"})) == Returned(12)
    assert returned(tool("shell", {"status": "running"})) is None
    assert returned(event("text", {"type": "text", "text": "hi"})) is None


def test_the_command_a_call_ran_is_its_shell_input() -> None:
    assert transcript.command(Called("shell", completed=True, input={"command": "gh pr view 3"})) == "gh pr view 3"
    assert transcript.command(Called("bash", completed=True, input={"command": "ls"})) is None  # 1's name
    assert transcript.command(Called("shell", completed=True, input={"command": 3})) is None
    assert transcript.command(Called("read", completed=True, input={"path": "a.py"})) is None


def test_a_line_is_of_a_session_when_it_is_an_event_that_names_it() -> None:
    assert transcript.in_session(tool("grep", {"status": "completed", "input": {}}), SESSION)
    assert not transcript.in_session(tool("grep", {"status": "completed", "input": {}}), "ses_other")
    assert not transcript.in_session("not an event", SESSION)
