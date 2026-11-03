"""The web UI's server traces each request as a server span named for its route, holding nothing the client sent."""

from pathlib import Path

from fastapi.testclient import TestClient
from starlette.types import Receive, Scope, Send

from canopy.infra import tracing
from canopy.serve.backend import Backend
from canopy.serve.traced import Traced
from tests.canopy.helpers import spans
from tests.canopy.web_helpers import client


def test_a_request_is_a_server_span_named_for_its_route_never_its_values(tmp_path: Path, backend: Backend) -> None:
    tracing.configure(tmp_path, "file")
    c = client(None, backend)
    c.get("/api/runs/39/transcript?secret=token-in-query", headers={"traceparent": f"00-{'a' * 32}-{'b' * 16}-01"})
    c.request("BREW", "/api/runs")
    tracing.configure(tmp_path, "off")
    written = (tmp_path / tracing.TRACES_FILE_NAME).read_text()
    transcript, brewed = spans(tmp_path / tracing.TRACES_FILE_NAME)
    assert transcript["name"] == "GET /api/runs/{run_id}/transcript"
    # A server span, of a trace of its own: the client's traceparent is not read.
    assert transcript["kind"] == 2
    assert transcript["traceId"] != "a" * 32
    assert "parentSpanId" not in transcript
    assert transcript["attributes"] == {
        "http.request.method": "GET",
        "http.route": "/api/runs/{run_id}/transcript",
        "http.response.status_code": "200",
    }
    # A method HTTP does not name is `_OTHER`; nothing the client sent beyond it is kept.
    assert brewed["attributes"]["http.request.method"] == "_OTHER"
    assert "BREW" not in written
    assert "/runs/39" not in written
    assert "token-in-query" not in written


def test_a_server_that_does_not_trace_writes_no_spans(tmp_path: Path, backend: Backend) -> None:
    tracing.configure(tmp_path, "file")
    tracing.configure(tmp_path, "off")
    client(None, backend).get("/api/runs")
    assert not (tmp_path / tracing.TRACES_FILE_NAME).exists()


def test_a_request_answered_with_a_server_error_is_a_failed_span_and_a_client_error_is_not(tmp_path: Path) -> None:
    async def answers(scope: Scope, receive: Receive, send: Send) -> None:
        status = 503 if scope["path"] == "/api/broken" else 404
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    tracing.configure(tmp_path, "file")
    browser = TestClient(Traced(answers, api_prefix="/api"))
    browser.get("/api/broken")
    browser.get("/api/missing")
    tracing.configure(tmp_path, "off")
    broken, missing = spans(tmp_path / tracing.TRACES_FILE_NAME)
    assert broken["status"] == {"code": 2, "message": "503"}
    assert missing["status"] == {"code": 0}
