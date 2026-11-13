"""Metrics: off and free until configured, then appended to the metrics file as OTLP JSON, sums as deltas."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, get_args

import pytest

from canopy.core.run_metrics import Role
from canopy.core.vocab import RunStatus, TickStatus
from canopy.infra import metrics
from canopy.loop.tick import Step


@pytest.fixture
def metered(tmp_path: Path) -> Iterator[Path]:
    """Metrics on, to the metrics file in `tmp_path`, which it yields; the test turns them off to send them."""
    metrics.configure(tmp_path, "file")
    yield tmp_path / metrics.METRICS_FILE_NAME
    metrics.configure(tmp_path, "off")


def exported(path: Path) -> dict[str, dict[str, Any]]:
    """Each metric in the metrics file, by name: the last of a name."""
    found: dict[str, dict[str, Any]] = {}
    for line in path.read_text().splitlines():
        for resource in json.loads(line)["resourceMetrics"]:
            for scope in resource["scopeMetrics"]:
                for metric in scope["metrics"]:
                    found[metric["name"]] = metric
    return found


def labels(point: dict[str, Any]) -> dict[str, object]:
    """A point's labels, as a plain dict."""
    return {a["key"]: next(iter(a["value"].values())) for a in point["attributes"]}


def test_a_metric_while_metrics_are_off_records_nothing(tmp_path: Path) -> None:
    assert not metrics.enabled()
    metrics.count("canopy.runs", role=Role.WORKER, status=RunStatus.DONE)
    metrics.record("canopy.run.duration", 1.0, unit="s", role=Role.WORKER)
    metrics.gauge("canopy.runs.active", 1, role=Role.WORKER)
    assert not (tmp_path / metrics.METRICS_FILE_NAME).exists()


def test_counts_histograms_and_gauges_are_written_as_otlp_json(metered: Path, tmp_path: Path) -> None:
    metrics.count("canopy.runs", role=Role.WORKER, status=RunStatus.DONE)
    metrics.count("canopy.runs", role=Role.WORKER, status=RunStatus.DONE)
    metrics.count("canopy.cost", 0.25, unit="USD", model="anthropic/sonnet", role=Role.WORKER)
    metrics.record("canopy.run.duration", 12.5, unit="s", role=Role.WORKER, status=RunStatus.DONE)
    metrics.gauge("canopy.runs.active", 3, role=Role.WORKER)
    # Turning metrics off sends what is left, as a process's exit does.
    metrics.configure(tmp_path, "off")
    found = exported(metered)
    runs = found["canopy.runs"]["sum"]
    # A delta, a monotonic count, added up within the export.
    assert (runs["aggregationTemporality"], runs["isMonotonic"]) == (1, True)
    [point] = runs["dataPoints"]
    assert (labels(point), point["asInt"]) == ({"role": "worker", "status": "done"}, "2")
    [cost] = found["canopy.cost"]["sum"]["dataPoints"]
    assert (labels(cost), cost["asDouble"], found["canopy.cost"]["unit"]) == (
        {"role": "worker", "model": "anthropic/sonnet"},
        0.25,
        "USD",
    )
    [duration] = found["canopy.run.duration"]["histogram"]["dataPoints"]
    assert (duration["count"], duration["sum"], found["canopy.run.duration"]["unit"]) == ("1", 12.5, "s")
    [active] = found["canopy.runs.active"]["gauge"]["dataPoints"]
    assert (labels(active), active["asInt"]) == ({"role": "worker"}, "3")


def test_every_metric_name_is_described_and_of_one_kind() -> None:
    """Each name is described, and is a counter's, a histogram's, or a gauge's alone; only a histogram has bounds."""
    counters, histograms, gauges = (
        set(get_args(kind.__value__)) for kind in (metrics.CounterName, metrics.HistogramName, metrics.GaugeName)
    )
    assert counters.isdisjoint(histograms | gauges)
    assert histograms.isdisjoint(gauges)
    assert set(metrics.INSTRUMENTS) == counters | histograms | gauges
    assert all(instrument.description for instrument in metrics.INSTRUMENTS.values())
    assert {name for name, instrument in metrics.INSTRUMENTS.items() if instrument.bounds} == histograms


def test_each_histogram_is_exported_with_its_description_and_bounds_in_seconds(metered: Path, tmp_path: Path) -> None:
    histograms = {name: i for name, i in metrics.INSTRUMENTS.items() if i.bounds}
    assert set(histograms) == {"canopy.tick.duration", "canopy.tick.step.duration", "canopy.run.duration"}
    # A tick of a fraction of a second, a step of some milliseconds, and a run of some hours: each past what the SDK's
    # default bounds tell apart.
    metrics.record("canopy.tick.duration", 0.3, unit="s", status=TickStatus.OK)
    metrics.record("canopy.tick.step.duration", 0.03, unit="s", step=Step.STATE)
    metrics.record("canopy.run.duration", 20_000, unit="s", role=Role.WORKER, status=RunStatus.DONE)
    metrics.configure(tmp_path, "off")
    found = exported(metered)
    for name, instrument in histograms.items():
        [point] = found[name]["histogram"]["dataPoints"]
        assert found[name]["description"] == instrument.description
        assert point["explicitBounds"] == list(instrument.bounds)
        # Neither lands in the first bucket nor past the last.
        [bucket] = [i for i, n in enumerate(point["bucketCounts"]) if n != "0"]
        assert 0 < bucket < len(instrument.bounds)


def test_counters_and_gauges_are_exported_with_their_descriptions(metered: Path, tmp_path: Path) -> None:
    metrics.count("canopy.ticks", status=TickStatus.OK, dry_run=False)
    metrics.gauge("canopy.runs.active", 1, role=Role.WORKER)
    metrics.configure(tmp_path, "off")
    found = exported(metered)
    for name in ("canopy.ticks", "canopy.runs.active"):
        assert found[name]["description"] == metrics.INSTRUMENTS[name].description


def test_otlp_metrics_without_an_endpoint_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"needs telemetry\.endpoint"):
        metrics.configure(tmp_path, "otlp")
