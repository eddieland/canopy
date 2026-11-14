"""Traces of what canopy does, through OpenTelemetry, off unless the operator turns them on.

Every span canopy makes goes through this module, as every process it starts goes through `procs`:

    with tracing.span("tick", tick_id=tick_id, dry_run=dry_run) as tick:
        ...
        tick.set(status=status)

An attribute is named `canopy.<keyword>` and holds one of canopy's own facts: an id, a kind, a status, a model, a count,
or a duration. Never text canopy read from elsewhere, such as a prompt, a ticket, a PR, or a tool's output, which is
untrusted and may be private (TRUST_MODEL T2). An event, a moment inside a span, such as a decision made or a lease
taken (`event`), holds attributes by the same rule. A span that ends by raising is marked failed with its exception's
type alone, for the same reason: an exception's message may quote what canopy read.

Until `configure` turns tracing on, a span is a no-op and OpenTelemetry is never imported, so a process that traces
nothing pays nothing for it. A child process carries its parent's span in `TRACEPARENT`, the W3C trace context, which
`procs` adds to every child's environment (`carrier`), so a detached run is traced under the tick that started it.
"""

from __future__ import annotations

import contextlib
import contextvars
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.trace import Span as OtelSpan
    from opentelemetry.trace import Tracer

#: Where a process's spans go: nowhere, appended to `TRACES_FILE_NAME` in the state directory, or sent to the OTLP/HTTP
#: endpoint the operator names.
type Traces = Literal["off", "file", "otlp"]
#: A span attribute's value; None leaves the attribute out.
type Attribute = str | int | float | bool | None

#: The file spans are appended to, as OTLP JSON, a line per span, in the state directory.
TRACES_FILE_NAME = "traces.jsonl"
#: The semantic conventions whose attributes a span may carry by their own names: the database's, for slow journal
#: queries, generative AI's, for model calls, HTTP's, for the web UI's requests, and process's, for the commands canopy
#: runs.
STANDARD_PREFIXES = ("db.", "gen_ai.", "http.", "process.")
#: Where an OTLP/HTTP endpoint takes spans, under its base URL.
TRACES_PATH = "/v1/traces"
#: The variable a child process finds its parent's span in, as OpenTelemetry names it for an environment.
TRACEPARENT = "TRACEPARENT"


class Span:
    """A span in progress: what `span` yields, to add what its step learns on the way. A no-op while tracing is off."""

    def __init__(self, inner: OtelSpan | None) -> None:
        """Wrap `inner`, OpenTelemetry's span, or None for one that records nothing."""
        self._inner = inner
        #: What `tally` added up while the span was open, its own and its children's, set on it as it ends.
        self.tallies: dict[str, float] = {}

    def tally(self, **amounts: float) -> None:
        """Add each amount to the span's total of that name, set on it as `canopy.<keyword>` as it ends."""
        if self._inner is not None:
            for key, amount in amounts.items():
                self.tallies[key] = self.tallies.get(key, 0) + amount

    def set(self, **attributes: Attribute) -> None:
        """Set each attribute, named `canopy.<keyword>`; one that is None is left as it was."""
        if self._inner is not None:
            self._inner.set_attributes(_named(attributes))

    def set_standard(self, attributes: Mapping[str, Attribute]) -> None:
        """Set each attribute a semantic convention names, by its own name; one that is None is left as it was.

        Raises:
            ValueError: An attribute is of no convention canopy records (`STANDARD_PREFIXES`).
        """
        if self._inner is not None:
            self._inner.set_attributes(_standard(attributes))

    def event(self, name: str, **attributes: Attribute) -> None:
        """Record a moment in the span, `name`, with each attribute named `canopy.<keyword>`, as `set` names them."""
        if self._inner is not None:
            self._inner.add_event(name, _named(attributes))

    def fail(self, why: str) -> None:
        """Mark the span failed, though its block raised nothing; `why` is canopy's word, never text it read."""
        if self._inner is not None:
            from opentelemetry.trace import StatusCode  # noqa: PLC0415  (imported only once tracing is on)

            self._inner.set_status(StatusCode.ERROR, why)

    def rename(self, name: str) -> None:
        """Rename the span, once its block knows a better name, as a request's span does once it is routed."""
        if self._inner is not None:
            self._inner.update_name(name)


