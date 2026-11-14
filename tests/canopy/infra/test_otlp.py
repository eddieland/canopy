"""OTLP export: posted as OTLP JSON to the endpoint the operator names alone, under a resource naming the workspace."""

from __future__ import annotations

import contextlib
import json
import os
import re
import stat
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, override
from unittest import mock

import pytest

from canopy.infra import exports, metrics, otlp, tracing

if TYPE_CHECKING:
    from tests.canopy.scenario_helpers import Scenario

#: The longest a test waits for an export, or holds one at work.
DEADLINE_SECONDS = 30


@dataclass
class Heard:
    """A request the endpoint heard: its method, path, content type, body, and the status it was answered with."""

    method: str
    path: str
    content_type: str
    body: dict[str, Any] = field(default_factory=dict)
    answered: int = 200


class _Endpoint(BaseHTTPRequestHandler):
    """An OTLP/HTTP endpoint that answers every request with `status`, and a redirect's `Location`."""

    status: ClassVar[int] = 200
    heard: ClassVar[list[Heard]] = []
    #: Set once a request arrives.
    reached: ClassVar[threading.Event] = threading.Event()
    #: While set, an event each request waits for before it is answered, holding its export at work.
    hold: ClassVar[threading.Event | None] = None

    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        body = json.loads(raw) if raw else {}
        status = _Endpoint.status
        _Endpoint.heard.append(Heard("POST", self.path, self.headers.get("Content-Type", ""), body, status))
        _Endpoint.reached.set()
        if _Endpoint.hold is not None:
            _Endpoint.hold.wait(timeout=DEADLINE_SECONDS)
        self.send_response(status)
        if 300 <= status < 400:
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
    _Endpoint.reached = threading.Event()
    _Endpoint.hold = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Endpoint)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def ledger(state_dir: Path, url: str) -> exports.Ledger:
    """A ledger of spans posted to `url`'s traces path, kept in `state_dir`."""
    return exports.Ledger(state_dir, exports.Signal.TRACES, url + tracing.TRACES_PATH)


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
def test_an_endpoint_that_does_not_take_a_batch_drops_it_and_a_redirect_is_not_followed(
    status: int,
    tmp_path: Path,
) -> None:
    with endpoint(status) as url:
        exporter = otlp.HttpExporter(url + tracing.TRACES_PATH, ledger(tmp_path, url))
        assert exporter.export([]) is otlp.SpanExportResult.FAILURE
    # Posted once, to the endpoint alone: never again, nor to where a redirect pointed.
    assert [h.path for h in _Endpoint.heard] == [tracing.TRACES_PATH]


def test_an_endpoint_that_is_down_fails_the_batch_and_nothing_else(tmp_path: Path) -> None:
    with endpoint() as url:
        pass
    exporter = otlp.HttpExporter(url + tracing.TRACES_PATH, ledger(tmp_path, url))
    assert exporter.export([]) is otlp.SpanExportResult.FAILURE
    # The state file says why, in canopy's own words.
    assert exports.read(tmp_path)[exports.Signal.TRACES].error == "URLError"


def test_otlp_without_an_endpoint_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"needs telemetry\.endpoint"):
        tracing.configure(tmp_path, "otlp")


def test_a_proxy_the_environment_names_is_not_used(tmp_path: Path) -> None:
    # A proxy that is not there: were it used, the post would fail.
    unreachable = {
        "HTTP_PROXY": "http://127.0.0.1:9",
        "http_proxy": "http://127.0.0.1:9",
        "NO_PROXY": "",
        "no_proxy": "",
    }
    with endpoint() as url, mock.patch.dict(os.environ, unreachable):
        exporter = otlp.HttpExporter(url + tracing.TRACES_PATH, ledger(tmp_path, url))
        assert exporter.export([]) is otlp.SpanExportResult.SUCCESS
    assert [h.path for h in _Endpoint.heard] == [tracing.TRACES_PATH]


def test_metrics_are_posted_as_otlp_json_to_the_endpoints_metrics_path(tmp_path: Path) -> None:
    with endpoint() as url:
        metrics.configure(tmp_path, "otlp", url)
        metrics.count("canopy.ticks", dry_run=False)
        metrics.configure(tmp_path, "off")
    [heard] = _Endpoint.heard
    assert (heard.method, heard.path, heard.content_type) == ("POST", metrics.METRICS_PATH, "application/json")
    [scope] = heard.body["resourceMetrics"][0]["scopeMetrics"]
    assert [m["name"] for m in scope["metrics"]] == ["canopy.ticks", exports.EXPORTS]
    # The export counts itself: the last a process makes, as it exits, is counted too.
    assert counted(heard) == {("metrics", "sent"): 1}


