"""A traced tick: its steps and its decisions in it, and each run a trace of its own, linked to its `spawn`."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import pytest

from canopy.core.vocab import TickStatus
from canopy.infra import tracing
from tests.canopy.helpers import KEY, decides, listed, spans
from tests.canopy.scenario_helpers import dispatches, fails

if TYPE_CHECKING:
    from pathlib import Path

    from tests.canopy.scenario_helpers import Scenario

#: OpenTelemetry's status codes, as a span in the traces file carries them.
UNSET, ERROR = 0, 2
#: The model the operator chose for workers, which the fake runtime lists.
MODEL = "acme/fake-model-1"


@pytest.mark.usefixtures("git_pool")
def test_a_run_is_a_trace_of_its_own_linked_to_the_tick_that_started_it(scenario: Scenario) -> None:
    scenario.configures("private", telemetry={"traces": "file"})
    scenario.seen()
    ticked = scenario.tick(dispatches())
    [ran] = ticked.runs
    traced = last_of_each(scenario, waiting_for="run")
    tick = traced["tick"]
    # The tick's journal totals hold each of its steps'.
    queries = int(tick["attributes"].pop("canopy.journal_queries"))
    assert float(tick["attributes"].pop("canopy.journal_seconds")) > 0
    assert queries > int(traced["state"]["attributes"]["canopy.journal_queries"]) > 0
    assert tick["attributes"] == {
        "canopy.tick_id": str(ticked.tick.id),
        "canopy.dry_run": False,
        "canopy.status": "ok",
    }
    assert tick["status"] == {"code": UNSET}
    for step in ("gc", "reconcile", "tasks", "connectors", "derive", "state", "overseer", "spawn"):
        assert traced[step]["parentSpanId"] == tick["spanId"], step
        assert traced[step]["traceId"] == tick["traceId"], step
    # The worker's run, in its detached `canopy _run`, is a trace of its own, linked to the step that started it.
    run = traced["run"]
    assert run["traceId"] != tick["traceId"]
    assert "parentSpanId" not in run
    links = run["links"]
    assert isinstance(links, list)
    [link] = links
    assert (link["traceId"], link["spanId"]) == (tick["traceId"], traced["spawn"]["spanId"])
    assert int(run["attributes"].pop("canopy.journal_queries")) > 0
    assert run["attributes"].pop("canopy.journal_seconds")
    # What canopy chose for it, besides its id; it chose no model, so the runtime's default ran it.
    assert run["attributes"] == {
        "canopy.run_id": str(ran.row["id"]),
        "canopy.role": "worker",
        "canopy.kind": "implement",
        "canopy.attempt": "1",
        "canopy.sandboxed": False,
        "canopy.status": "done",
    }
    # A run that did its work is no failure.
    assert run["status"] == {"code": UNSET}


@pytest.mark.usefixtures("git_pool")
def test_a_run_that_fails_without_raising_is_a_failed_span_of_its_kind_and_attempt(
    scenario: Scenario,
    opencode_state: Path,
) -> None:
    listed(opencode_state, MODEL)
    scenario.configures("private", telemetry={"traces": "file"})
    scenario.configures(runtime={"models": {"worker": MODEL}})
    assert [scenario.run(worker=fails()).row["status"] for _ in range(2)] == ["failed", "failed"]
    run = last_of_each(scenario)["run"]
    assert run["status"] == {"code": ERROR, "message": "failed"}
    attributes = run["attributes"]
    assert (attributes["canopy.kind"], attributes["canopy.role"]) == ("implement", "worker")
    # The ticket's second implement, on the model the operator chose for its workers.
    assert (attributes["canopy.attempt"], attributes["canopy.model"]) == ("2", MODEL)
    assert attributes["canopy.status"] == "failed"


def test_a_dry_tick_s_trace_holds_a_moment_for_each_decision_it_recorded(scenario: Scenario) -> None:
    scenario.configures("private", telemetry={"traces": "file"})
    scenario.seen(KEY, "PROJ-2")
    # A dispatch, the same one again, which a guard refuses, and a wait.
    ticked = scenario.tick(dispatches(), dispatches(), decides("PROJ-2", rationale="a-secret-rationale"), dry_run=True)
    traced = spans(scenario.env.state_dir / tracing.TRACES_FILE_NAME)
    [tick] = [s for s in traced if s["name"] == "tick"]
    moments = {
        int(e["attributes"]["canopy.decision_id"]): (s["name"], e["attributes"])
        for s in traced
        if s["traceId"] == tick["traceId"]
        for e in s["events"]
        if e["name"] == "decision"
    }
    assert sorted(moments) == sorted(d.id for d in ticked.decisions)
    by_action = {d.action: (d, *moments[d.id]) for d in ticked.decisions}
    # Each of the overseer's is a moment in the tool call that recorded it, in the overseer's process.
    dispatched, span_name, attributes = by_action["dispatch:implement"]
    assert span_name == "tools/call dispatch"
    assert attributes == {
        "canopy.decision_id": str(dispatched.id),
        "canopy.kind": "dispatch",
        "canopy.outcome": "made",
        "canopy.decider": "overseer",
    }
    [(refused, span_name, attributes)] = [v for action, v in by_action.items() if action.startswith("refused:")]
    assert span_name == "tools/call dispatch"
    assert attributes == {
        "canopy.decision_id": str(refused.id),
        "canopy.kind": "dispatch",
        "canopy.outcome": "refused",
        "canopy.guard": refused.action.removeprefix("refused:"),
        "canopy.decider": "overseer",
        "canopy.run_kind": "implement",
    }
    assert by_action["wait"][1] == "tools/call decide"
    # Canopy's own words alone: never a ticket's key or the overseer's rationale.
    text = (scenario.env.state_dir / tracing.TRACES_FILE_NAME).read_text()
    assert "a-secret-rationale" not in text
    assert "PROJ-2" not in text


def test_a_tick_that_does_not_end_ok_is_a_failed_span(scenario: Scenario) -> None:
    scenario.configures("private", telemetry={"traces": "file"})
    scenario.seen()
    failed = scenario.tick(exit_code=3, code=1)
    assert failed.tick.status == TickStatus.OVERSEER_FAILED
    tick = last_of_each(scenario)["tick"]
    assert tick["status"] == {"code": ERROR, "message": "overseer_failed"}
    assert tick["attributes"]["canopy.status"] == "overseer_failed"


def test_a_workspace_that_does_not_trace_writes_no_traces(scenario: Scenario) -> None:
    scenario.seen(KEY)
    scenario.tick(dispatches())
    assert not (scenario.env.state_dir / tracing.TRACES_FILE_NAME).exists()


def last_of_each(
    scenario: Scenario,
    *,
    waiting_for: str | None = None,
    timeout: float = 30,
) -> dict[str, dict[str, Any]]:
    """The last span of each name the workspace traced, once a span named `waiting_for`, if any, is among them.

    A detached run closes its row before it ends its span and writes it, as its process exits.
    """
    path = scenario.env.state_dir / tracing.TRACES_FILE_NAME
    deadline = time.monotonic() + timeout
    while True:
        traced = {s["name"]: s for s in spans(path)}
        if waiting_for is None or waiting_for in traced:
            return traced
        assert time.monotonic() < deadline, f"no {waiting_for} span within {timeout}s"
        time.sleep(0.05)
