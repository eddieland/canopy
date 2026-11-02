"""Spans in OTLP's JSON encoding, and the exporters that append them to a file or post them to an OTLP/HTTP endpoint.

The encoding is OTLP/JSON's `ExportTraceServiceRequest`: what an OpenTelemetry Collector's `otlpjsonfile` receiver reads
from a file, a request per line, and what an OTLP/HTTP endpoint takes as `application/json`. Only `tracing` imports
this module, and only once tracing is on, since importing it loads OpenTelemetry's SDK.

`HttpExporter` is the harness's one network call (TRUST_MODEL T2): made only to the endpoint the operator names in their
own config, carrying canopy's spans and nothing else, through no proxy and following no redirect, so the spans reach
that endpoint or none.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, override

# The harness's one network call: this module alone may make it (TRUST_MODEL T2).
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener  # noqa: TID251

from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.util.types import AttributeValue

#: Who may read the traces file: the operator alone, as the log (TRUST_MODEL T2).
FILE_MODE = 0o600
#: How long a post may take: the longest an endpoint that is down delays a process's exit, which sends what is left.
TIMEOUT_SECONDS = 5


class FileExporter(SpanExporter):
    """Appends each batch of spans to a file, as one line of OTLP JSON."""

    def __init__(self, path: Path) -> None:
        """Append to `path`, which is made, readable by the operator alone, if it is not there."""
        self.path = path

    @override
    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Append `spans` as one line, opening the file anew each time, so it follows a rotation.

        Returns:
            Whether the whole line was written.
        """
        line = (json.dumps(encoded(spans), separators=(",", ":")) + "\n").encode()
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, FILE_MODE)
        except OSError:
            return SpanExportResult.FAILURE
        try:
            # One write of the whole line: appended so, another process's line never lands inside it.
            written = os.write(fd, line)
        except OSError:
            return SpanExportResult.FAILURE
        finally:
            os.close(fd)
        return SpanExportResult.SUCCESS if written == len(line) else SpanExportResult.FAILURE

    @override
    def shutdown(self) -> None:
        """Nothing to close: the file is open only while a line is written."""


class HttpExporter(SpanExporter):
    """Posts each batch of spans, as OTLP JSON, to an OTLP/HTTP endpoint's spans URL."""

    def __init__(self, url: str) -> None:
        """Post to `url`, `<endpoint>/v1/traces`, which config held to `http` or `https`."""
        self.url = url
        self._failing = False

    @override
    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Post `spans` once, never again: a batch the endpoint did not take is dropped, and the next is posted anew.

        Returns:
            Whether the endpoint took them, with a 2xx.
        """
        request = Request(  # noqa: S310  (config holds the URL to http or https)
            self.url,
            data=json.dumps(encoded(spans), separators=(",", ":")).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with _OPENER.open(request, timeout=TIMEOUT_SECONDS) as response:
                took = 200 <= response.status < 300  # noqa: PLR2004  (HTTP's success range)
                why = f"HTTP {response.status}"
        # Whatever the network or the endpoint does, a span never fails what canopy was doing.
        except Exception as e:  # noqa: BLE001
            took, why = False, type(e).__name__
        self._note(took=took, why=why)
        return SpanExportResult.SUCCESS if took else SpanExportResult.FAILURE

    @override
    def shutdown(self) -> None:
        """Nothing to close: each post opens and closes its own connection."""

    def _note(self, *, took: bool, why: str) -> None:
        """Log when posts start failing, and when they recover: once each, not once per batch."""
        if took == (not self._failing):
            return
        self._failing = not took
        if took:
            _LOG.info("traces sent again", extra={"endpoint": self.url})
        else:
            _LOG.warning(
                "traces not sent; spans are dropped until the endpoint takes them",
                extra={"endpoint": self.url, "error": why},
            )


class _NoRedirect(HTTPRedirectHandler):
    """Refuses every redirect: a post reaches the endpoint the operator named, or fails."""

    @override
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        """Follow none: returning nothing makes urllib raise the redirect as an error."""


# No proxy, whatever the environment names: a post reaches the endpoint the operator named, a collector on this machine
# included, or fails.
_OPENER = build_opener(ProxyHandler({}), _NoRedirect())
_LOG = logging.getLogger("canopy")


def encoded(spans: Sequence[ReadableSpan]) -> dict[str, object]:
    """`spans` as an OTLP/JSON `ExportTraceServiceRequest`, grouped by resource and then by instrumentation scope.

    Returns:
        The request, for `json.dumps`.
    """
    by_resource: dict[int, tuple[ReadableSpan, dict[tuple[str, str | None], list[dict[str, object]]]]] = {}
    for span in spans:
        _, scopes = by_resource.setdefault(id(span.resource), (span, {}))
        scope = span.instrumentation_scope
        key = (scope.name, scope.version) if scope is not None else ("", None)
        scopes.setdefault(key, []).append(_span(span))
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": _attributes(first.resource.attributes)},
                "scopeSpans": [
                    {"scope": {"name": name, **({"version": v} if v else {})}, "spans": encoded_spans}
                    for (name, v), encoded_spans in scopes.items()
                ],
            }
            for first, scopes in by_resource.values()
        ],
    }


# OTLP numbers span kinds from 1, where OpenTelemetry's Python `SpanKind` numbers them from 0.
_KIND_OFFSET = 1


def _span(span: ReadableSpan) -> dict[str, object]:
    """One span, in OTLP/JSON: ids in hex, times in nanoseconds as strings, as the encoding has 64-bit integers.

    Returns:
        The span.
    """
    context = span.get_span_context()
    out: dict[str, object] = {
        "traceId": f"{context.trace_id:032x}" if context is not None else "",
        "spanId": f"{context.span_id:016x}" if context is not None else "",
        "name": span.name,
        "kind": span.kind.value + _KIND_OFFSET,
        "startTimeUnixNano": str(span.start_time or 0),
        "endTimeUnixNano": str(span.end_time or 0),
        "attributes": _attributes(span.attributes),
        "status": {
            "code": span.status.status_code.value,
            **({"message": span.status.description} if span.status.description else {}),
        },
    }
    if span.parent is not None:
        out["parentSpanId"] = f"{span.parent.span_id:016x}"
    if span.events:
        out["events"] = [
            {"timeUnixNano": str(e.timestamp), "name": e.name, "attributes": _attributes(e.attributes)}
            for e in span.events
        ]
    if span.links:
        out["links"] = [
            {
                "traceId": f"{link.context.trace_id:032x}",
                "spanId": f"{link.context.span_id:016x}",
                "attributes": _attributes(link.attributes),
            }
            for link in span.links
        ]
    return out


def _attributes(attributes: Mapping[str, AttributeValue] | None) -> list[dict[str, object]]:
    """Attributes as OTLP's list of key and typed value.

    Returns:
        The list, empty for none.
    """
    return [{"key": key, "value": _value(value)} for key, value in (attributes or {}).items()]


def _value(value: AttributeValue) -> dict[str, object]:
    """One attribute's value, typed: a bool before an int, as a bool is one; an int as a string, being 64-bit.

    Returns:
        The typed value.
    """
    match value:
        case bool():
            return {"boolValue": value}
        case int():
            return {"intValue": str(value)}
        case float():
            return {"doubleValue": value}
        case str():
            return {"stringValue": value}
        case None:
            return {}
        case _:
            return {"arrayValue": {"values": [_value(v) for v in value]}}
