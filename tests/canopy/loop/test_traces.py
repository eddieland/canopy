"""A traced tick: its steps under it, and each run it starts a trace of its own, linked to its `spawn`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from canopy.core.vocab import TickStatus
from canopy.infra import tracing
from tests.canopy.helpers import KEY, listed, spans
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
    traced = last_of_each(scenario)
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


def last_of_each(scenario: Scenario) -> dict[str, dict[str, Any]]:
    """The last span of each name the workspace traced."""
    return {s["name"]: s for s in spans(scenario.env.state_dir / tracing.TRACES_FILE_NAME)}
