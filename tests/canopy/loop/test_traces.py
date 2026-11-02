"""A traced tick: its steps under it, and the runs it starts under its `spawn`, each in a process of its own."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from canopy.infra import tracing
from tests.canopy.helpers import KEY
from tests.canopy.scenario_helpers import dispatches

if TYPE_CHECKING:
    from pathlib import Path

    from tests.canopy.scenario_helpers import Scenario


def spans(path: Path) -> dict[str, dict[str, object]]:
    """Each span in the traces file, by name: the last of a name, with its attributes as a plain dict."""
    found: dict[str, dict[str, object]] = {}
    for line in path.read_text().splitlines():
        for resource in json.loads(line)["resourceSpans"]:
            for scope in resource["scopeSpans"]:
                for span in scope["spans"]:
                    values = {a["key"]: next(iter(a["value"].values())) for a in span["attributes"]}
                    found[span["name"]] = {**span, "attributes": values}
    return found


def test_a_tick_and_the_run_it_starts_are_one_trace(scenario: Scenario) -> None:
    scenario.configures("private", telemetry={"traces": "file"})
    scenario.seen()
    ticked = scenario.tick(dispatches())
    [ran] = ticked.runs
    traced = spans(scenario.env.state_dir / tracing.TRACES_FILE_NAME)
    tick = traced["tick"]
    assert tick["attributes"] == {
        "canopy.tick_id": str(ticked.tick.id),
        "canopy.dry_run": False,
        "canopy.status": "ok",
    }
    for step in ("gc", "reconcile", "tasks", "connectors", "derive", "state", "overseer", "spawn"):
        assert traced[step]["parentSpanId"] == tick["spanId"], step
        assert traced[step]["traceId"] == tick["traceId"], step
    # The worker's run, in its detached `canopy _run`, is under the step that started it.
    run = traced["run"]
    assert (run["traceId"], run["parentSpanId"]) == (tick["traceId"], traced["spawn"]["spanId"])
    assert run["attributes"] == {"canopy.run_id": str(ran.row["id"]), "canopy.status": ran.row["status"]}


def test_a_workspace_that_does_not_trace_writes_no_traces(scenario: Scenario) -> None:
    scenario.seen(KEY)
    scenario.tick(dispatches())
    assert not (scenario.env.state_dir / tracing.TRACES_FILE_NAME).exists()
