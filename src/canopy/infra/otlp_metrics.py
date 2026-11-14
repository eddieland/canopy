"""Metrics in OTLP's JSON encoding, and the exporters that append them to a file or post them to an OTLP/HTTP endpoint.

The encoding is OTLP/JSON's `ExportMetricsServiceRequest`, appended and posted as `otlp` appends and posts spans. Sums
and histograms go as deltas, what changed since the last export: canopy's processes are many and short, so a collector
adds up what each sends, with its `deltatocumulative` processor, rather than reading one process's running total.
Each export also carries what this process counted of its exports, by signal and outcome (`exports`): counts canopy
keeps itself, not the SDK, so those an export the endpoint did not take carried ride the next one instead of being lost
with it. Only `metrics` imports this module, and only once metrics are on.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, override

from opentelemetry.sdk.metrics import Counter, Histogram
from opentelemetry.sdk.metrics.export import (
    AggregationTemporality,
    Gauge,
    HistogramDataPoint,
    MetricExporter,
    MetricExportResult,
    MetricsData,
    NumberDataPoint,
    Sum,
)
from opentelemetry.sdk.metrics.export import Histogram as HistogramData

from canopy.infra import exports, otlp

if TYPE_CHECKING:
    from opentelemetry.sdk.metrics.export import Metric

#: How each kind of instrument is exported: counts and histograms as deltas, so a collector sums many processes'.
DELTAS = {Counter: AggregationTemporality.DELTA, Histogram: AggregationTemporality.DELTA}
#: The instrumentation scope of canopy's metrics: the meter `metrics` records with, and the counts of exports.
SCOPE = "canopy"


class MetricFileExporter(MetricExporter):
    """Appends each export of metrics to a file, as one line of OTLP JSON."""

    def __init__(self, path: Path, ledger: exports.Ledger) -> None:
        """Append to `path`, made readable by the operator alone if it is not there, and tell `ledger`."""
        super().__init__(preferred_temporality=dict(DELTAS))
        self.path = path
        self.ledger = ledger

    @override
    def export(self, metrics_data: MetricsData, timeout_millis: float = 10_000, **kwargs: Any) -> MetricExportResult:
        """Append `metrics_data` as one line, with what this process counted of its exports.

        Returns:
            Whether the whole line was written.
        """
        carried = _riding(metrics_data)
        written = otlp.append_line(self.path, encoded(metrics_data, carried))
        self.ledger.noted(took=written, why=otlp.UNWRITTEN)
        return _went(carried, took=written)

    @override
    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        """Nothing is held back: each export is written as it comes.

        Returns:
            True.
        """
        return True

    @override
    def shutdown(self, timeout_millis: float = 30_000, **kwargs: Any) -> None:
        """Nothing to close: the file is open only while a line is written."""


class MetricHttpExporter(MetricExporter):
    """Posts each export of metrics, as OTLP JSON, to an OTLP/HTTP endpoint's metrics URL."""

    def __init__(self, url: str, ledger: exports.Ledger) -> None:
        """Post to `url`, `<endpoint>/v1/metrics`, which config held to `http` or `https`, telling `ledger`."""
        super().__init__(preferred_temporality=dict(DELTAS))
        self.poster = otlp.Poster(url, ledger)

    @override
    def export(self, metrics_data: MetricsData, timeout_millis: float = 10_000, **kwargs: Any) -> MetricExportResult:
        """Post `metrics_data` once, with what this process counted of its exports: one not taken is dropped.

        Its metrics are dropped as a batch of spans is; the counts it carried ride the next.

        Returns:
            Whether the endpoint took it, with a 2xx.
        """
        carried = _riding(metrics_data)
        took = self.poster.post(encoded(metrics_data, carried))
        return _went(carried, took=took)

    @override
    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        """Nothing is held back: each export is posted as it comes.

        Returns:
            True.
        """
        return True

    @override
    def shutdown(self, timeout_millis: float = 30_000, **kwargs: Any) -> None:
        """Nothing to close: each post opens and closes its own connection."""


def encoded(metrics_data: MetricsData, carried: exports.Riding | None = None) -> dict[str, object]:
    """`metrics_data` as an OTLP/JSON `ExportMetricsServiceRequest`, with the counts `carried`, if any.

    The counts go under the first resource, in canopy's own scope, where the metrics `metrics` records are.

    Returns:
        The request, for `json.dumps`.
    """
    # Placed once: under the first resource's own scope, or a scope of its own when that resource has none.
    counts: list[dict[str, object]] = _carried(carried) if carried is not None else []
    resources: list[dict[str, object]] = []
    for rm in metrics_data.resource_metrics:
        scopes: list[dict[str, object]] = []
        for sm in rm.scope_metrics:
            encoded_metrics = [_metric(m) for m in sm.metrics]
            if sm.scope.name == SCOPE:
                encoded_metrics.extend(counts)
                counts = []
            scope = {"name": sm.scope.name, **({"version": sm.scope.version} if sm.scope.version else {})}
            scopes.append({"scope": scope, "metrics": encoded_metrics})
        if counts:
            scopes.append({"scope": {"name": SCOPE}, "metrics": counts})
            counts = []
        resources.append({"resource": {"attributes": otlp.attributes(rm.resource.attributes)}, "scopeMetrics": scopes})
    return {"resourceMetrics": resources}


