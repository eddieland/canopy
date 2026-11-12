"""Metrics of what canopy does, through OpenTelemetry, off until the operator turns them on (D132).

Every metric canopy records goes through this module, as every span goes through `tracing`:

    metrics.count("canopy.runs", role=Role.WORKER, status=RunStatus.DONE)
    metrics.record("canopy.run.duration", 312.5, unit="s", role=Role.WORKER, status=RunStatus.DONE)
    metrics.gauge("canopy.runs.active", 2, role=Role.WORKER)

A label is one of canopy's closed vocabularies, a `StrEnum` member or a flag, so a label never holds a ticket key, a
path, or text, and a metric's series stay as few as the vocabularies' words (D132). The one other label is `model`,
which only the operator's config names. Each metric is named in `INSTRUMENTS`, with its description and, for a
histogram, its buckets' bounds, so the type checker refuses a name it does not hold.

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
    from collections.abc import Mapping, Sequence

    from opentelemetry.metrics import Counter, Histogram, Meter, _Gauge
    from opentelemetry.sdk.metrics import MeterProvider

#: Where a process's metrics go: nowhere, appended to `METRICS_FILE_NAME` in the state directory, or sent to the
#: OTLP/HTTP endpoint the operator names.
type Metrics = Literal["off", "file", "otlp"]
#: A metric's label: a word of one of canopy's closed vocabularies, or a flag (D132).
type Label = StrEnum | bool
#: Each counter canopy records, which `count` alone takes.
type CounterName = Literal["canopy.ticks", "canopy.runs", "canopy.cost", "canopy.tokens"]
#: Each histogram canopy records, which `record` alone takes.
type HistogramName = Literal["canopy.tick.duration", "canopy.run.duration"]
#: Each gauge canopy sets, which `gauge` alone takes.
type GaugeName = Literal["canopy.runs.active"]
#: Each metric canopy records, as `INSTRUMENTS` describes it. A name is one kind of instrument only: the type checker
#: refuses a histogram's name to `count`, so no name is exported as two kinds.
type MetricName = CounterName | HistogramName | GaugeName

#: The file metrics are appended to, as OTLP JSON, a line per export, in the state directory.
METRICS_FILE_NAME = "metrics.jsonl"
#: Where an OTLP/HTTP endpoint takes metrics, under its base URL.
METRICS_PATH = "/v1/metrics"
#: How often a process sends what it has recorded; it sends what is left as it exits, whatever the time.
EXPORT_EVERY_MILLIS = 30_000


@dataclass(frozen=True)
class Instrument:
    """What a collector is told of one metric beyond its name and unit."""

    #: What it measures, sent with every export.
    description: str
    #: A histogram's buckets' upper bounds, in its unit; empty for a counter or a gauge. The SDK's own default is made
    #: for milliseconds, and canopy's times are seconds.
    bounds: Sequence[float] = ()


#: How long a tick takes, in seconds: a quiet one well under a second, one whose overseer works some minutes.
_TICK_SECONDS = (0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600)
#: How long an agent run takes, in seconds: a short chore some seconds, a worker's longest some hours.
_RUN_SECONDS = (10, 30, 60, 120, 300, 600, 1200, 1800, 3600, 7200, 14400, 28800)

#: Every metric canopy records, by name.
INSTRUMENTS: Mapping[MetricName, Instrument] = {
    "canopy.ticks": Instrument("Ticks that closed, by status, and whether each was a dry run."),
    "canopy.tick.duration": Instrument("How long a tick took, from its start to its close, by status.", _TICK_SECONDS),
    "canopy.runs": Instrument("Agent runs that ended, by role and status, and a worker's by kind."),
    "canopy.run.duration": Instrument("How long an agent run ran, by role and status.", _RUN_SECONDS),
    "canopy.cost": Instrument("What agent runs cost, as the runtime reported, by role and model."),
    "canopy.tokens": Instrument("The tokens agent runs spent, by role, model, and type."),
    "canopy.runs.active": Instrument("The agent runs at work as a tick closes, by role."),
}


def count(name: CounterName, value: float = 1, *, unit: str = "1", model: str | None = None, **labels: Label) -> None:
    """Add `value` to the counter `name`, under `labels`, and the model that did the work, if any."""
    meter = _metrics.meter
    if meter is not None:
        _metrics.counter(meter, name, unit).add(value, _labelled(labels, model))


def record(name: HistogramName, value: float, *, unit: str, model: str | None = None, **labels: Label) -> None:
    """Record `value`, in `unit`, in the histogram `name`, under `labels`, and the model that did the work, if any."""
    meter = _metrics.meter
    if meter is not None:
        _metrics.histogram(meter, name, unit).record(value, _labelled(labels, model))


def gauge(name: GaugeName, value: float, *, unit: str = "1", **labels: Label) -> None:
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


def configure(state_dir: Path, metrics: Metrics, endpoint: str | None = None) -> None:
    """Turn this process's metrics on or off, as `metrics` says, as every command does when it opens its workspace.

    `otlp` sends them to `endpoint`, an OTLP/HTTP endpoint's base URL, which config requires for it. A second call with
    the same settings changes nothing.

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
    # Held across the check and the change: the web server's threads may each open a workspace at once.
    with _CONFIGURING:
        if (metrics, target) == (_metrics.metrics, _metrics.target):
            return
        _metrics.stop()
        if target is not None:
            _metrics.start(metrics, target)


