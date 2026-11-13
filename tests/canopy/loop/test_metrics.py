"""A metered tick: its own count and time, its overseer's run, and each run it starts, counted where it is closed."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

from canopy.core import db, overseer_runs, run_metrics
from canopy.core.run_metrics import Role
from canopy.core.vocab import Phase, TickStatus
from canopy.infra import metrics
from tests.canopy.helpers import KEY, in_tick, raises, waits
from tests.canopy.scenario_helpers import dispatches

if TYPE_CHECKING:
    from tests.canopy.scenario_helpers import Scenario

#: How long a detached run's process may take to exit, sending its metrics as it does.
DEADLINE_SECONDS = 30
#: The gauges of what the loop holds, each set as a tick closes or publishes its attention list.
LOOP_GAUGES = {
    "canopy.tick.last",
    "canopy.tickets",
    "canopy.capacity.used",
    "canopy.capacity.limit",
    "canopy.attention.open",
    "canopy.disk.free",
}


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


def test_a_tick_sets_what_the_loop_holds_as_it_closes(scenario: Scenario) -> None:
    scenario.configures("private", telemetry={"metrics": "file"}, capacity={"max_workers": 3, "max_chores": 2})
    scenario.seen()
    db.change_ticket(scenario.conn, KEY, "phase", Phase.READY)
    began = time.time()
    scenario.tick(dispatches(), raises("PROJ-9", "needs_human"))
    metrics.configure(Path(), "off")
    found = points(scenario.env.state_dir / metrics.METRICS_FILE_NAME)
    gauges: dict[str, list[tuple[dict[str, object], float]]] = {}
    for name, labels, point in found:
        if name in LOOP_GAUGES:
            value = float(point["asDouble"]) if "asDouble" in point else float(point["asInt"])
            gauges.setdefault(name, []).append((labels, value))
    assert set(gauges) == LOOP_GAUGES
    [(last, at)] = gauges["canopy.tick.last"]
    assert last == {"status": TickStatus.OK.value}
    assert began - 1 <= at <= time.time() + 1
    # Each label a word of its vocabulary, and every phase set, an empty one to 0.
    tickets = {str(labels["phase"]): value for labels, value in gauges["canopy.tickets"]}
    assert tickets == {phase.value: 1 if phase is Phase.READY else 0 for phase in Phase}
    used = {str(labels["role"]): value for labels, value in gauges["canopy.capacity.used"]}
    limit = {str(labels["role"]): value for labels, value in gauges["canopy.capacity.limit"]}
    roles = {Role.WORKER.value, Role.REVIEW.value, Role.TASK.value, Role.CHORE.value}
    assert set(used) == set(limit) == roles
    # As config sets them, `max_reviews` and `max_tasks` by default.
    assert limit == {Role.WORKER.value: 3, Role.REVIEW.value: 1, Role.TASK.value: 1, Role.CHORE.value: 2}
    # The run the tick started was at work as it closed.
    assert used[Role.WORKER.value] == 1
    # The one item the overseer raised, as the tick published it.
    [(open_labels, open_items)] = gauges["canopy.attention.open"]
    assert (open_labels, open_items) == ({}, 1)
    # The free space where the state directory is, give or take what the disk gained or lost since.
    [(disk_labels, free)] = gauges["canopy.disk.free"]
    assert disk_labels == {}
    assert abs(free - shutil.disk_usage(scenario.env.state_dir).free) < 2**30


def test_a_ticket_done_or_stopped_is_not_counted_in_its_phase(scenario: Scenario) -> None:
    scenario.configures("private", telemetry={"metrics": "file"})
    scenario.seen(KEY, "PROJ-2", "PROJ-3")
    scenario.operator("start", "PROJ-2")
    scenario.operator("stop", "PROJ-2")
    for key in (KEY, "PROJ-2", "PROJ-3"):
        db.change_ticket(scenario.conn, key, "phase", Phase.BLOCKED)
    db.change_ticket(scenario.conn, "PROJ-3", "done", 1)
    scenario.tick(*waits(KEY))
    metrics.configure(Path(), "off")
    found = points(scenario.env.state_dir / metrics.METRICS_FILE_NAME)
    counted = sum(int(point["asInt"]) for name, _, point in found if name == "canopy.tickets")
    assert counted == 1


def test_a_workers_capacity_is_filled_by_every_run_that_holds_a_slot() -> None:
    assert set(run_metrics.FILLED_BY[Role.WORKER]) == set(db.SLOT_TABLES)


def test_a_workspace_that_does_not_meter_writes_no_metrics(scenario: Scenario) -> None:
    scenario.seen()
    scenario.tick(dispatches())
    assert not (scenario.env.state_dir / metrics.METRICS_FILE_NAME).exists()


def test_a_tick_a_dead_process_left_is_counted_as_the_next_closes_it(scenario: Scenario) -> None:
    scenario.configures("private", telemetry={"metrics": "file"})
    with in_tick(scenario.conn) as dead:
        overseer_runs.start(scenario.conn, dead)
    scenario.tick(*waits(KEY))
    metrics.configure(Path(), "off")
    found = [(n, labels) for n, labels, _ in points(scenario.env.state_dir / metrics.METRICS_FILE_NAME)]
    assert ("canopy.ticks", {"status": "abandoned", "dry_run": False}) in found
    assert ("canopy.runs", {"role": "overseer", "status": "abandoned"}) in found
    # When the next tick closed it, beside when that tick closed itself.
    assert ("canopy.tick.last", {"status": "abandoned"}) in found
    assert ("canopy.tick.last", {"status": "ok"}) in found


def test_a_metric_that_fails_is_logged_and_never_fails_the_tick(scenario: Scenario) -> None:
    scenario.configures("private", telemetry={"metrics": "file"})
    scenario.seen()
    with mock.patch.object(metrics, "gauge", autospec=True, side_effect=OSError("disk full")):
        ticked = scenario.tick(dispatches())
    metrics.configure(Path(), "off")
    assert ticked.tick.status == TickStatus.OK
    assert "a metric was not recorded" in (scenario.env.state_dir / "canopy.log").read_text()