@contextlib.contextmanager
def span(name: str, *, new_trace: bool = False, server: bool = False, **attributes: Attribute) -> Iterator[Span]:
    """Trace the `with` block as a span called `name`, a child of the span it runs in, if any.

    With `new_trace`, it starts a trace of its own instead, whatever span it runs in, as each tick does: a `canopy
    loop` started from a shell with a `TRACEPARENT` set would otherwise put every tick it ever runs in that one trace.
    With `server`, it is a server's span, as the web UI's server records each request it answers.

    Yields:
        The span, to set what the block learns. It records nothing while tracing is off.
    """
    tracer = _tracing.tracer
    if tracer is None:
        yield _OFF
        return
    from opentelemetry.context import Context  # noqa: PLC0415  (imported only once tracing is on)
    from opentelemetry.trace import (  # noqa: PLC0415
        Link,
        SpanKind,
        StatusCode,
        get_current_span,
    )

    # A new trace still points back at the span it would have been a child of, as a detached run's does at the tick's
    # step that started it.
    was_in = get_current_span().get_span_context()
    outer = _OPEN.get()
    with tracer.start_as_current_span(
        name,
        context=Context() if new_trace else None,
        links=[Link(was_in)] if new_trace and was_in.is_valid else None,
        kind=SpanKind.SERVER if server else SpanKind.INTERNAL,
        attributes=_named(attributes),
        record_exception=False,
        set_status_on_exception=False,
    ) as inner:
        traced = Span(inner)
        opened = _OPEN.set(traced)
        try:
            yield traced
        except BaseException as e:
            inner.set_status(StatusCode.ERROR, type(e).__name__)
            raise
        finally:
            _OPEN.reset(opened)
            inner.set_attributes(_named(traced.tallies))
            # A span's totals are its parent's too, so a tick's hold what each of its steps did; a new trace's are not.
            if outer is not None and not new_trace:
                outer.tally(**traced.tallies)


def enabled() -> bool:
    """Whether this process traces: for what costs something to measure, measured only when a span would hold it.

    Returns:
        Whether `configure` turned tracing on.
    """
    return _tracing.tracer is not None


def tally(**amounts: float) -> None:
    """Add each amount to the span open now, as `Span.tally` does, and so to every span it is under in this process."""
    traced = _OPEN.get()
    if traced is not None:
        traced.tally(**amounts)


def event(name: str, **attributes: Attribute) -> None:
    """Record a moment in the span open now in this process, as `Span.event` does; outside every span, nothing."""
    traced = _OPEN.get()
    if traced is not None:
        traced.event(name, **attributes)


def here() -> Here | None:
    """The span open now, for spans of what happens elsewhere, such as on a reader's thread, to be recorded under.

    Returns:
        It, or None while tracing is off.
    """
    if _tracing.tracer is None:
        return None
    from opentelemetry.context import get_current  # noqa: PLC0415

    return Here(get_current())


def ids() -> tuple[str, str] | None:
    """The trace and span ids of the span open now, in hex as OTLP JSON spells them, for a log line to name.

    Outside every span of this process's own, that is the span its parent passed in `TRACEPARENT`, if any.

    Returns:
        The trace id and the span id, or None while tracing is off or no span is open.
    """
    if _tracing.tracer is None:
        return None
    from opentelemetry.trace import get_current_span  # noqa: PLC0415  (imported only once tracing is on)

    context = get_current_span().get_span_context()
    if not context.is_valid:
        return None
    return f"{context.trace_id:032x}", f"{context.span_id:016x}"


def interval(
    name: str,
    under: Here | None,
    *,
    start_ns: int,
    end_ns: int,
    failed: bool = False,
    standard: Mapping[str, Attribute] | None = None,
    **attributes: Attribute,
) -> None:
    """Record a span of what already happened, from `start_ns` to `end_ns`, under the span `here` gave.

    `standard` holds attributes OpenTelemetry's semantic conventions name, such as `gen_ai.usage.input_tokens`, which
    keep their names; the rest are named `canopy.<keyword>`, as `span`'s are. Nothing is recorded while tracing is off.

    Raises:
        ValueError: A `standard` attribute is of no convention canopy records.
    """
    tracer = _tracing.tracer
    if tracer is None or under is None:
        return
    from opentelemetry.trace import StatusCode  # noqa: PLC0415

    named = {**_named(attributes), **_standard(standard or {})}
    inner = tracer.start_span(name, context=under.context, start_time=start_ns, attributes=named)  # pyrefly: ignore[bad-argument-type]
    if failed:
        inner.set_status(StatusCode.ERROR)
    inner.end(end_time=end_ns)


@dataclass(frozen=True)
class Here:
    """A span `here` captured, to record later spans under: OpenTelemetry's context, opaque to its holder."""

    context: object


def carrier() -> dict[str, str]:
    """The current span, as the variables a child process continues its trace from.

    Returns:
        `TRACEPARENT`, and `TRACESTATE` when there is one; none while tracing is off or no span is open.
    """
    if _tracing.tracer is None:
        return {}
    from opentelemetry.trace.propagation.tracecontext import (  # noqa: PLC0415  (imported only once tracing is on)
        TraceContextTextMapPropagator,
    )

    found: dict[str, str] = {}
    TraceContextTextMapPropagator().inject(found)
    return {key.upper(): value for key, value in found.items()}