def counted(heard: Heard, name: str = exports.EXPORTS) -> dict[tuple[str, ...], int]:
    """What one export of metrics counted under `name`, by the values of each point's labels."""
    return {
        tuple(a["value"]["stringValue"] for a in point["attributes"]): int(point["asInt"])
        for resource in heard.body["resourceMetrics"]
        for scope in resource["scopeMetrics"]
        for metric in scope["metrics"]
        if metric["name"] == name
        for point in metric["sum"]["dataPoints"]
    }


def test_what_an_export_the_endpoint_refused_counted_rides_the_next_it_takes(tmp_path: Path) -> None:
    with endpoint(503) as url, mock.patch.object(metrics, "EXPORT_EVERY_MILLIS", 20):
        tracing.configure(tmp_path, "otlp", url)
        metrics.configure(tmp_path, "otlp", url)
        # A gauge is sent in every export, so each has something for the counts to ride.
        metrics.gauge("canopy.disk.free", 1)
        with tracing.span("tick"):
            pass
        # The span's batch is refused as tracing turns off, and the counts wait while metrics are refused too.
        tracing.configure(tmp_path, "off")
        # Two more refused, so the export the endpoint takes first was made once the span's batch was refused.
        refused_before = len(_Endpoint.heard)
        _wait_for(lambda: len(_Endpoint.heard) >= refused_before + 2)
        _Endpoint.status = 200
        _wait_for(lambda: any(h.answered == 200 for h in _Endpoint.heard))
        metrics.configure(tmp_path, "off")
    posted = [h for h in _Endpoint.heard if h.path == metrics.METRICS_PATH]
    refused = [h for h in posted if h.answered == 503]
    first, *later = [h for h in posted if h.answered == 200]
    # The first export taken carries every count the refused ones did, and itself; each later one, itself alone.
    assert counted(first) == {("metrics", "failed"): len(refused), ("metrics", "sent"): 1, ("traces", "failed"): 1}
    assert all(counted(h) == {("metrics", "sent"): 1} for h in later)
    assert exports.read(tmp_path)[exports.Signal.TRACES].failing


def test_a_span_the_full_queue_drops_is_counted_and_kept(tmp_path: Path) -> None:
    # A queue of one span, sent one at a time, as soon as it is queued.
    small = {"OTEL_BSP_MAX_QUEUE_SIZE": "1", "OTEL_BSP_MAX_EXPORT_BATCH_SIZE": "1", "OTEL_BSP_SCHEDULE_DELAY": "1"}
    with endpoint() as url, mock.patch.dict(os.environ, small):
        metrics.configure(tmp_path, "file")
        tracing.configure(tmp_path, "otlp", url)
        _Endpoint.hold = threading.Event()
        for name in ("first", "second", "third"):
            with tracing.span(name):
                pass
            # The first is posted, and held there: the second waits in the queue, and the third finds no room.
            assert _Endpoint.reached.wait(DEADLINE_SECONDS)
        _Endpoint.hold.set()
        tracing.configure(tmp_path, "off")
        metrics.gauge("canopy.disk.free", 1)
        metrics.configure(tmp_path, "off")
    # The SDK keeps the newer span and drops the older; either way, one was lost.
    assert [name for h in _Endpoint.heard for name in span_names(h)] == ["first", "third"]
    [line] = (tmp_path / metrics.METRICS_FILE_NAME).read_text().splitlines()
    sent = Heard("", "", "", json.loads(line))
    assert counted(sent, exports.SPANS_DROPPED) == {(): 1}
    assert exports.read(tmp_path)[exports.Signal.TRACES].dropped_at is not None


def test_status_says_traces_are_not_being_taken_while_the_endpoint_refuses_them(scenario: Scenario) -> None:
    with endpoint(503) as url:
        scenario.configures("private", telemetry={"traces": "otlp", "metrics": "file", "endpoint": url})
        traces = f"traces  to {url}{tracing.TRACES_PATH}"
        assert f"{traces}, no export yet" in scenario.operator("status").out
        scenario.tick()
        # The tick's spans are sent as its process exits.
        tracing.configure(scenario.env.state_dir, "off")
        out = scenario.operator("status").out
    assert re.search(rf"{re.escape(traces)}, not being taken: the last export failed \d+s ago \(HTTP 503\); never", out)
    assert f"metrics  to {scenario.env.state_dir / metrics.METRICS_FILE_NAME}, no export yet" in out


def test_status_says_nothing_of_telemetry_while_it_is_off(scenario: Scenario) -> None:
    assert "Telemetry" not in scenario.operator("status").out


def _wait_for(done: Callable[[], bool]) -> None:
    """Poll until `done`, failing the test past the deadline."""
    deadline = time.monotonic() + DEADLINE_SECONDS
    while not done():
        assert time.monotonic() < deadline, "the endpoint never heard what the test waits for"
        time.sleep(0.01)


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
    # The process is named instead, by one id, so its spans and its metrics name the same instance.
    assert attributes["service.instance.id"] != "not an id"
    assert otlp.resource(tmp_path, {}).attributes["service.instance.id"] == attributes["service.instance.id"]
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
