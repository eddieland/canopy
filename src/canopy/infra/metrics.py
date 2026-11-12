"""Metrics of what canopy does, through OpenTelemetry, off until the operator turns them on (D132).

Every metric canopy records goes through this module, as every span goes through `tracing`:

    metrics.count("canopy.runs", role=Role.WORKER, status=RunStatus.DONE)
    metrics.record("canopy.run.duration", 312.5, unit="s", role=Role.WORKER, status=RunStatus.DONE)
    metrics.gauge("canopy.runs.active", 2, role=Role.WORKER)

A label is one of canopy's closed vocabularies, a `StrEnum` member or a flag, so a label never holds a ticket key, a
path, or text, and a metric's series stay as few as the vocabularies' words (D132). The one other label is `model`,
which only the operator's config names.

Counts and histograms are exported as deltas, what changed since the last export: canopy's processes are many and
short, a detached run's among them, so a collector adds up what each sends. A process sends what is left as it exits.
Until `configure` turns metrics on, a call does nothing and OpenTelemetry is never imported.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping

    from opentelemetry.metrics import Counter, Histogram, Meter, _Gauge
    from opentelemetry.sdk.metrics import MeterProvider

#: Where a process's metrics go: nowhere, appended to `METRICS_FILE_NAME` in the state directory, or sent to the
#: OTLP/HTTP endpoint the operator names.
type Metrics = Literal["off", "file", "otlp"]
#: A metric's label: a word of one of canopy's closed vocabularies, or a flag (D132).
type Label = StrEnum | bool

#: The file metrics are appended to, as OTLP JSON, a line per export, in the state directory.
METRICS_FILE_NAME = "metrics.jsonl"
#: Where an OTLP/HTTP endpoint takes metrics, under its base URL.
METRICS_PATH = "/v1/metrics"
#: How often a process sends what it has recorded; it sends what is left as it exits, whatever the time.
EXPORT_EVERY_MILLIS = 30_000


def count(name: str, value: float = 1, *, unit: str = "1", model: str | None = None, **labels: Label) -> None:
    """Add `value` to the counter `name`, under `labels`, and the model that did the work, if any."""
    meter = _metrics.meter
    if meter is not None:
        _metrics.counter(meter, name, unit).add(value, _labelled(labels, model))


def record(name: str, value: float, *, unit: str, model: str | None = None, **labels: Label) -> None:
    """Record `value`, in `unit`, in the histogram `name`, under `labels`, and the model that did the work, if any."""
    meter = _metrics.meter
    if meter is not None:
        _metrics.histogram(meter, name, unit).record(value, _labelled(labels, model))


def gauge(name: str, value: float, *, unit: str = "1", **labels: Label) -> None:
    """Set the gauge `name`, under `labels`, to `value`, what it is now."""
    meter = _metrics.meter
    if meter is not None:
        _metrics.gauge(meter, name, unit).set(value, _labelled(labels, None))


def enabled() -> bool:
    """Whether metrics are on in this process, for a caller to skip reading what it would record.

    Returns:
        True once `configure` turned them on.
    """
    return _metrics.meter is not None


def configure(
    state_dir: Path,
    metrics: Metrics,
    endpoint: str | None = None,
    *,
    resource: Mapping[str, str] | None = None,
) -> None:
    """Turn this process's metrics on or off, as `metrics` says, as every command does when it opens its workspace.

    `otlp` sends them to `endpoint`, an OTLP/HTTP endpoint's base URL, which config requires for it. Their resource
    names this workspace (`otlp.resource`), with the operator's own `resource` attributes. A second call with the same
    settings changes nothing.

    Raises:
        ValueError: `metrics` is `otlp` and `endpoint` names none.
    """
    match metrics:
        case "off":
            target = None
        case "file":
            target = str(state_dir / METRICS_FILE_NAME)
        case "otlp":
            if not endpoint:
                msg = "telemetry.metrics = 'otlp' needs telemetry.endpoint"
                raise ValueError(msg)
            target = endpoint.rstrip("/") + METRICS_PATH
    # The resource is a setting only while metrics go somewhere: off is off, whatever workspace it is in.
    settings = _Settings(metrics, target, state_dir, dict(resource or {})) if target is not None else None
    # Held across the check and the change: the web server's threads may each open a workspace at once.
    with _CONFIGURING:
        if settings == _metrics.settings:
            return
        _metrics.stop()
        if settings is not None:
            _metrics.start(settings)


@dataclass(frozen=True)
class _Settings:
    """Where a process's metrics go, and what their resource is made from: what a second `configure` compares."""

    metrics: Metrics
    #: The file's path, or the endpoint's URL for metrics.
    target: str
    #: The state directory, which keeps the workspace's `service.instance.id`.
    state_dir: Path
    #: The operator's own resource attributes.
    resource: Mapping[str, str]


