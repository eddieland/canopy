"""The web UI's server traces each request as a server span named for its route, holding nothing the client sent."""

from pathlib import Path

from canopy.infra import tracing
from canopy.serve.backend import Backend
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
    client(None, backend).get("/api/runs")
    assert not (tmp_path / tracing.TRACES_FILE_NAME).exists()
