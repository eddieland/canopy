"""Metrics in OTLP's JSON encoding, and the exporters that append them to a file or post them to an OTLP/HTTP endpoint.

The encoding is OTLP/JSON's `ExportMetricsServiceRequest`, appended and posted as `otlp` appends and posts spans. Sums
and histograms go as deltas, what changed since the last export: canopy's processes are many and short, so a collector
adds up what each sends, with its `deltatocumulative` processor, rather than reading one process's running total.
Only `metrics` imports this module, and only once metrics are on.
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

from canopy.infra import otlp

if TYPE_CHECKING:
    from opentelemetry.sdk.metrics.export import Metric

#: How each kind of instrument is exported: counts and histograms as deltas, so a collector sums many processes'.
DELTAS = {Counter: AggregationTemporality.DELTA, Histogram: AggregationTemporality.DELTA}


class MetricFileExporter(MetricExporter):
    """Appends each export of metrics to a file, as one line of OTLP JSON."""

    def __init__(self, path: Path) -> None:
        """Append to `path`, made readable by the operator alone if it is not there."""
        super().__init__(preferred_temporality=dict(DELTAS))
        self.path = path

    @override
    def export(self, metrics_data: MetricsData, timeout_millis: float = 10_000, **kwargs: Any) -> MetricExportResult:
        """Append `metrics_data` as one line.

        Returns:
            Whether the whole line was written.
        """
        if not otlp.append_line(self.path, encoded(metrics_data)):
            return MetricExportResult.FAILURE
        return MetricExportResult.SUCCESS

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

    def __init__(self, url: str) -> None:
        """Post to `url`, `<endpoint>/v1/metrics`, which config held to `http` or `https`."""
        super().__init__(preferred_temporality=dict(DELTAS))
        self.poster = otlp.Poster(url, "metrics")

    @override
    def export(self, metrics_data: MetricsData, timeout_millis: float = 10_000, **kwargs: Any) -> MetricExportResult:
        """Post `metrics_data` once: an export the endpoint did not take is dropped, as a batch of spans is.

        Returns:
            Whether the endpoint took it, with a 2xx.
        """
        if not self.poster.post(encoded(metrics_data)):
            return MetricExportResult.FAILURE
        return MetricExportResult.SUCCESS

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


def encoded(metrics_data: MetricsData) -> dict[str, object]:
    """`metrics_data` as an OTLP/JSON `ExportMetricsServiceRequest`.

    Returns:
        The request, for `json.dumps`.
    """
    return {
        "resourceMetrics": [
            {
                "resource": {"attributes": otlp.attributes(rm.resource.attributes)},
                "scopeMetrics": [
                    {
                        "scope": {"name": sm.scope.name, **({"version": sm.scope.version} if sm.scope.version else {})},
                        "metrics": [_metric(m) for m in sm.metrics],
                    }
                    for sm in rm.scope_metrics
                ],
            }
            for rm in metrics_data.resource_metrics
        ],
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