def _riding(metrics_data: MetricsData) -> exports.Riding | None:
    """What this export carries of the counts of exports, counting itself sent: none when it holds no resource.

    Returns:
        The counts, or None, when they wait for an export that has a resource to put them under.
    """
    return exports.riding(sending=exports.Signal.METRICS) if metrics_data.resource_metrics else None


def _went(carried: exports.Riding | None, *, took: bool) -> MetricExportResult:
    """Take what an export carried off the counts, once it was taken.

    Returns:
        The export's result, for the SDK.
    """
    if not took:
        return MetricExportResult.FAILURE
    if carried is not None:
        exports.rode(carried)
    return MetricExportResult.SUCCESS


def _carried(carried: exports.Riding) -> list[dict[str, object]]:
    """The counts of exports, and of dropped spans if any, as OTLP sums of deltas over the time they were counted.

    Returns:
        The metrics.
    """
    times = {"startTimeUnixNano": str(carried.start_ns), "timeUnixNano": str(carried.end_ns)}
    out: list[dict[str, object]] = [
        _delta_sum(
            exports.EXPORTS,
            exports.EXPORTS_DESCRIPTION,
            [
                {**times, "attributes": otlp.attributes({"signal": signal, "outcome": outcome}), "asInt": str(n)}
                for (signal, outcome), n in sorted(carried.exports.items())
            ],
        ),
    ]
    if carried.spans_dropped:
        out.append(
            _delta_sum(
                exports.SPANS_DROPPED,
                exports.SPANS_DROPPED_DESCRIPTION,
                [{**times, "attributes": [], "asInt": str(carried.spans_dropped)}],
            ),
        )
    return out


def _delta_sum(name: str, description: str, points: list[dict[str, object]]) -> dict[str, object]:
    """A monotonic sum of deltas, in OTLP/JSON, of `points`.

    Returns:
        The metric.
    """
    return {
        "name": name,
        "description": description,
        "unit": "1",
        "sum": {
            "dataPoints": points,
            "aggregationTemporality": AggregationTemporality.DELTA.value,
            "isMonotonic": True,
        },
    }


def _metric(metric: Metric) -> dict[str, object]:
    """One metric: its name, unit, and data, a sum, a gauge, or a histogram, each point with its labels.

    Returns:
        The metric.

    Raises:
        TypeError: Its data is of a kind canopy records none of, such as an exponential histogram.
    """
    out: dict[str, object] = {"name": metric.name, "description": metric.description or "", "unit": metric.unit or ""}
    data = metric.data
    match data:
        case Sum():
            out["sum"] = {
                "dataPoints": [_number(p) for p in data.data_points if isinstance(p, NumberDataPoint)],
                "aggregationTemporality": data.aggregation_temporality.value,
                "isMonotonic": data.is_monotonic,
            }
        case Gauge():
            out["gauge"] = {"dataPoints": [_number(p) for p in data.data_points if isinstance(p, NumberDataPoint)]}
        case HistogramData():
            out["histogram"] = {
                "dataPoints": [_histogram(p) for p in data.data_points],
                "aggregationTemporality": data.aggregation_temporality.value,
            }
        case _:
            msg = f"canopy records no metric of {type(data).__name__}"
            raise TypeError(msg)
    return out


def _number(point: NumberDataPoint) -> dict[str, object]:
    """A sum's or a gauge's point: an int as a string, being 64-bit in OTLP, or a float as a double.

    Returns:
        The point.
    """
    value: Mapping[str, object] = (
        {"asDouble": point.value} if isinstance(point.value, float) else {"asInt": str(point.value)}
    )
    return {**_times(point), "attributes": otlp.attributes(point.attributes), **value}


def _histogram(point: HistogramDataPoint) -> dict[str, object]:
    """A histogram's point: its count, sum, buckets and their bounds, and its least and greatest value.

    Returns:
        The point.
    """
    return {
        **_times(point),
        "attributes": otlp.attributes(point.attributes),
        "count": str(point.count),
        "sum": point.sum,
        "bucketCounts": [str(c) for c in point.bucket_counts],
        "explicitBounds": list(point.explicit_bounds),
        "min": point.min,
        "max": point.max,
    }


def _times(point: NumberDataPoint | HistogramDataPoint) -> dict[str, str]:
    """When a point's interval started and ended, in nanoseconds, as strings.

    Returns:
        The times.
    """
    return {"startTimeUnixNano": str(point.start_time_unix_nano or 0), "timeUnixNano": str(point.time_unix_nano)}
