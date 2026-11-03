"""A running agent's output read a line at a time: what each line changes of what its row records (DESIGN §8)."""

import json
from pathlib import Path

from canopy.infra import tracing
from canopy.runtime.implementation import Version
from canopy.runtime.report import Called
from canopy.runtime.watch import Change, Watch

TOKENS = {"input": 100, "output": 20, "reasoning": 3, "cache": {"read": 400, "write": 50}}


def event(kind: str, part: object, session: object = "ses_abc123") -> str:
    return json.dumps({"type": kind, "timestamp": 1, "sessionID": session, "part": part})


def test_each_line_says_what_it_changed() -> None:
    watch = Watch(version=Version.ONE)
    assert watch.read("starting up\n") is None  # not an event
    assert watch.read(event("text", {"text": "hi"}, session="bad id!")) is None  # no session canopy prints yet
    started = watch.read(event("step_start", {}))
    assert started == Change("ses_abc123", started=True, usage=None, did=None)
    assert watch.read(event("text", {"text": "Working on it."})) is None  # the same session, nothing spent or done
    ran = watch.read(event("tool_use", {"tool": "bash", "state": {"status": "completed", "input": {"command": "ls"}}}))
    called = Called("bash", completed=True, input={"command": "ls"})
    assert ran == Change("ses_abc123", started=False, usage=None, did=("bash", "ls"), called=called)
    spent = watch.read(event("step_finish", {"cost": 0.25, "tokens": TOKENS}))
    assert spent is not None
    assert spent.usage is not None
    assert (spent.started, spent.usage.cost_usd, spent.did) == (False, 0.25, None)


def test_a_model_call_that_cannot_be_read_reports_nothing_spent_from_then_on() -> None:
    watch = Watch(version=Version.ONE)
    assert watch.read(event("step_finish", {"cost": -1, "tokens": TOKENS})) == Change(
        "ses_abc123",
        started=True,
        usage=None,
        did=None,
    )
    assert watch.read(event("step_finish", {"cost": 0.25, "tokens": TOKENS})) is None


def test_a_tool_call_is_given_as_the_agent_made_it_under_either_version() -> None:
    for version in Version:
        watch = Watch(version=version)
        state = {"status": "error", "input": {"summary": "s"}, "error": "refused"}
        change = watch.read(event("tool_use", {"tool": "canopy_run_status", "state": state}))
        assert change is not None
        assert change.called == Called("canopy_run_status", completed=False, input={"summary": "s"})


RECORDED = Path(__file__).parent / "opencode2" / "recorded" / "run.jsonl"


def test_each_model_call_and_tool_call_is_a_span_at_the_times_the_runtime_printed(tmp_path: Path) -> None:
    tracing.configure(tmp_path, "file")
    printed = [json.loads(line) for line in RECORDED.read_text().splitlines()]
    with tracing.span("run", run_id=7):
        watch = Watch(version=Version.TWO, model="anthropic/claude-sonnet")
        for line in RECORDED.read_text().splitlines(keepends=True):
            watch.read(line)
    tracing.configure(tmp_path, "off")
    written = (tmp_path / tracing.TRACES_FILE_NAME).read_text()
    spans = [
        span
        for line in written.splitlines()
        for resource in json.loads(line)["resourceSpans"]
        for scope in resource["scopeSpans"]
        for span in scope["spans"]
    ]
    [run] = [s for s in spans if s["name"] == "run"]
    calls = [s for s in spans if s["name"] == "chat anthropic/claude-sonnet"]
    tools = [s for s in spans if s["name"].startswith("execute_tool ")]
    steps = sum(1 for e in printed if e["type"] == "step_finish")
    assert (len(calls), len(tools)) == (steps, sum(1 for e in printed if e["type"] == "tool_use"))
    assert {s["parentSpanId"] for s in calls + tools} == {run["spanId"]}
    # A model call runs from its step_start to its step_finish, as the runtime timed them.
    starts = [e["timestamp"] for e in printed if e["type"] == "step_start"]
    assert [int(c["startTimeUnixNano"]) // 1_000_000 for c in calls] == starts[: len(calls)]
    first = {a["key"]: next(iter(a["value"].values())) for a in calls[0]["attributes"]}
    assert first["gen_ai.operation.name"] == "chat"
    assert first["gen_ai.request.model"] == "anthropic/claude-sonnet"
    assert int(str(first["gen_ai.usage.input_tokens"])) > 0
    # What the model was sent or wrote, and what a tool returned, never reaches a span.
    texts = [e["part"]["text"] for e in printed if e["type"] == "text"]
    outputs = [e["part"]["state"].get("output") for e in printed if e["type"] == "tool_use"]
    assert not [t for t in [*texts, *outputs] if t and len(t) > 8 and t in written]
