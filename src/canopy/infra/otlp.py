"""Spans in OTLP's JSON encoding, their exporters, and how any signal is appended to a file or posted to an endpoint.

The encoding is OTLP/JSON's export request: what an OpenTelemetry Collector's `otlpjsonfile` receiver reads from a file,
a request per line, and what an OTLP/HTTP endpoint takes as `application/json`. `otlp_metrics` encodes metrics the same
way, through `append_line` and `Poster`. Only `tracing` and `metrics` import these modules, and only once their signal
is on, since importing them loads OpenTelemetry's SDK.

`Poster` is the harness's one network call (TRUST_MODEL T2): made only to the endpoint the operator names in their own
config, carrying canopy's spans and metrics and nothing else, through no proxy and following no redirect, so they reach
that endpoint or none.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, override

# The harness's one network call: this module alone may make it (TRUST_MODEL T2).
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener  # noqa: TID251

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.util.types import AttributeValue

#: Who may read a telemetry file: the operator alone, as the log (TRUST_MODEL T2).
FILE_MODE = 0o600
#: The service every signal's resource names.
SERVICE = "canopy"
#: The file in the state directory that keeps the workspace's `service.instance.id`: a random id, made once.
INSTANCE_FILE_NAME = "instance-id"
#: This process's `service.instance.id` when the workspace's can be neither made nor read: one id, so its spans and
#: its metrics still name the same instance.
_PROCESS_INSTANCE = str(uuid.uuid4())
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
        return SpanExportResult.SUCCESS if append_line(self.path, encoded(spans)) else SpanExportResult.FAILURE

    @override
    def shutdown(self) -> None:
        """Nothing to close: the file is open only while a line is written."""


class HttpExporter(SpanExporter):
    """Posts each batch of spans, as OTLP JSON, to an OTLP/HTTP endpoint's spans URL."""

    def __init__(self, url: str) -> None:
        """Post to `url`, `<endpoint>/v1/traces`, which config held to `http` or `https`."""
        self.poster = Poster(url, "traces")

    @override
    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Post `spans` once, never again: a batch the endpoint did not take is dropped, and the next is posted anew.

        Returns:
            Whether the endpoint took them, with a 2xx.
        """
        return SpanExportResult.SUCCESS if self.poster.post(encoded(spans)) else SpanExportResult.FAILURE

    @override
    def shutdown(self) -> None:
        """Nothing to close: each post opens and closes its own connection."""


def resource(state_dir: Path, extra: Mapping[str, str]) -> Resource:
    """What every signal canopy sends says it came from: canopy, at the version installed, in this workspace.

    `service.instance.id` tells one workspace from another, on one machine or many, without naming its path. `extra`
    holds the operator's own attributes (`telemetry.resource`), which never replace canopy's.

    Returns:
        The resource, for a provider of spans or of metrics.
    """
    own = {
        "service.name": SERVICE,
        "service.version": version("canopy"),
        "service.instance.id": instance_id(state_dir) or _PROCESS_INSTANCE,
    }
    return Resource.create({**extra, **own})


def instance_id(state_dir: Path) -> str | None:
    """The workspace's instance id, kept in `INSTANCE_FILE_NAME` in `state_dir`, made by the first process to need it.

    Returns:
        The id, or None, logged, when it can be neither made nor read: telemetry never fails what canopy was doing,
        and `resource` then names this process alone, the same for its spans and its metrics.
    """
    path = state_dir / INSTANCE_FILE_NAME
    try:
        if not path.exists():
            _make_instance_id(path)
        return str(uuid.UUID(path.read_text(encoding="utf-8").strip()))
    except (OSError, ValueError) as e:
        _LOG.warning(
            "telemetry sent without service.instance.id",
            extra={"file": str(path), "error": type(e).__name__},
        )
        return None


def _make_instance_id(path: Path) -> None:
    """Write a random id at `path`, readable by the operator alone, unless another process wrote one first.

    It is written whole to a file of its own and linked into place, so no process reads half an id, and of two that
    race, the one linked first is kept, and each reads it back.
    """
    fd, made = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        # Written whole or raised: a short write never leaves part of an id to link into place.
        with os.fdopen(fd, "w", encoding="utf-8") as made_file:
            made_file.write(f"{uuid.uuid4()}\n")
        with contextlib.suppress(FileExistsError):
            os.link(made, path)
    finally:
        Path(made).unlink()


def append_line(path: Path, request: Mapping[str, object]) -> bool:
    """Append `request`, an OTLP/JSON export request, to `path` as one line, made readable by the operator alone.

    The file is opened anew each time, so it follows a rotation, and written in one write, so a line another process
    appends never lands inside it.

    Returns:
        Whether the whole line was written.
    """
    line = (json.dumps(request, separators=(",", ":")) + "\n").encode()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, FILE_MODE)
    except OSError:
        return False
    try:
        written = os.write(fd, line)
    except OSError:
        return False
    finally:
        os.close(fd)
    return written == len(line)


class Poster:
    """Posts OTLP/JSON export requests to one of an endpoint's URLs: the harness's one network call (TRUST_MODEL T2)."""

    def __init__(self, url: str, signal: str) -> None:
        """Post to `url`, which config held to `http` or `https`; `signal`, `traces` or `metrics`, names it in logs."""
        self.url = url
        self.signal = signal
        self._failing = False

    def post(self, request: Mapping[str, object]) -> bool:
        """Post `request` once, never again: one the endpoint did not take is dropped.

        Returns:
            Whether the endpoint took it, with a 2xx.
        """
        posted = Request(  # noqa: S310  (config holds the URL to http or https)
            self.url,
            data=json.dumps(request, separators=(",", ":")).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with _OPENER.open(posted, timeout=TIMEOUT_SECONDS) as response:
                took = 200 <= response.status < 300  # noqa: PLR2004  (HTTP's success range)
                why = f"HTTP {response.status}"
        # Whatever the network or the endpoint does, telemetry never fails what canopy was doing.
        except Exception as e:  # noqa: BLE001
            took, why = False, type(e).__name__
        self._note(took=took, why=why)
        return took

    def _note(self, *, took: bool, why: str) -> None:
        """Log when posts start failing, and when they recover: once each, not once per request."""
        if took == (not self._failing):
            return
        self._failing = not took
        if took:
            _LOG.info(f"{self.signal} sent again", extra={"endpoint": self.url})
        else:
            _LOG.warning(
                f"{self.signal} not sent; they are dropped until the endpoint takes them",
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
                "resource": {"attributes": attributes(first.resource.attributes)},
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
        "attributes": attributes(span.attributes),
        "status": {
            "code": span.status.status_code.value,
            **({"message": span.status.description} if span.status.description else {}),
        },
    }
    if span.parent is not None:
        out["parentSpanId"] = f"{span.parent.span_id:016x}"
    if span.events:
        out["events"] = [
            {"timeUnixNano": str(e.timestamp), "name": e.name, "attributes": attributes(e.attributes)}
            for e in span.events
        ]
    if span.links:
        out["links"] = [
            {
                "traceId": f"{link.context.trace_id:032x}",
                "spanId": f"{link.context.span_id:016x}",
                "attributes": attributes(link.attributes),
            }
            for link in span.links
        ]
    return out


def attributes(values: Mapping[str, AttributeValue] | None) -> list[dict[str, object]]:
    """Attributes as OTLP's list of key and typed value.

    Returns:
        The list, empty for none.
    """
    return [{"key": key, "value": _value(value)} for key, value in (values or {}).items()]


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
