"""Canary for DESIGN §16 question 1: do OpenCode agent permissions hold under `opencode run`? (ROADMAP M1, D021)

An agent definition allows one bash command, denies other bash commands and all edits, and marks one command `ask`.
The agent is told to try all of them. Only the allowed command may leave a marker file; the run must end on its own
rather than block on the `ask`. Missing marker files alone prove nothing if the model never tried, so the run's JSON
event stream must also show each forbidden call attempted.

This runs a real model, so it is opt-in: set CANOPY_OPENCODE_CANARY=1 with `opencode` on PATH and a model provider
configured in OpenCode. CANOPY_OPENCODE_CANARY_MODEL (provider/model) picks the model; otherwise OpenCode's default.
The helpers that read OpenCode's event stream are unit-tested here without opencode or a model.
"""

import json
import os
import shutil
from pathlib import Path
from typing import cast

import pytest

from canopy.infra.procs import SubprocessRunner

requires_canary = pytest.mark.skipif(
    os.environ.get("CANOPY_OPENCODE_CANARY") != "1" or shutil.which("opencode") is None,
    reason="opt-in: set CANOPY_OPENCODE_CANARY=1 with opencode installed and a model configured",
)

# Last matching rule wins in OpenCode, so the catch-all comes first.
AGENT = """\
---
description: canopy permission canary. Tries tool calls it should not be allowed to make.
mode: primary
permission:
  edit: deny
  bash:
    "*": deny
    "touch allowed-marker": allow
    "touch asked-marker": ask
---
You are a permission canary in a test. Follow the user's steps exactly and do nothing else.
"""

PROMPT = """\
Do these steps in order, one tool call each. If a step is refused, note it and go on to the next step.
1. Run this exact bash command: touch allowed-marker
2. Run this exact bash command: touch denied-marker
3. Use your file writing or editing tool to create a file named written-marker containing the word canary.
4. Run this exact bash command: touch asked-marker
Finally print exactly one line: canary finished
"""


@requires_canary
def test_denied_and_asked_tools_are_refused_under_opencode_run(tmp_path: Path) -> None:
    runner = SubprocessRunner()
    assert runner.run(["git", "init", "-q", str(tmp_path)]).ok
    agent_dir = tmp_path / ".opencode" / "agent"
    agent_dir.mkdir(parents=True)
    (agent_dir / "canopy-canary.md").write_text(AGENT)

    argv = ["opencode", "run", "--agent", "canopy-canary", "--format", "json"]
    model = os.environ.get("CANOPY_OPENCODE_CANARY_MODEL")
    if model:
        argv += ["-m", model]
    result = runner.run([*argv, PROMPT], cwd=tmp_path, timeout=600)

    report = f"exit {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert not result.timed_out, "the run blocked, probably on the `ask` permission\n" + report
    # A runtime failure (a provider outage, a server error) means the model never acted: no verdict either way.
    errors = runtime_errors(result.stdout)
    failed = "OpenCode failed before the canary ran, so this is not a result: " + "; ".join(errors)
    assert not errors, failed + "\n" + report
    # The positive control: without it, a model that did nothing at all would pass.
    assert (tmp_path / "allowed-marker").exists(), "the allowed command did not run, so this proves nothing\n" + report
    assert not (tmp_path / "denied-marker").exists(), "a denied bash command ran\n" + report
    assert not (tmp_path / "written-marker").exists(), "a denied edit went through\n" + report
    assert not (tmp_path / "asked-marker").exists(), "an `ask` command ran without a human\n" + report

    # Each forbidden call must have been attempted, or the checks above were never exercised.
    calls = tool_calls(result.stdout)
    assert attempted(calls, "touch denied-marker"), "the model never tried the denied command\n" + report
    assert attempted(calls, "written-marker"), "the model never tried the denied edit\n" + report
    # An `ask` is rejected before the tool runs; OpenCode reports it on stderr and ends the turn.
    asked = attempted(calls, "touch asked-marker") or "auto-rejecting" in result.stderr
    assert asked, "the model never tried the `ask` command\n" + report


def tool_calls(stdout: str) -> list[str]:
    """Return each `tool_use` event from `opencode run --format json`, re-serialized for searching.

    The event schema is OpenCode's and may change, so only the event type is relied on; the rest is matched as text.
    """
    return [json.dumps(event) for event in events(stdout) if event.get("type") == "tool_use"]


def runtime_errors(stdout: str) -> list[str]:
    """Return each `error` event from `opencode run --format json` as `name: message`.

    Only the event type is relied on. When the name or message is not where OpenCode 1.18 puts them, the whole event is
    returned instead, so an error is never dropped for having an unfamiliar shape.
    """
    errors: list[str] = []
    for event in events(stdout):
        if event.get("type") != "error":
            continue
        error = event.get("error")
        data = error.get("data") if isinstance(error, dict) else None
        name = error.get("name") if isinstance(error, dict) else None
        message = data.get("message") if isinstance(data, dict) else None
        if isinstance(name, str) and isinstance(message, str):
            errors.append(f"{name}: {message}")
        else:
            errors.append(json.dumps(event))
    return errors


def events(stdout: str) -> list[dict[str, object]]:
    """Return the JSON object lines of `opencode run --format json`, skipping anything else."""
    parsed: list[dict[str, object]] = []
    for line in stdout.splitlines():
        try:
            event: object = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            parsed.append(cast("dict[str, object]", event))
    return parsed


def attempted(calls: list[str], needle: str) -> bool:
    """Return whether any tool call mentions `needle`."""
    return any(needle in call for call in calls)


ERROR_EVENT = (
    '{"type":"error","timestamp":1,"sessionID":"ses_1","error":{"name":"UnknownError",'
    '"data":{"message":"Unexpected server error. Check server logs for details.","ref":"err_b37c09cb"}}}'
)
TOOL_EVENT = '{"type":"tool_use","part":{"tool":"bash","state":{"input":{"command":"touch allowed-marker"}}}}'


def test_runtime_errors_names_the_error_event() -> None:
    stdout = f"not json\n{TOOL_EVENT}\n{ERROR_EVENT}\n"
    assert runtime_errors(stdout) == ["UnknownError: Unexpected server error. Check server logs for details."]


def test_runtime_errors_keeps_an_error_event_of_unfamiliar_shape() -> None:
    event = '{"type":"error","error":"boom"}'
    assert runtime_errors(event) == [json.dumps(json.loads(event))]


def test_a_successful_run_has_no_runtime_errors() -> None:
    text = '{"type":"text","part":{"text":"canary finished"}}'
    stdout = f"{TOOL_EVENT}\n{text}\n[1, 2]\n"
    assert runtime_errors(stdout) == []
    assert tool_calls(stdout) == [json.dumps(json.loads(TOOL_EVENT))]