@dataclass
class _Metrics:
    """This process's metrics: none, or a provider writing to one file or sending to one endpoint, and its instruments.

    Process-wide, as tracing's provider is: a metric is recorded deep in code that has no `Context` to pass it through.
    """

    #: Where metrics go, or None while they are off.
    settings: _Settings | None = None
    provider: MeterProvider | None = None
    meter: Meter | None = None
    #: Each instrument made so far, by kind and name: made once, on first use.
    counters: dict[str, Counter] = field(default_factory=dict)
    histograms: dict[str, Histogram] = field(default_factory=dict)
    gauges: dict[str, _Gauge] = field(default_factory=dict)

    def start(self, settings: _Settings) -> None:
        """Send this process's metrics where `settings` says, every `EXPORT_EVERY_MILLIS` and as it exits."""
        # Imported here, never at import time: a process that records no metric never loads OpenTelemetry.
        from opentelemetry.sdk.metrics import MeterProvider  # noqa: PLC0415
        from opentelemetry.sdk.metrics.export import MetricExporter, PeriodicExportingMetricReader  # noqa: PLC0415

        from canopy.infra import otlp, otlp_metrics  # noqa: PLC0415

        exporter: MetricExporter = (
            otlp_metrics.MetricHttpExporter(settings.target)
            if settings.metrics == "otlp"
            else otlp_metrics.MetricFileExporter(Path(settings.target))
        )
        reader = PeriodicExportingMetricReader(exporter, export_interval_millis=EXPORT_EVERY_MILLIS)
        provider = MeterProvider(
            resource=otlp.resource(settings.state_dir, settings.resource),
            metric_readers=[reader],
        )
        self.settings = settings
        self.provider, self.meter = provider, provider.get_meter("canopy")

    def stop(self) -> None:
        """Send what is left, close the provider, if any, and record nothing more."""
        if self.provider is not None:
            self.provider.shutdown()
        self.settings, self.provider, self.meter = None, None, None
        self.counters.clear()
        self.histograms.clear()
        self.gauges.clear()

    def counter(self, meter: Meter, name: str, unit: str) -> Counter:
        """The counter `name`, made on first use.

        Returns:
            The counter.
        """
        if name not in self.counters:
            self.counters[name] = meter.create_counter(name, unit=unit)
        return self.counters[name]

    def histogram(self, meter: Meter, name: str, unit: str) -> Histogram:
        """The histogram `name`, made on first use.

        Returns:
            The histogram.
        """
        if name not in self.histograms:
            self.histograms[name] = meter.create_histogram(name, unit=unit)
        return self.histograms[name]

    def gauge(self, meter: Meter, name: str, unit: str) -> _Gauge:
        """The gauge `name`, made on first use.

        Returns:
            The gauge.
        """
        if name not in self.gauges:
            self.gauges[name] = meter.create_gauge(name, unit=unit)
        return self.gauges[name]


_metrics = _Metrics()
_CONFIGURING = threading.Lock()


def _labelled(labels: Mapping[str, Label], model: str | None) -> dict[str, str | bool]:
    """`labels` as OpenTelemetry takes them, each word as its value, with `model` when there is one.

    Returns:
        The labels.
    """
    out: dict[str, str | bool] = {
        key: value if isinstance(value, bool) else str(value) for key, value in labels.items()
    }
    if model is not None:
        out["model"] = model
    return out
