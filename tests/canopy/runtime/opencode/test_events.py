"""Reading an agent's stdout: plain text, or OpenCode's JSON events (DESIGN §13)."""

import json

import pytest

from canopy.runtime.opencode import events
from canopy.runtime.report import AgentOutput, ToolUse, Usage

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
    assert events.read(stdout) == AgentOutput(stdout, stdout)  # plain text is one message


def test_events_give_the_text_the_session_the_cost_the_peak_context_and_the_first_call() -> None:
    lines = [
        event("step_start", {"type": "step-start"}),
        text("Working on it.\nStill working."),
        event("tool_use", {"tool": "bash", "state": {"output": RESULT.replace("did it", "a tool's output")}}),
        step(0.25),
        text(RESULT),
        step(1, {**TOKENS, "cache": {"read": 900, "write": 50}}),
        "not an event",
    ]
    output = events.read("\n".join(lines))
    assert output.text == f"Working on it.\nStill working.\n{RESULT}"
    assert output.last == RESULT
    assert output.session_id == "ses_abc123"
    peak = 100 + 900 + 50  # the second call's input, cache read, and cache write
    first = 100 + 400 + 50  # the first call's
    assert output.usage == Usage(
        1.25,
        200,
        40,
        6,
        cache_read=1300,
        cache_write=100,
        peak_context=peak,
        first_call=first,
        first_cache_write=50,
        first_cache_read=400,
    )
    assert output.usage is not None
    assert output.usage.new_tokens == 2 * (100 + 50 + 20 + 3)  # every kind but the cache reads
    assert output.usage.describe() == "$1.25, 346 tokens, 1.1k peak context"


def test_a_cost_recorded_before_the_peak_context_was_kept_says_none() -> None:
    usage = Usage(0.5, input=9000, output=1000, reasoning=0, cache_read=40_000, cache_write=0)
    assert usage.describe() == "$0.50, 10.0k tokens"
    assert usage.spent() == {"cost_usd": 0.5, "new_tokens": 10_000, "peak_context": None}


def test_a_result_line_is_not_an_event() -> None:
    # The fake agent and plain-text templates print the result contract alone; it has no type or session.
    assert events.read(RESULT).text == RESULT


def test_events_with_no_model_call_cost_nothing() -> None:
    error = json.dumps({"type": "error", "timestamp": 1, "sessionID": "ses_abc123", "error": {"name": "UnknownError"}})
    output = events.read(error)
    assert (output.text, output.last, output.session_id) == ("", "", "ses_abc123")
    assert output.usage == Usage(0, 0, 0, 0, 0, 0, peak_context=0)  # and no first call


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
    output = events.read(f"{step()}\n{bad}\n{text(RESULT)}")
    assert output.usage is None
    assert (output.text, output.session_id) == (RESULT, "ses_abc123")


def test_non_finite_cost_reports_no_cost() -> None:
    line = step().replace('"cost": 0.25', '"cost": Infinity')
    assert events.read(line).usage is None


@pytest.mark.parametrize("session", ["", "ses abc", "ses_\x1b[31m", "x" * 101, 12, None])
def test_a_session_id_that_does_not_validate_is_not_reported(session: object) -> None:
    output = events.read(event("text", {"text": RESULT}, session))
    assert output.session_id is None
    assert output.text == RESULT


def test_the_first_valid_session_id_is_kept() -> None:
    stdout = "\n".join([event("text", {"text": "a"}, "bad id"), text("b"), event("text", {"text": "c"}, "ses_other")])
    assert events.read(stdout).session_id == "ses_abc123"


def test_a_text_part_that_does_not_validate_is_left_out() -> None:
    stdout = "\n".join([text("first"), event("text", {"text": 12}), event("text", None), text(RESULT)])
    assert events.read(stdout).text == f"first\n{RESULT}"


def error(value: object) -> str:
    return json.dumps({"type": "error", "timestamp": 1, "sessionID": "ses_abc123", "error": value})


