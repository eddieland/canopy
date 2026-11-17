"""Reading an agent's stdout: plain text, or OpenCode 2's JSON events (DESIGN §13)."""

import json
from pathlib import Path
from typing import Final

import pytest

from canopy.runtime.opencode2 import events
from canopy.runtime.report import AgentOutput, ToolUse, Usage

#: What OpenCode 2.1.2 printed for canopy's worker on a stand-in model, its paths replaced (2026-10-22): a shell call,
#: a skill loaded, a forced push and a read outside the worktree denied, and two texts.
RECORDED: Final = Path(__file__).parent / "recorded"
RESULT: Final = '{"status":"done","summary":"did it"}'
TOKENS: Final = {"input": 100, "output": 20, "reasoning": 3, "cache": {"read": 400, "write": 50}}


def event(kind: str, part: object, session: object = "ses_abc123") -> str:
    return json.dumps({"type": kind, "timestamp": 1, "sessionID": session, "part": part})


def start() -> str:
    return event("step_start", {"type": "step-start"})


def text(value: str) -> str:
    return event("text", {"type": "text", "text": value})


def step(cost: object = 0.25, tokens: object = TOKENS) -> str:
    return event("step_finish", {"type": "step-finish", "reason": "stop", "cost": cost, "tokens": tokens})


def error(value: object) -> str:
    return json.dumps({"type": "error", "timestamp": 1, "sessionID": "ses_abc123", "error": value})


def test_a_recorded_run_gives_its_text_session_and_tools_and_no_cost_for_its_lost_last_call() -> None:
    output = events.read((RECORDED / "run.jsonl").read_text())
    assert (output.text, output.last) == ("All done.\nFinal line.", "Final line.")
    assert output.session_id == "ses_e9efac2adffehb60wAIBaOM6if"
    assert output.tools == (
        ToolUse("shell", calls=2, errors=1, result_chars=len("hi\n") + len("Permission denied: shell")),
        ToolUse("skill:demo", calls=1, errors=0, result_chars=293),
        ToolUse("read", calls=1, errors=1, result_chars=len("Permission denied: external_directory")),
    )
    # Four calls printed their cost; the fifth, which wrote the texts, did not.
    assert output.usage is None
    assert output.errors == ()


def test_a_recorded_failure_reports_its_error_and_the_calls_before_it() -> None:
    output = events.read((RECORDED / "failed.jsonl").read_text())
    assert output.errors == ("provider.invalid-request: prompt is too long: 250000 tokens > 200000 maximum",)
    assert output.usage is not None
    assert (output.usage.input, output.usage.output) == (100, 20)


def test_plain_text_is_read_as_it_is() -> None:
    stdout = f"chatter\n{RESULT}\n"
    assert events.read(stdout) == AgentOutput(stdout, stdout)  # plain text is one message


def test_finished_calls_give_the_cost_the_peak_context_and_the_first_call() -> None:
    lines = [
        start(),
        text("Working on it."),
        step(0.25),
        start(),
        text(RESULT),
        step(1, {**TOKENS, "cache": {"read": 900, "write": 50}}),
        "not an event",
    ]
    output = events.read("\n".join(lines))
    assert output.text == f"Working on it.\n{RESULT}"
    assert output.usage == Usage(
        1.25,
        200,
        40,
        6,
        cache_read=1300,
        cache_write=100,
        peak_context=100 + 900 + 50,
        first_call=100 + 400 + 50,
        first_cache_write=50,
        first_cache_read=400,
    )


def test_a_call_that_never_finished_reports_no_cost_unless_an_error_took_its_place() -> None:
    unfinished = [start(), text("first"), step(), start(), text(RESULT)]
    assert events.read("\n".join(unfinished)).usage is None
    failed = [*unfinished, error({"type": "provider.overloaded", "message": "try later"})]
    assert events.read("\n".join(failed)).usage == events.read("\n".join(unfinished[:3])).usage


