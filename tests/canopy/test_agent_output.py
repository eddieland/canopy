"""Reading an agent's stdout: plain text, or OpenCode's JSON events (DESIGN §13)."""

import json

import pytest

from canopy.core import agent_output
from canopy.core.agent_output import AgentOutput, Usage

RESULT = '{"status":"done","summary":"did it"}'
TOKENS = {"input": 100, "output": 20, "reasoning": 3, "cache": {"read": 400, "write": 50}}


def event(kind: str, part: object, session: object = "ses_abc123") -> str:
    return json.dumps({"type": kind, "timestamp": 1, "sessionID": session, "part": part})


def text(value: str) -> str:
    return event("text", {"type": "text", "text": value})


def step(cost: object = 0.25, tokens: object = TOKENS) -> str:
    return event("step_finish", {"type": "step-finish", "reason": "stop", "cost": cost, "tokens": tokens})


def test_plain_text_is_read_as_it_is() -> None:
    stdout = f"chatter\n{RESULT}\n"
    assert agent_output.read(stdout) == AgentOutput(stdout)


def test_events_give_the_text_the_session_and_the_cost() -> None:
    lines = [
        event("step_start", {"type": "step-start"}),
        text("Working on it.\nStill working."),
        event("tool_use", {"tool": "bash", "state": {"output": RESULT.replace("did it", "a tool's output")}}),
        step(0.25),
        text(RESULT),
        step(1),
        "not an event",
    ]
    output = agent_output.read("\n".join(lines))
    assert output.text == f"Working on it.\nStill working.\n{RESULT}"
    assert output.session_id == "ses_abc123"
    assert output.usage == Usage(1.25, input=200, output=40, reasoning=6, cache_read=800, cache_write=100)
    assert output.usage is not None
    assert output.usage.tokens == 2 * (100 + 20 + 3 + 400 + 50)


def test_a_result_line_is_not_an_event() -> None:
    # The fake agent and plain-text templates print the result contract alone; it has no type or session.
    assert agent_output.read(RESULT).text == RESULT


def test_events_with_no_model_call_cost_nothing() -> None:
    error = json.dumps({"type": "error", "timestamp": 1, "sessionID": "ses_abc123", "error": {"name": "UnknownError"}})
    output = agent_output.read(error)
    assert (output.text, output.session_id) == ("", "ses_abc123")
    assert output.usage == Usage(0, 0, 0, 0, 0, 0)


@pytest.mark.parametrize(
    "bad",
    [
        step(cost=-1),
        step(cost="0.25"),
        step(cost=None),
        step(tokens={**TOKENS, "input": -1}),
        step(tokens={**TOKENS, "output": 1.5}),
        step(tokens={**TOKENS, "input": 2**63}),
        step(cost=10**400),
        step(cost=1e300),
        step(tokens={k: v for k, v in TOKENS.items() if k != "cache"}),
        event("step_finish", "not a part"),
    ],
)
def test_a_step_that_does_not_validate_reports_no_cost(bad: str) -> None:
    # One unreadable step would make the total too low, so there is no total at all.
    output = agent_output.read(f"{step()}\n{bad}\n{text(RESULT)}")
    assert output.usage is None
    assert (output.text, output.session_id) == (RESULT, "ses_abc123")


def test_non_finite_cost_reports_no_cost() -> None:
    line = step().replace('"cost": 0.25', '"cost": Infinity')
    assert agent_output.read(line).usage is None


@pytest.mark.parametrize("session", ["", "ses abc", "ses_\x1b[31m", "x" * 101, 12, None])
def test_a_session_id_that_does_not_validate_is_not_reported(session: object) -> None:
    output = agent_output.read(event("text", {"text": RESULT}, session))
    assert output.session_id is None
    assert output.text == RESULT


def test_the_first_valid_session_id_is_kept() -> None:
    stdout = "\n".join([event("text", {"text": "a"}, "bad id"), text("b"), event("text", {"text": "c"}, "ses_other")])
    assert agent_output.read(stdout).session_id == "ses_abc123"


def test_a_text_part_that_does_not_validate_is_left_out() -> None:
    stdout = "\n".join([text("first"), event("text", {"text": 12}), event("text", None), text(RESULT)])
    assert agent_output.read(stdout).text == f"first\n{RESULT}"
