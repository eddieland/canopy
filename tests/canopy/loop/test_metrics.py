"""A metered tick: its own count and time, its overseer's run, and each run it starts, counted where it is closed."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from canopy.infra import metrics
from tests.canopy.scenario_helpers import dispatches

if TYPE_CHECKING:
    from tests.canopy.scenario_helpers import Scenario

#: How long a detached run's process may take to exit, sending its metrics as it does.
DEADLINE_SECONDS = 30


def points(path: Path) -> list[tuple[str, dict[str, object], dict[str, Any]]]:
    """Each point in the metrics file: its metric's name, its labels, and the point."""
    found: list[tuple[str, dict[str, object], dict[str, Any]]] = []
    if not path.exists():
        return found
    for line in path.read_text().splitlines():
        for resource in json.loads(line)["resourceMetrics"]:
            for scope in resource["scopeMetrics"]:
                for metric in scope["metrics"]:
                    data = metric.get("sum") or metric.get("gauge") or metric.get("histogram") or {}
                    for point in data["dataPoints"]:
                        labels = {a["key"]: next(iter(a["value"].values())) for a in point["attributes"]}
                        found.append((metric["name"], labels, point))
    return found


def worker_run_counted(path: Path) -> list[dict[str, object]]:
    """The labels of each `canopy.runs` point a worker's run sent, once its process has exited, within the deadline."""
    deadline = time.monotonic() + DEADLINE_SECONDS
    while True:
        counted = [labels for name, labels, _ in points(path) if name == "canopy.runs" and labels["role"] == "worker"]
        if counted or time.monotonic() > deadline:
            return counted
        time.sleep(0.1)


def test_a_tick_and_the_run_it_starts_are_counted(scenario: Scenario) -> None:
    scenario.configures("private", telemetry={"metrics": "file"})
    scenario.seen()
    ticked = scenario.tick(dispatches())
    [ran] = ticked.runs
    path = scenario.env.state_dir / metrics.METRICS_FILE_NAME
    # The run's own process sent its count as it exited.
    assert worker_run_counted(path) == [{"role": "worker", "status": ran.row["status"], "kind": ran.row["kind"]}]
    # This process ran the tick: turning metrics off sends what it recorded.
    metrics.configure(Path(), "off")
    found = points(path)
    assert ("canopy.ticks", {"status": "ok", "dry_run": False}) in [(n, labels) for n, labels, _ in found]
    assert any(n == "canopy.tick.duration" for n, _, _ in found)
    assert any(n == "canopy.runs" and labels["role"] == "overseer" for n, labels, _ in found)
    active = {str(labels["role"]) for n, labels, _ in found if n == "canopy.runs.active"}
    assert active == {"worker", "task", "review", "chore"}


def test_a_workspace_that_does_not_meter_writes_no_metrics(scenario: Scenario) -> None:
    scenario.seen()
    scenario.tick(dispatches())
    assert not (scenario.env.state_dir / metrics.METRICS_FILE_NAME).exists()
