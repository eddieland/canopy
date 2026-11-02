"""Traces of what canopy does, through OpenTelemetry, off unless the operator turns them on.

Every span canopy makes goes through this module, as every process it starts goes through `procs`:

    with tracing.span("tick", tick_id=tick_id, dry_run=dry_run) as tick:
        ...
        tick.set(status=status)

An attribute is named `canopy.<keyword>` and holds one of canopy's own facts: an id, a kind, a status, a model, a count,
or a duration. Never text canopy read from elsewhere, such as a prompt, a ticket, a PR, or a tool's output, which is
untrusted and may be private (TRUST_MODEL T2). A span that ends by raising is marked failed with its exception's type
alone, for the same reason: an exception's message may quote what canopy read.

Until `configure` turns tracing on, a span is a no-op and OpenTelemetry is never imported, so a process that traces
nothing pays nothing for it. A child process carries its parent's span in `TRACEPARENT`, the W3C trace context, which
`procs` adds to every child's environment (`carrier`), so a detached run is traced under the tick that started it.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.trace import Span as OtelSpan
    from opentelemetry.trace import Tracer

#: Where a process's spans go: nowhere, or appended to `TRACES_FILE_NAME` in the state directory.
type Traces = Literal["off", "file"]
#: A span attribute's value; None leaves the attribute out.
type Attribute = str | int | float | bool | None

#: The file spans are appended to, as OTLP JSON, a line per span, in the state directory.
TRACES_FILE_NAME = "traces.jsonl"
#: The variable a child process finds its parent's span in, as OpenTelemetry names it for an environment.
TRACEPARENT = "TRACEPARENT"
#: The service a span's resource names.
SERVICE = "canopy"


class Span:
    """A span in progress: what `span` yields, to add what its step learns on the way. A no-op while tracing is off."""

    def __init__(self, inner: OtelSpan | None) -> None:
        """Wrap `inner`, OpenTelemetry's span, or None for one that records nothing."""
        self._inner = inner

    def set(self, **attributes: Attribute) -> None:
        """Set each attribute, named `canopy.<keyword>`; one that is None is left as it was."""
        if self._inner is not None:
            self._inner.set_attributes(_named(attributes))


@contextlib.contextmanager
def span(name: str, **attributes: Attribute) -> Iterator[Span]:
    """Trace the `with` block as a span called `name`, a child of the span it runs in, if any.

    Yields:
        The span, to set what the block learns. It records nothing while tracing is off.
    """
    tracer = _tracing.tracer
    if tracer is None:
        yield _OFF
        return
    from opentelemetry.trace import StatusCode  # noqa: PLC0415  (imported only once tracing is on)

    with tracer.start_as_current_span(
        name,
        attributes=_named(attributes),
        record_exception=False,
        set_status_on_exception=False,
    ) as inner:
        try:
            yield Span(inner)
        except BaseException as e:
            inner.set_status(StatusCode.ERROR, type(e).__name__)
            raise


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


def configure(state_dir: Path, traces: Traces) -> None:
    """Turn this process's tracing on or off, as `traces` says, as every command does when it opens its workspace.

    Turned on, the process's first span continues the trace `TRACEPARENT` names, if its parent passed one. A second
    call with the same settings, as each of `canopy _mcp`'s tool calls makes, changes nothing.
    """
    path = state_dir / TRACES_FILE_NAME if traces == "file" else None
    if path == _tracing.path:
        return
    _tracing.stop()
    if path is not None:
        _tracing.start(path)


@dataclass
class _Tracing:
    """This process's tracing: none, or a provider writing to one file.

    Process-wide, as logging's handlers are: a span is made deep in code that has no `Context` to pass it through.
    """

    path: Path | None = None
    provider: TracerProvider | None = None
    tracer: Tracer | None = None
    #: The token of the parent context attached from `TRACEPARENT`, to detach on `stop`.
    parent: object | None = None

    def start(self, path: Path) -> None:
        """Send this process's spans to `path`, continuing the trace in `TRACEPARENT` if there is one."""
        # Imported here, never at import time: a process that traces nothing never loads OpenTelemetry.
        from opentelemetry import context  # noqa: PLC0415
        from opentelemetry.sdk.resources import Resource  # noqa: PLC0415
        from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: PLC0415
        from opentelemetry.sdk.trace.sampling import ALWAYS_ON  # noqa: PLC0415
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator  # noqa: PLC0415

        from canopy.infra import otlp  # noqa: PLC0415

        resource = Resource.create({"service.name": SERVICE, "service.version": version("canopy")})
        # Every span, whatever the parent says: the operator turned tracing on, and a `TRACEPARENT` canopy did not set,
        # from whatever started it, may say its trace is not sampled.
        provider = TracerProvider(resource=resource, sampler=ALWAYS_ON)
        # Each span is written as it ends: a detached run may be killed before a batch would have been.
        provider.add_span_processor(SimpleSpanProcessor(otlp.FileExporter(path)))
        inherited = {key.lower(): value for key, value in os.environ.items() if key in {TRACEPARENT, "TRACESTATE"}}
        parent = TraceContextTextMapPropagator().extract(inherited)
        self.parent = context.attach(parent) if inherited else None
        self.path, self.provider, self.tracer = path, provider, provider.get_tracer("canopy")

    def stop(self) -> None:
        """Flush and close the provider, if any, and record nothing more."""
        if self.provider is not None:
            self.provider.shutdown()
        if self.parent is not None:
            from opentelemetry import context  # noqa: PLC0415

            context.detach(self.parent)  # pyrefly: ignore[bad-argument-type]  # the token `attach` returned
        self.path = self.provider = self.tracer = self.parent = None


_tracing = _Tracing()
_OFF = Span(None)


def _named(attributes: Mapping[str, Attribute]) -> dict[str, str | int | float | bool]:
    """`attributes` named `canopy.<keyword>`, less any that is None.

    Returns:
        The attributes, as OpenTelemetry takes them.
    """
    return {f"canopy.{key}": value for key, value in attributes.items() if value is not None}
