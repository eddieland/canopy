"""OTLP export over HTTP: spans posted as OTLP JSON to the endpoint the operator names, and nowhere else."""

import contextlib
import json
import os
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar, override
from unittest import mock

import pytest

from canopy.infra import otlp, tracing


@dataclass
class Heard:
    """A request the endpoint heard: its method, path, content type, and body."""

    method: str
    path: str
    content_type: str
    body: dict[str, Any] = field(default_factory=dict)


class _Endpoint(BaseHTTPRequestHandler):
    """An OTLP/HTTP endpoint that answers every request with `status`, and a redirect's `Location`."""

    status: ClassVar[int] = 200
    heard: ClassVar[list[Heard]] = []

    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        body = json.loads(raw) if raw else {}
        _Endpoint.heard.append(Heard("POST", self.path, self.headers.get("Content-Type", ""), body))
        self.send_response(_Endpoint.status)
        if 300 <= _Endpoint.status < 400:
            self.send_header("Location", "/elsewhere")
        self.send_header("Content-Length", "0")
        self.end_headers()

    @override
    def log_message(self, format: str, *args: Any) -> None:
        del format, args


@contextlib.contextmanager
def endpoint(status: int = 200) -> Iterator[str]:
    """Serve an endpoint answering `status` until the block ends. Yields its base URL."""
    _Endpoint.status = status
    _Endpoint.heard = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Endpoint)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def span_names(heard: Heard) -> list[str]:
    """The names of the spans one request carried."""
    return [
        span["name"]
        for resource in heard.body["resourceSpans"]
        for scope in resource["scopeSpans"]
        for span in scope["spans"]
    ]


def test_spans_are_posted_as_otlp_json_to_the_endpoints_traces_path(tmp_path: Path) -> None:
    with endpoint() as url:
        tracing.configure(tmp_path, "otlp", url)
        with tracing.span("tick", new_trace=True, tick_id=1), tracing.span("state"):
            pass
        # Turning tracing off sends what is left, as a process's exit does.
        tracing.configure(tmp_path, "off")
    [heard] = _Endpoint.heard
    assert (heard.method, heard.path, heard.content_type) == ("POST", tracing.TRACES_PATH, "application/json")
    assert span_names(heard) == ["state", "tick"]
    assert not (tmp_path / tracing.TRACES_FILE_NAME).exists()


@pytest.mark.parametrize("status", [500, 302])
def test_an_endpoint_that_does_not_take_a_batch_drops_it_and_a_redirect_is_not_followed(status: int) -> None:
    with endpoint(status) as url:
        exporter = otlp.HttpExporter(url + tracing.TRACES_PATH)
        assert exporter.export([]) is otlp.SpanExportResult.FAILURE
    # Posted once, to the endpoint alone: never again, nor to where a redirect pointed.
    assert [h.path for h in _Endpoint.heard] == [tracing.TRACES_PATH]


def test_an_endpoint_that_is_down_fails_the_batch_and_nothing_else() -> None:
    with endpoint() as url:
        pass
    assert otlp.HttpExporter(url + tracing.TRACES_PATH).export([]) is otlp.SpanExportResult.FAILURE


def test_otlp_without_an_endpoint_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"needs telemetry\.endpoint"):
        tracing.configure(tmp_path, "otlp")


def test_a_proxy_the_environment_names_is_not_used() -> None:
    # A proxy that is not there: were it used, the post would fail.
    unreachable = {
        "HTTP_PROXY": "http://127.0.0.1:9",
        "http_proxy": "http://127.0.0.1:9",
        "NO_PROXY": "",
        "no_proxy": "",
    }
    with endpoint() as url, mock.patch.dict(os.environ, unreachable):
        assert otlp.HttpExporter(url + tracing.TRACES_PATH).export([]) is otlp.SpanExportResult.SUCCESS
    assert [h.path for h in _Endpoint.heard] == [tracing.TRACES_PATH]
