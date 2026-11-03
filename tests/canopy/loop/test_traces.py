"""A traced tick: its steps under it, and each run it starts a trace of its own, linked to its `spawn`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.infra import tracing
from tests.canopy.helpers import KEY, spans
from tests.canopy.scenario_helpers import dispatches

if TYPE_CHECKING:
    from tests.canopy.scenario_helpers import Scenario


def test_a_run_is_a_trace_of_its_own_linked_to_the_tick_that_started_it(scenario: Scenario) -> None:
    scenario.configures("private", telemetry={"traces": "file"})
    scenario.seen()
    ticked = scenario.tick(dispatches())
    [ran] = ticked.runs
    # The last span of each name.
    traced = {s["name"]: s for s in spans(scenario.env.state_dir / tracing.TRACES_FILE_NAME)}
    tick = traced["tick"]
    assert tick["attributes"] == {
        "canopy.tick_id": str(ticked.tick.id),
        "canopy.dry_run": False,
        "canopy.status": "ok",
    }
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
    assert run["attributes"] == {"canopy.run_id": str(ran.row["id"]), "canopy.status": ran.row["status"]}


def test_a_workspace_that_does_not_trace_writes_no_traces(scenario: Scenario) -> None:
    scenario.seen(KEY)
    scenario.tick(dispatches())
    assert not (scenario.env.state_dir / tracing.TRACES_FILE_NAME).exists()
