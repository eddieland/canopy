"""The web UI's server (canopy.serve): the guard, the SPA fallback and caching, base paths, and the mock API."""

import asyncio
import json
import threading
import time
from pathlib import Path

import httpx2
import pytest
import uvicorn
from fastapi.testclient import TestClient
from pydantic import ValidationError

from canopy.serve import mock
from canopy.serve.__main__ import main
from canopy.serve.app import create_app
from canopy.serve.guard import host_name
from canopy.serve.options import ServeOptions
from canopy.serve.schema import SessionUpdated, StreamEvent
from canopy.serve.spa import content_security_policy

INDEX = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <script>document.documentElement.dataset.ok = "1";</script>
    <script type="module" src="./assets/index-abc123.js"></script>
  </head>
  <body><div id="root"></div></body>
</html>
"""


@pytest.fixture
def ui(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX)
    (root / "assets" / "index-abc123.js").write_text("console.log(1)")
    (root / "favicon.svg").write_text("<svg/>")
    return root


def client(ui_dir: Path | None, **options: object) -> TestClient:
    app = create_app(ServeOptions.model_validate({"ui_dir": ui_dir, "mock": True, **options}))
    return TestClient(app, base_url="http://127.0.0.1:8765")


def test_a_route_gets_index_html_uncached_with_a_base_href_and_a_csp(ui: Path) -> None:
    for path in ("/", "/sessions", "/worktrees/lease:1"):
        response = client(ui).get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache"
        assert '<base href="/" />' in response.text
        csp = response.headers["content-security-policy"]
        assert "script-src 'self' 'sha256-" in csp
        assert "connect-src 'self'" in csp
        assert response.headers["x-frame-options"] == "DENY"


def test_the_csp_hashes_each_inline_script_and_no_external_one() -> None:
    csp = content_security_policy('<script>a()</script><script src="x.js"></script><script>b()</script>')
    assert csp.count("'sha256-") == 2


def test_assets_are_immutable_and_a_missing_asset_is_a_404_not_the_page(ui: Path) -> None:
    c = client(ui)
    asset = c.get("/assets/index-abc123.js")
    assert asset.status_code == 200
    assert "immutable" in asset.headers["cache-control"]
    assert c.get("/favicon.svg").headers["cache-control"] == "no-cache"
    for missing in ("/assets/gone-123.js", "/assets/nested/gone", "/gone.png", "/sessions/x.js"):
        response = c.get(missing)
        assert response.status_code == 404, missing
        assert "<html" not in response.text


def test_the_fallback_never_answers_for_the_api_or_escapes_the_build(ui: Path) -> None:
    c = client(ui)
    assert c.get("/api/nope").status_code == 404
    assert c.get("/api/nope").json() == {"detail": "Not Found"}
    assert c.get("/api").status_code == 404
    assert c.post("/sessions").status_code == 405
    assert c.get("/assets/../index.html").status_code in {200, 404}  # normalized by the client to /index.html
    assert c.get("/index.html").status_code == 404
    assert c.get("/assets/%2e%2e/%2e%2e/secret.txt").status_code == 404


def test_a_base_path_prefixes_everything(ui: Path) -> None:
    c = client(ui, base_path="/canopy")
    page = c.get("/canopy/sessions")
    assert '<base href="/canopy/" />' in page.text
    assert c.get("/canopy/api/meta").json()["mock"] is True
    assert c.get("/canopy/assets/index-abc123.js").status_code == 200
    assert c.get("/canopy", follow_redirects=False).headers["location"] == "/canopy/"
    assert c.get("/sessions").status_code == 404
    assert c.get("/api/meta").status_code == 404


@pytest.mark.parametrize("base_path", ["/", "canopy", "/canopy/", "/a/../b", '/"><script>'])
def test_a_bad_base_path_is_refused(base_path: str) -> None:
    with pytest.raises(ValidationError):
        ServeOptions(base_path=base_path)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "10.0.0.5", "example.com"])  # noqa: S104
def test_only_loopback_binds_until_the_listener_secret_exists(host: str) -> None:
    with pytest.raises(ValidationError):
        ServeOptions(host=host)


def test_a_foreign_host_is_refused_everywhere(ui: Path) -> None:
    c = client(ui)
    assert c.get("/", headers={"host": "evil.example:8765"}).status_code == 403
    assert c.get("/api/meta", headers={"host": "evil.example"}).status_code == 403
    # Any port: an SSH forward to another local port sends that port.
    assert c.get("/api/meta", headers={"host": "localhost:9000"}).status_code == 200
    assert c.get("/api/meta", headers={"host": "[::1]:9000"}).status_code == 200


def test_a_foreign_origin_is_refused_on_the_api(ui: Path) -> None:
    c = client(ui)
    for origin in ("https://evil.example", "null", "http://127.0.0.1.evil.example"):
        assert c.get("/api/meta", headers={"origin": origin}).status_code == 403, origin
        assert c.get("/api/events", headers={"origin": origin}).status_code == 403, origin
    assert c.get("/api/meta", headers={"origin": "http://localhost:5173"}).status_code == 200


def test_host_name_strips_the_port() -> None:
    assert host_name("127.0.0.1:8765") == "127.0.0.1"
    assert host_name("[::1]:8765") == "::1"
    assert host_name("localhost") == "localhost"


def test_without_a_build_every_route_says_it_is_not_built(tmp_path: Path) -> None:
    for ui_dir in (None, tmp_path):
        response = client(ui_dir).get("/sessions")
        assert response.status_code == 503
        assert "not built" in response.text


def test_without_mock_the_unwired_endpoints_say_so(ui: Path) -> None:
    c = client(ui, mock=False)
    assert c.get("/api/meta").json()["mock"] is False
    for path in ("/api/sessions", "/api/leases", "/api/events"):
        assert c.get(path).status_code == 501, path


def test_mock_lists_cover_every_state(ui: Path) -> None:
    c = client(ui)
    assert {s["state"] for s in c.get("/api/sessions").json()} == {"running", "blocked", "idle", "done", "failed"}
    assert {s["state"] for s in c.get("/api/leases").json()} == {"held", "expiring", "released"}


def test_the_stream_sends_typed_events_unbuffered_over_a_real_socket(ui: Path) -> None:
    # TestClient waits for an endless stream to end, so this one runs uvicorn, on a port the OS picks.
    options = ServeOptions(ui_dir=ui, mock=True, mock_event_seconds=0.01, port=1)
    server = uvicorn.Server(uvicorn.Config(create_app(options), host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]
        with httpx2.stream("GET", f"http://127.0.0.1:{port}/api/events", timeout=10) as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["x-accel-buffering"] == "no"
            assert response.headers["cache-control"] == "no-cache"
            line = next(line for line in response.iter_lines() if line.startswith("data: "))
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    event = StreamEvent.model_validate_json(line.removeprefix("data: "))
    assert isinstance(event.root, SessionUpdated)


def test_mock_events_are_deterministic() -> None:
    async def first(n: int) -> list[str]:
        stream = mock.events()
        return [(await anext(stream)).model_dump_json() for _ in range(n)]

    assert asyncio.run(first(6)) == asyncio.run(first(6))
    kinds = [json.loads(e)["type"] for e in asyncio.run(first(3))]
    assert kinds == ["session.updated", "session.updated", "lease.updated"]


def test_openapi_names_the_stream_event(capsys: pytest.CaptureFixture[str]) -> None:
    main(["openapi"])
    schema = json.loads(capsys.readouterr().out)
    assert {"Session", "Lease", "StreamEvent", "SessionState", "LeaseState"} <= set(schema["components"]["schemas"])
    assert "/api/events" in schema["paths"]