def configure(
    state_dir: Path,
    traces: Traces,
    endpoint: str | None = None,
    *,
    resource: Mapping[str, str] | None = None,
) -> None:
    """Turn this process's tracing on or off, as `traces` says, as every command does when it opens its workspace.

    `otlp` sends spans to `endpoint`, an OTLP/HTTP endpoint's base URL, which config requires for it. Every span's
    resource names this workspace (`otlp.resource`), with the operator's own `resource` attributes. Turned on, the
    process's first span continues the trace `TRACEPARENT` names, if its parent passed one. A second call with the same
    settings, as each of `canopy _mcp`'s tool calls makes, changes nothing.

    Raises:
        ValueError: `traces` is `otlp` and `endpoint` names none.
    """
    match traces:
        case "off":
            target = None
        case "file":
            target = str(state_dir / TRACES_FILE_NAME)
        case "otlp":
            if not endpoint:
                msg = "telemetry.traces = 'otlp' needs telemetry.endpoint"
                raise ValueError(msg)
            target = endpoint.rstrip("/") + TRACES_PATH
    # The resource is a setting only while spans go somewhere: off is off, whatever workspace it is in.
    settings = _Settings(traces, target, state_dir, dict(resource or {})) if target is not None else None
    # Held across the check and the change: the web server's threads may each open a workspace at once.
    with _CONFIGURING:
        if settings == _tracing.settings:
            return
        _tracing.stop()
        if settings is not None:
            _tracing.start(settings)


@dataclass(frozen=True)
class _Settings:
    """Where a process's spans go, and what their resource is made from: what a second `configure` compares."""

    traces: Traces
    #: The file's path, or the endpoint's URL for spans.
    target: str
    #: The state directory, which keeps the workspace's `service.instance.id`.
    state_dir: Path
    #: The operator's own resource attributes.
    resource: Mapping[str, str]


@dataclass
class _Tracing:
    """This process's tracing: none, or a provider writing to one file or sending to one endpoint.

    Process-wide, as logging's handlers are: a span is made deep in code that has no `Context` to pass it through.
    """

    #: Where spans go, or None while tracing is off.
    settings: _Settings | None = None
    provider: TracerProvider | None = None
    tracer: Tracer | None = None
    #: The token of the parent context attached from `TRACEPARENT`, to detach on `stop`.
    parent: object | None = None

    def start(self, settings: _Settings) -> None:
        """Send this process's spans where `settings` says, continuing the trace in `TRACEPARENT` if there is one."""
        # Imported here, never at import time: a process that traces nothing never loads OpenTelemetry.
        from opentelemetry import context  # noqa: PLC0415
        from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor  # noqa: PLC0415
        from opentelemetry.sdk.trace.sampling import ALWAYS_ON  # noqa: PLC0415
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator  # noqa: PLC0415

        from canopy.infra import otlp  # noqa: PLC0415

        # Every span, whatever the parent says: the operator turned tracing on, and a `TRACEPARENT` canopy did not set,
        # from whatever started it, may say its trace is not sampled.
        resource = otlp.resource(settings.state_dir, settings.resource)
        provider = TracerProvider(resource=resource, sampler=ALWAYS_ON)
        if settings.traces == "otlp":
            # Sent in batches, by a thread of the SDK's, so no step waits on the network; what is left is sent as the
            # process exits, within the exporter's timeout, so an endpoint that is down delays an exit by that alone.
            provider.add_span_processor(BatchSpanProcessor(otlp.HttpExporter(settings.target)))
        else:
            # Each span is written as it ends: a detached run may be killed before a batch would have been.
            provider.add_span_processor(SimpleSpanProcessor(otlp.FileExporter(Path(settings.target))))
        inherited = {key.lower(): value for key, value in os.environ.items() if key in {TRACEPARENT, "TRACESTATE"}}
        parent = TraceContextTextMapPropagator().extract(inherited)
        self.parent = context.attach(parent) if inherited else None
        self.settings = settings
        self.provider, self.tracer = provider, provider.get_tracer("canopy")

    def stop(self) -> None:
        """Flush and close the provider, if any, and record nothing more."""
        if self.provider is not None:
            self.provider.shutdown()
        if self.parent is not None:
            from opentelemetry import context  # noqa: PLC0415

            context.detach(self.parent)  # pyrefly: ignore[bad-argument-type]  # the token `attach` returned
        self.settings, self.provider, self.tracer, self.parent = None, None, None, None


_tracing = _Tracing()
#: The span of canopy's open now in this thread or task, for `tally` and `event`.
_OPEN: contextvars.ContextVar[Span | None] = contextvars.ContextVar("canopy_span", default=None)
_CONFIGURING = threading.Lock()
_OFF = Span(None)


def _standard(attributes: Mapping[str, Attribute]) -> dict[str, str | int | float | bool]:
    """`attributes`, by the names their convention gives them, less any that is None.

    Returns:
        The attributes, as OpenTelemetry takes them.

    Raises:
        ValueError: An attribute is of no convention canopy records (`STANDARD_PREFIXES`).
    """
    unknown = [key for key in attributes if not key.startswith(STANDARD_PREFIXES)]
    if unknown:
        msg = f"not an attribute of a convention canopy records: {', '.join(unknown)}"
        raise ValueError(msg)
    return {key: value for key, value in attributes.items() if value is not None}


def _named(attributes: Mapping[str, Attribute]) -> dict[str, str | int | float | bool]:
    """`attributes` named `canopy.<keyword>`, less any that is None.

    Returns:
        The attributes, as OpenTelemetry takes them.
    """
    return {f"canopy.{key}": value for key, value in attributes.items() if value is not None}
