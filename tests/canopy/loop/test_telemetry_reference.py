"""The guide's Telemetry page names what canopy records, and the example dashboard and alerts query only that.

Its tables are the operator's reference for writing a query, so each is held to the code: every metric by name, kind,
and Prometheus name; the spans and events a traced, metered tick and its run record, by name and attribute; and every
`canopy_*` name the examples in `examples/otel/` query.
"""

from __future__ import annotations

import json
import re
import time
import typing
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from canopy.core import run_spans
from canopy.core.vocab import FAILED_RUN_STATUSES
from canopy.infra import exports, metrics, tracing
from canopy.loop.tick import Step
from tests.canopy.helpers import KEY, points, raises, spans
from tests.canopy.scenario_helpers import dispatches

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from tests.canopy.scenario_helpers import Scenario

ROOT: Final = Path(__file__).resolve().parents[3]
#: The guide's page, whose tables are held here.
GUIDE: Final = ROOT / "ui" / "src" / "guide" / "telemetry.md"
#: The example collector's dashboard and alerts.
DASHBOARD: Final = ROOT / "examples" / "otel" / "dashboard.json"
ALERTS: Final = ROOT / "examples" / "otel" / "alerts.yaml"
#: What every span may carry, the journal queries run under it, which the guide names in its prose.
TALLIES: Final = frozenset({"canopy.journal_queries", "canopy.journal_seconds"})
#: Each unit canopy records, as the collector's Prometheus exporter adds it to a name: `1` and an annotation in braces
#: add nothing, and a unit the exporter does not know, `USD`, is added as it is.
PROMETHEUS_UNITS: Final = {"1": "", "s": "seconds", "By": "bytes", "USD": "USD", "{token}": ""}
#: The series a histogram is served as in Prometheus, besides none under its own name.
HISTOGRAM_SERIES: Final = ("_bucket", "_sum", "_count")
#: How long a detached run's process may take to exit, writing what it recorded as it does.
DEADLINE_SECONDS: Final = 30


def test_the_guide_names_every_metric_as_the_kind_canopy_records_it() -> None:
    kinds = {
        **dict.fromkeys(typing.get_args(metrics.CounterName.__value__), "counter"),
        **dict.fromkeys(typing.get_args(metrics.HistogramName.__value__), "histogram"),
        **dict.fromkeys(typing.get_args(metrics.GaugeName.__value__), "gauge"),
        # Counted by `exports`, not OpenTelemetry, so they ride an export that is taken.
        exports.EXPORTS: "counter",
        exports.SPANS_DROPPED: "counter",
    }
    assert set(kinds) == set(metrics.INSTRUMENTS) | {exports.EXPORTS, exports.SPANS_DROPPED}
    assert {row.code("Metric")[0]: row.text("Kind") for row in table("Every metric")} == kinds


def test_the_guide_gives_each_metric_the_name_the_collector_serves_it_by() -> None:
    for row in table("Every metric"):
        [name], [unit], [served] = row.code("Metric"), row.code("Unit"), row.code("In Prometheus")
        assert served == prometheus_name(name, row.text("Kind"), unit), name


def test_the_dashboard_and_the_alerts_query_only_what_the_collector_serves() -> None:
    served = {row.code("In Prometheus")[0]: row.text("Kind") for row in table("Every metric")}
    series = set(served) | {
        f"{name}{suffix}" for name, kind in served.items() if kind == "histogram" for suffix in HISTOGRAM_SERIES
    }
    dashboard = json.loads(DASHBOARD.read_text())
    queried = {
        "dashboard": "\n".join(target["expr"] for panel in dashboard["panels"] for target in panel["targets"]),
        "alerts": ALERTS.read_text(),
    }
    for source, text in queried.items():
        names = set(re.findall(r"\bcanopy_\w+", text))
        assert names, source
        assert names <= series, f"{source}: {sorted(names - series)}"
        # A histogram is queried by its series, never by its own name, which Prometheus does not have.
        assert not names & {name for name, kind in served.items() if kind == "histogram"}, source


def test_the_failing_runs_alert_counts_each_status_a_run_fails_in() -> None:
    [statuses] = re.findall(r'canopy_runs_total\{status=~"([^"]+)"\}', ALERTS.read_text())
    assert set(statuses.split("|")) == {status.value for status in FAILED_RUN_STATUSES}


def test_the_guide_names_each_step_s_span_and_each_run_s() -> None:
    rows = table("Every span")
    names = {name for row in rows for name in row.code("Span")}
    assert {step.value for step in Step} <= names
    for name, key in run_spans.SPANS.values():
        [row] = [row for row in rows if name in row.code("Span")]
        assert f"canopy.{key}" in row.code("Attributes"), name
    assert all(f"`{tally}`" in GUIDE.read_text() for tally in TALLIES)