@pytest.mark.parametrize(
    "bad",
    [
        step(cost=-1),
        step(cost="0.25"),
        step(tokens={**TOKENS, "input": -1}),
        step(tokens={**TOKENS, "output": 1.5}),
        step(cost=1e300),
        step(tokens={k: v for k, v in TOKENS.items() if k != "cache"}),
        event("step_finish", "not a part"),
    ],
)
def test_a_step_that_does_not_validate_reports_no_cost(bad: str) -> None:
    output = events.read(f"{step()}\n{bad}\n{text(RESULT)}")
    assert output.usage is None
    assert (output.text, output.session_id) == (RESULT, "ses_abc123")


@pytest.mark.parametrize("session", ["", "ses abc", "ses_\x1b[31m", "x" * 101, 12, None])
def test_a_session_id_that_does_not_validate_is_not_reported(session: object) -> None:
    output = events.read(event("text", {"text": RESULT}, session))
    assert output.session_id is None
    assert output.text == RESULT


@pytest.mark.parametrize(
    ("value", "said"),
    [
        ({"type": "provider.auth", "message": "invalid x-api-key", "status": 401}, "provider.auth: invalid x-api-key"),
        ({"type": "aborted", "message": "Session interrupted: timeout"}, "aborted: Session interrupted: timeout"),
        ({"message": "it broke\nbadly"}, "it broke badly"),
        ({}, "error"),
        ("not an object", "error"),  # one canopy cannot read still says the session failed
        ({"type": "x" * 300}, "x" * 200),
    ],
)
def test_an_error_says_its_type_and_message_on_one_line(value: object, said: str) -> None:
    assert events.read(error(value)).errors == (said,)


def test_each_distinct_error_is_kept_in_order() -> None:
    first = {"type": "provider.overloaded", "message": "busy"}
    last = {"type": "unknown", "message": "Prompt was not promoted"}
    assert events.read("\n".join([error(first), error(first), error(last)])).errors == (
        "provider.overloaded: busy",
        "unknown: Prompt was not promoted",
    )


def tool(name: object, status: str = "completed", **state: object) -> str:
    return event("tool_use", {"type": "tool", "tool": name, "state": {"status": status, "input": {}, **state}})


def test_a_skill_call_is_counted_under_the_skill_it_loaded() -> None:
    def skill(status: str = "completed", **state: object) -> str:
        return tool("skill", status, **state)

    lines = [
        # OpenCode 2.1.2 takes the skill's id in the call's input, and nests the one it loaded in its metadata.
        skill(input={"id": "tracker-jira"}, metadata={"metadata": {"name": "tracker-jira"}}, output="x" * 10),
        skill(input={"id": "tracker-jira"}, output="y" * 5),
        skill("error", input={"id": "no-such-skill"}, error="Skill not found"),
        # A name that is not a skill's by OpenCode's rule counts as the tool alone, as does a call that names none.
        skill(input={"id": "Bad Name\u001b[31m"}, output="z"),
        skill(input={"id": "a" * 65}, output="z"),
        skill(metadata={"metadata": "not an object"}, output="z"),
        text(RESULT),
    ]
    assert events.read("\n".join(lines)).tools == (
        ToolUse("skill:tracker-jira", calls=2, errors=0, result_chars=15),
        ToolUse("skill:no-such-skill", calls=1, errors=1, result_chars=len("Skill not found")),
        ToolUse("skill", calls=3, errors=0, result_chars=3),
    )


def test_a_tally_says_what_read_would_of_the_lines_so_far() -> None:
    lines = (RECORDED / "run.jsonl").read_text().splitlines()
    tally = events.Tally()
    for line in lines:
        found = events.parse_event(line)
        assert found is not None
        tally.add(found)
    assert tally.tools == events.read("\n".join(lines)).tools
    # The four calls whose cost was printed, so far, while the fifth is still open.
    assert tally.usage is not None
    assert not tally.settled
    assert tally.usage.cost_usd == pytest.approx(0.00103625 + 0.00106625 + 0.00109625 + 0.00112625)
