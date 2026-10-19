"""A running agent's output read a line at a time: what each line changes of what its row records (DESIGN §8)."""

import json

from canopy.runtime.watch import Change, Watch

TOKENS = {"input": 100, "output": 20, "reasoning": 3, "cache": {"read": 400, "write": 50}}


def event(kind: str, part: object, session: object = "ses_abc123") -> str:
    return json.dumps({"type": kind, "timestamp": 1, "sessionID": session, "part": part})


def test_each_line_says_what_it_changed() -> None:
    watch = Watch()
    assert watch.read("starting up\n") is None  # not an event
    assert watch.read(event("text", {"text": "hi"}, session="bad id!")) is None  # no session canopy prints yet
    started = watch.read(event("step_start", {}))
    assert started == Change("ses_abc123", started=True, usage=None, did=None)
    assert watch.read(event("text", {"text": "Working on it."})) is None  # the same session, nothing spent or done
    ran = watch.read(event("tool_use", {"tool": "bash", "state": {"status": "completed", "input": {"command": "ls"}}}))
    assert ran == Change("ses_abc123", started=False, usage=None, did=("bash", "ls"))
    spent = watch.read(event("step_finish", {"cost": 0.25, "tokens": TOKENS}))
    assert spent is not None
    assert spent.usage is not None
    assert (spent.started, spent.usage.cost_usd, spent.did) == (False, 0.25, None)


def test_a_model_call_that_cannot_be_read_reports_nothing_spent_from_then_on() -> None:
    watch = Watch()
    assert watch.read(event("step_finish", {"cost": -1, "tokens": TOKENS})) == Change(
        "ses_abc123", started=True, usage=None, did=None
    )
    assert watch.read(event("step_finish", {"cost": 0.25, "tokens": TOKENS})) is None