def test_a_tick_and_its_run_record_only_what_the_guide_names(
    scenario: Scenario,
    sink_script: Path,
    tmp_path: Path,
) -> None:
    """A tick that dispatches a worker, has a dispatch refused, and tells a sink that is down, and the worker's run."""
    out = tmp_path / "phone.txt"
    Path(f"{out}.exit").write_text("1")
    scenario.configures("private", telemetry={"traces": "file", "metrics": "file"})
    sink = {"cmd": f"{sink_script} {out} {out}.exit"}
    scenario.configures(capacity={"max_workers": 1}, notify={"sinks": {"phone": sink}})
    scenario.seen(KEY, "PROJ-2")
    scenario.tick(dispatches(), dispatches("PROJ-2"), raises("PROJ-2", "needs_human"))
    traces = scenario.env.state_dir / tracing.TRACES_FILE_NAME
    metered = scenario.env.state_dir / metrics.METRICS_FILE_NAME
    wait_for_the_run(traces, metered)
    # This process ran the tick: turning both off writes what it recorded.
    metrics.configure(Path(), "off")
    tracing.configure(Path(), "off")

    described = {row.code("Metric")[0]: row for row in table("Every metric")}
    recorded = list(metrics_in(metered))
    assert {name for name, *_ in recorded} >= {"canopy.ticks", "canopy.runs", "canopy.notifications"}
    for name, kind, unit, labels in recorded:
        assert name in described, name
        row = described[name]
        assert (kind, unit) == (row.text("Kind"), row.code("Unit")[0]), name
        assert set(labels) <= set(row.code("Labels")), name

    patterns = [(span_pattern(row.code("Span")), set(row.code("Attributes"))) for row in table("Every span")]
    events = {row.code("Event")[0]: set(row.code("Attributes")) for row in table("Every event")}
    traced = spans(traces)
    assert {"tick", "run", "tools/call dispatch"} <= {span["name"] for span in traced}
    for span in traced:
        attributes = set(span["attributes"]) - TALLIES
        # A name may match more than one pattern, a step's and a command's alike: one must allow what it holds.
        assert any(pattern.fullmatch(span["name"]) and attributes <= allowed for pattern, allowed in patterns), (
            f"{span['name']}: {sorted(attributes)}"
        )
        for event in span["events"]:
            assert event["name"] in events, event["name"]
            assert set(event["attributes"]) <= events[event["name"]], event["name"]


class Row:
    """A row of one of the guide's tables, by its columns' names."""

    def __init__(self, cells: Mapping[str, str]) -> None:
        """Hold `cells`, each column's text as written."""
        self.cells = cells

    def text(self, column: str) -> str:
        """The cell's text, as written.

        Returns:
            The text.
        """
        return self.cells[column]

    def code(self, column: str) -> list[str]:
        """Each code span in the cell, in order.

        Returns:
            The spans' text, without their backticks.
        """
        return re.findall(r"`([^`]+)`", self.cells[column])


def table(heading: str) -> list[Row]:
    """The rows of the table under the `##` heading `heading` on the guide's page.

    Returns:
        The rows, its header's and its delimiter's left out.
    """
    lines = GUIDE.read_text().splitlines()
    rows: list[Row] = []
    header: Sequence[str] = ()
    for line in lines[lines.index(f"## {heading}") + 1 :]:
        if line.startswith("## ") or (header and not line.startswith("|")):
            break
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not header:
            header = cells
        elif not set("".join(cells)) <= set("-: "):
            rows.append(Row(dict(zip(header, cells, strict=True))))
    assert rows, heading
    return rows


def prometheus_name(name: str, kind: str, unit: str) -> str:
    """`name`, as the collector's Prometheus exporter serves a metric of `kind` and `unit`.

    It translates as `UnderscoreEscapingWithSuffixes` does (`examples/otel/collector.yaml`): each run of characters a
    name cannot hold an underscore, the unit added unless the name holds it already, `_total` added to a counter, and
    `_ratio` to a gauge whose unit is `1`.

    Returns:
        The name.
    """
    assert unit in PROMETHEUS_UNITS, f"teach PROMETHEUS_UNITS how the exporter adds {unit!r} to a name"
    words = [word for word in re.split(r"[^a-zA-Z0-9:]+", name) if word]
    suffix = PROMETHEUS_UNITS[unit]
    if suffix and suffix not in words:
        words.append(suffix)
    if kind == "counter":
        words = [*(word for word in words if word != "total"), "total"]
    if kind == "gauge" and unit == "1":
        words = [*(word for word in words if word != "ratio"), "ratio"]
    return "_".join(words)


def span_pattern(names: Sequence[str]) -> re.Pattern[str]:
    """What the span names a row lists match, each `<placeholder>` in them standing for one word.

    Returns:
        The pattern.
    """
    return re.compile("|".join(re.sub(r"<\w+>", r"\\S+", re.escape(name)) for name in names))


def metrics_in(path: Path) -> Iterator[tuple[str, str, str, dict[str, object]]]:
    """Each point in the metrics file, as its metric's name, kind, and unit, and its labels.

    Yields:
        The name, the kind (`counter`, `gauge`, or `histogram`), the unit, and the labels of each point.
    """
    for line in path.read_text().splitlines():
        for resource in json.loads(line)["resourceMetrics"]:
            for scope in resource["scopeMetrics"]:
                for metric in scope["metrics"]:
                    kind, data = metric_kind(metric)
                    for point in data["dataPoints"]:
                        labels = {a["key"]: next(iter(a["value"].values())) for a in point["attributes"]}
                        yield metric["name"], kind, metric["unit"], labels


def metric_kind(metric: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]]:
    """A metric's kind, as the guide's table names it, and its data.

    Returns:
        The kind and the data.
    """
    if "sum" in metric:
        assert metric["sum"]["isMonotonic"], metric["name"]
        return "counter", metric["sum"]
    if "histogram" in metric:
        return "histogram", metric["histogram"]
    return "gauge", metric["gauge"]


def wait_for_the_run(traces: Path, metered: Path) -> None:
    """Wait until the worker's run, in a process of its own, has written its span and its metrics, as it exits."""
    deadline = time.monotonic() + DEADLINE_SECONDS
    while not (
        any(span["name"] == "run" for span in spans(traces))
        and any(name == "canopy.runs" and labels["role"] == "worker" for name, labels, _ in points(metered))
    ):
        assert time.monotonic() < deadline, "the worker's run wrote no span or no count"
        time.sleep(0.05)