@dataclass
class _Metrics:
    """This process's metrics: none, or a provider writing to one file or sending to one endpoint, and its instruments.

    Process-wide, as tracing's provider is: a metric is recorded deep in code that has no `Context` to pass it through.
    """

    metrics: Metrics = "off"
    #: The file's path, or the endpoint's URL for metrics.
    target: str | None = None
    provider: MeterProvider | None = None
    meter: Meter | None = None
    #: Each instrument made so far, by kind and name: made once, on first use.
    counters: dict[str, Counter] = field(default_factory=dict)
    histograms: dict[str, Histogram] = field(default_factory=dict)
    gauges: dict[str, _Gauge] = field(default_factory=dict)

    def start(self, metrics: Metrics, target: str) -> None:
        """Send this process's metrics to `target`, every `EXPORT_EVERY_MILLIS` and as it exits."""
        # Imported here, never at import time: a process that records no metric never loads OpenTelemetry.
        from opentelemetry.sdk.metrics import MeterProvider  # noqa: PLC0415
        from opentelemetry.sdk.metrics.export import MetricExporter, PeriodicExportingMetricReader  # noqa: PLC0415

        from canopy.infra import otlp, otlp_metrics  # noqa: PLC0415

        exporter: MetricExporter = (
            otlp_metrics.MetricHttpExporter(target)
            if metrics == "otlp"
            else otlp_metrics.MetricFileExporter(Path(target))
        )
        reader = PeriodicExportingMetricReader(exporter, export_interval_millis=EXPORT_EVERY_MILLIS)
        provider = MeterProvider(resource=otlp.resource(), metric_readers=[reader])
        self.metrics, self.target = metrics, target
        self.provider, self.meter = provider, provider.get_meter("canopy")

    def stop(self) -> None:
        """Send what is left, close the provider, if any, and record nothing more."""
        if self.provider is not None:
            self.provider.shutdown()
        self.metrics, self.target, self.provider, self.meter = "off", None, None, None
        self.counters.clear()
        self.histograms.clear()
        self.gauges.clear()

    def counter(self, meter: Meter, name: CounterName, unit: str) -> Counter:
        """The counter `name`, made on first use.

        Returns:
            The counter.
        """
        if name not in self.counters:
            self.counters[name] = meter.create_counter(name, unit=unit, description=INSTRUMENTS[name].description)
        return self.counters[name]

    def histogram(self, meter: Meter, name: HistogramName, unit: str) -> Histogram:
        """The histogram `name`, made on first use.

        Returns:
            The histogram.
        """
        if name not in self.histograms:
            instrument = INSTRUMENTS[name]
            self.histograms[name] = meter.create_histogram(
                name,
                unit=unit,
                description=instrument.description,
                explicit_bucket_boundaries_advisory=instrument.bounds,
            )
        return self.histograms[name]

    def gauge(self, meter: Meter, name: GaugeName, unit: str) -> _Gauge:
        """The gauge `name`, made on first use.

        Returns:
            The gauge.
        """
        if name not in self.gauges:
            self.gauges[name] = meter.create_gauge(name, unit=unit, description=INSTRUMENTS[name].description)
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
