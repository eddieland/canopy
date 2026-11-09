"""The web UI's server traces each request as a server span named for its route, holding nothing the client sent."""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from starlette.types import Receive, Scope, Send

from canopy.infra import tracing
from canopy.serve.backend import Backend
from canopy.serve.traced import Traced
from tests.canopy.helpers import spans
from tests.canopy.web_helpers import client

#: OTLP's `SPAN_KIND_SERVER`, as the traces file spells a request's span.
SERVER = 2


def served(path: Path, count: int) -> list[dict[str, Any]]:
    """The `count` server spans in traces file `path`, in the order written.

    Tracing is the whole process's, so the file also holds any span another thread of the test's worker opened while it
    was on; those are not a request's, and are left out. The failure lists every span, to name the one that was not.
    """
    found = spans(path)
    server = [s for s in found if s["kind"] == SERVER]
    assert len(server) == count, [(s["name"], s["kind"]) for s in found]
    return server


def test_a_request_is_a_server_span_named_for_its_route_never_its_values(tmp_path: Path, backend: Backend) -> None:
    tracing.configure(tmp_path, "file")
    c = client(None, backend)
    c.get("/api/runs/39/transcript?secret=token-in-query", headers={"traceparent": f"00-{'a' * 32}-{'b' * 16}-01"})
    c.request("BREW", "/api/runs")
    tracing.configure(tmp_path, "off")
    written = (tmp_path / tracing.TRACES_FILE_NAME).read_text()
    transcript, brewed = served(tmp_path / tracing.TRACES_FILE_NAME, 2)
    assert transcript["name"] == "GET /api/runs/{run_id}/transcript"
    # A trace of its own: the client's traceparent is not read.
    assert transcript["traceId"] != "a" * 32
    assert "parentSpanId" not in transcript
    assert {k: v for k, v in transcript["attributes"].items() if k.startswith("http.")} == {
        "http.request.method": "GET",
        "http.route": "/api/runs/{run_id}/transcript",
        "http.response.status_code": "200",
    }
    # What the request asked of the journal, run on the server's worker threads.
    assert int(transcript["attributes"]["canopy.journal_queries"]) > 0
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
    broken, missing = served(tmp_path / tracing.TRACES_FILE_NAME, 2)
    assert broken["status"] == {"code": 2, "message": "503"}
    assert missing["status"] == {"code": 0}