def test_each_distinct_error_is_reported_on_one_line_in_order() -> None:
    """As OpenCode prints an error it did not expect, its ref says where its own log has the detail."""
    overflow = {"name": "ContextOverflowError", "data": {"message": "too long"}}
    server = {"name": "UnknownError", "data": {"message": "Unexpected server error.\nCheck logs.", "ref": "err_ccf1"}}
    lines = [text("Reading the state."), error(overflow), text("Compacted."), error(overflow), error(server)]
    assert events.read("\n".join(lines)).errors == (
        "ContextOverflowError: too long",
        "UnknownError: Unexpected server error. Check logs. (err_ccf1)",
    )


@pytest.mark.parametrize(
    ("value", "said"),
    [
        ({"name": "APIError"}, "APIError"),
        ({"data": {"message": "it broke"}}, "it broke"),
        ({}, "error"),
        ("not an object", "error"),  # one canopy cannot read still says the session failed
        ({"name": "x" * 300}, "x" * 200),
    ],
)
def test_an_error_says_what_it_gives(value: object, said: str) -> None:
    assert events.read(error(value)).errors == (said,)


def test_output_with_no_error_event_reports_none() -> None:
    assert events.read(f"error\n{RESULT}\n").errors == ()
    assert events.read("\n".join([text(RESULT), step()])).errors == ()


def tool(name: object, status: str = "completed", **state: object) -> str:
    return event("tool_use", {"type": "tool", "tool": name, "state": {"status": status, "input": {}, **state}})


def test_tool_calls_are_rolled_up_by_tool_with_what_they_returned() -> None:
    lines = [
        tool("bash", output="12345"),
        tool("github_pull_request_read", output="x" * 1000),
        tool("bash", "error", error="no such file"),
        tool("bash", output=None),  # returned nothing
        tool("github_pull_request_read", output="y" * 500),
        event("tool_use", {"tool": "bash", "state": {"status": "running"}}),  # not ended, so not printed by OpenCode
        event("tool_use", {"state": {"status": "completed", "output": "who called it?"}}),
        text(RESULT),
    ]
    assert events.read("\n".join(lines)).tools == (
        ToolUse("bash", calls=3, errors=1, result_chars=5 + len("no such file")),
        ToolUse("github_pull_request_read", calls=2, errors=0, result_chars=1500),
    )


def test_a_skill_call_is_counted_under_the_skill_it_loaded() -> None:
    def skill(status: str = "completed", **state: object) -> str:
        return event("tool_use", {"type": "tool", "tool": "skill", "state": {"status": status, **state}})

    lines = [
        # OpenCode 1.19.3 names the skill in the call's input, and the one it loaded in its metadata.
        skill(input={"name": "tracker-jira"}, metadata={"name": "tracker-jira", "dir": "/s"}, output="x" * 10),
        skill(input={"name": "tracker-jira"}, output="y" * 5),
        skill("error", input={"name": "no-such-skill"}, error="Skill not found"),
        # A name that is not a skill's by OpenCode's rule counts as the tool alone, as does a call that names none.
        skill(input={"name": "Bad Name\u001b[31m"}, output="z"),
        skill(input={"name": "a" * 65}, output="z"),
        skill(output="z"),
        text(RESULT),
    ]
    assert events.read("\n".join(lines)).tools == (
        ToolUse("skill:tracker-jira", calls=2, errors=0, result_chars=15),
        ToolUse("skill:no-such-skill", calls=1, errors=1, result_chars=len("Skill not found")),
        ToolUse("skill", calls=3, errors=0, result_chars=3),
    )


def test_plain_text_and_events_with_no_tool_call_roll_up_no_tool() -> None:
    assert events.read(f"chatter\n{RESULT}\n").tools == ()
    assert events.read("\n".join([text(RESULT), step()])).tools == ()


def test_a_tally_rolls_up_the_tools_as_read_does() -> None:
    lines = [tool("bash", output="12345"), tool("read", output="abc"), tool("bash", "error", error="no")]
    tally = events.Tally()
    for line in lines:
        found = events.parse_event(line)
        assert found is not None
        tally.add(found)
    assert tally.tools == events.read("\n".join(lines)).tools
