"""OTLP export: posted as OTLP JSON to the endpoint the operator names alone, under a resource naming the workspace."""

import contextlib
import json
import os
import stat
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar, override
from unittest import mock

import pytest

from canopy.infra import metrics, otlp, tracing


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


def test_metrics_are_posted_as_otlp_json_to_the_endpoints_metrics_path(tmp_path: Path) -> None:
    with endpoint() as url:
        metrics.configure(tmp_path, "otlp", url)
        metrics.count("canopy.ticks", dry_run=False)
        metrics.configure(tmp_path, "off")
    [heard] = _Endpoint.heard
    assert (heard.method, heard.path, heard.content_type) == ("POST", metrics.METRICS_PATH, "application/json")
    [scope] = heard.body["resourceMetrics"][0]["scopeMetrics"]
    assert [m["name"] for m in scope["metrics"]] == ["canopy.ticks"]


def resources(path: Path, signal: str) -> list[dict[str, object]]:
    """The resource each export request in a telemetry file names, its attributes as a plain dict of their values."""
    return [
        {a["key"]: next(iter(a["value"].values())) for a in exported["resource"]["attributes"]}
        for line in path.read_text().splitlines()
        for exported in json.loads(line)[signal]
    ]


def test_each_workspace_names_itself_in_every_signals_resource_and_keeps_its_name(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    for state_dir in (first, second, first):
        state_dir.mkdir(exist_ok=True)
        tracing.configure(state_dir, "file", resource={"deployment.environment.name": "laptop"})
        metrics.configure(state_dir, "file", resource={"deployment.environment.name": "laptop"})
        with tracing.span("tick"):
            metrics.count("canopy.ticks", dry_run=False)
        # Turning them off sends what is left, as a process's exit does; the next turn is another process's.
        tracing.configure(state_dir, "off")
        metrics.configure(state_dir, "off")
    names: dict[Path, set[object]] = {}
    for state_dir in (first, second):
        found = [
            *resources(state_dir / tracing.TRACES_FILE_NAME, "resourceSpans"),
            *resources(state_dir / metrics.METRICS_FILE_NAME, "resourceMetrics"),
        ]
        assert {(r["service.name"], r["deployment.environment.name"]) for r in found} == {("canopy", "laptop")}
        names[state_dir] = {r["service.instance.id"] for r in found}
        assert stat.S_IMODE((state_dir / otlp.INSTANCE_FILE_NAME).stat().st_mode) == 0o600
    # One name for each workspace, in every process and signal, and never its path.
    [first_name], [second_name] = names[first], names[second]
    assert first_name != second_name
    assert str(tmp_path) not in json.dumps([first_name, second_name])


def test_processes_that_race_to_name_a_workspace_agree_on_one_name(tmp_path: Path) -> None:
    with ThreadPoolExecutor(max_workers=8) as pool:
        named = set(pool.map(otlp.instance_id, [tmp_path] * 32))
    assert named == {(tmp_path / otlp.INSTANCE_FILE_NAME).read_text().strip()}
    # Nothing is left of the ids that lost.
    assert [p.name for p in tmp_path.iterdir()] == [otlp.INSTANCE_FILE_NAME]


def test_a_name_canopy_cannot_read_is_left_out_and_fails_nothing(tmp_path: Path) -> None:
    (tmp_path / otlp.INSTANCE_FILE_NAME).write_text("not an id\n")
    assert otlp.instance_id(tmp_path) is None
    attributes = otlp.resource(tmp_path, {"service.name": "not canopy", "host.name": "studio"}).attributes
    # OpenTelemetry's SDK names the process instead, as it does by default.
    assert attributes["service.instance.id"] != "not an id"
    # The operator's own attributes never replace canopy's.
    assert (attributes["service.name"], attributes["host.name"]) == ("canopy", "studio")


def test_configuring_again_with_other_resource_attributes_starts_anew(tmp_path: Path) -> None:
    tracing.configure(tmp_path, "file", resource={"deployment.environment.name": "staging"})
    with tracing.span("before"):
        pass
    tracing.configure(tmp_path, "file", resource={"deployment.environment.name": "production"})
    with tracing.span("after"):
        pass
    tracing.configure(tmp_path, "off")
    found = resources(tmp_path / tracing.TRACES_FILE_NAME, "resourceSpans")
    assert [r["deployment.environment.name"] for r in found] == ["staging", "production"]
