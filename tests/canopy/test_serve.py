"""The web UI's server (canopy.serve): the guard, the SPA fallback and caching, base paths, signing in, the stream, and
the mock journal. The API over a real journal, and the loop serving it, are in test_web.py."""

import json
import stat
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx2
import pytest
import uvicorn
from fastapi.testclient import TestClient
from pydantic import ValidationError

from canopy.serve import mock, secret
from canopy.serve.__main__ import main
from canopy.serve.app import create_app
from canopy.serve.auth import SESSION_SECONDS, Sessions
from canopy.serve.backend import Backend
from canopy.serve.guard import host_name
from canopy.serve.options import ServeOptions
from canopy.serve.schema import (
    AttentionUpdated,
    ChoresUpdated,
    LoopUpdated,
    RunsUpdated,
    SpendUpdated,
    StreamEvent,
    TicketChanged,
    TicketsUpdated,
    TickUpdated,
)
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
SECRET = "s3cret-" + "x" * 40
ORIGIN = "http://127.0.0.1:8765"


@pytest.fixture
def ui(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX)
    (root / "assets" / "index-abc123.js").write_text("console.log(1)")
    (root / "favicon.svg").write_text("<svg/>")
    return root


@pytest.fixture
def backend(tmp_path: Path) -> Backend:
    return mock.seed(tmp_path / "mock")


def client(ui_dir: Path | None, backend: Backend, *, key: str | None = None, **options: object) -> TestClient:
    opts = ServeOptions.model_validate({"ui_dir": ui_dir, "mock": True, "mock_event_seconds": None, **options})
    sessions = Sessions(key, port=opts.port, base_path=opts.base_path, hosts=opts.hosts)
    return TestClient(create_app(opts, backend, sessions), base_url="http://127.0.0.1:8765")


def signed_in(c: TestClient, *, base: str = "") -> dict[str, str]:
    """Sign `c` in; return the headers a write needs."""
    response = c.post(f"{base}/api/session", json={"secret": SECRET})
    assert response.status_code == 200
    token = response.json()["token"]
    assert isinstance(token, str)
    return {"x-canopy-token": token, "origin": ORIGIN}


# Serving the app


def test_a_route_gets_index_html_uncached_with_a_base_href_and_a_csp(ui: Path, backend: Backend) -> None:
    for path in ("/", "/runs", "/tickets/ABC-1"):
        response = client(ui, backend).get(path)
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


def test_assets_are_immutable_and_a_missing_asset_is_a_404_not_the_page(ui: Path, backend: Backend) -> None:
    c = client(ui, backend)
    asset = c.get("/assets/index-abc123.js")
    assert asset.status_code == 200
    assert "immutable" in asset.headers["cache-control"]
    assert c.get("/favicon.svg").headers["cache-control"] == "no-cache"
    for missing in ("/assets/gone-123.js", "/assets/nested/gone", "/gone.png", "/runs/x.js"):
        response = c.get(missing)
        assert response.status_code == 404, missing
        assert "<html" not in response.text


def test_the_fallback_never_answers_for_the_api_or_escapes_the_build(ui: Path, backend: Backend) -> None:
    c = client(ui, backend)
    assert c.get("/api/nope").status_code == 404
    assert c.get("/api/nope").json() == {"detail": "Not Found"}
    assert c.get("/api").status_code == 404
    assert c.post("/runs").status_code == 405
    assert c.get("/assets/../index.html").status_code in {200, 404}  # normalized by the client to /index.html
    assert c.get("/index.html").status_code == 404
    assert c.get("/assets/%2e%2e/%2e%2e/secret.txt").status_code == 404


def test_a_base_path_prefixes_everything(ui: Path, backend: Backend) -> None:
    c = client(ui, backend, base_path="/canopy")
    page = c.get("/canopy/runs")
    assert '<base href="/canopy/" />' in page.text
    assert c.get("/canopy/api/meta").json()["mock"] is True
    assert c.get("/canopy/assets/index-abc123.js").status_code == 200
    assert c.get("/canopy", follow_redirects=False).headers["location"] == "/canopy/"
    assert c.get("/runs").status_code == 404
    assert c.get("/api/meta").status_code == 404


@pytest.mark.parametrize("base_path", ["/", "canopy", "/canopy/", "/a/../b", '/"><script>'])
def test_a_bad_base_path_is_refused(base_path: str) -> None:
    with pytest.raises(ValidationError):
        ServeOptions(base_path=base_path)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "8.8.8.8", "2001:4860::8888", "224.0.0.1", "example.com"])  # noqa: S104
def test_a_wildcard_public_or_named_bind_is_refused(host: str) -> None:
    with pytest.raises(ValidationError):
        ServeOptions(host=host)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "10.0.0.5", "192.168.1.20", "fd00::5"])
def test_loopback_and_private_binds_are_allowed(host: str) -> None:
    assert ServeOptions(host=host).host == host


def test_a_foreign_host_is_refused_everywhere(ui: Path, backend: Backend) -> None:
    c = client(ui, backend)
    assert c.get("/", headers={"host": "evil.example:8765"}).status_code == 403
    assert c.get("/api/meta", headers={"host": "evil.example"}).status_code == 403
    # Any port: an SSH forward to another local port sends that port.
    assert c.get("/api/meta", headers={"host": "localhost:9000"}).status_code == 200
    assert c.get("/api/meta", headers={"host": "[::1]:9000"}).status_code == 200


def test_a_private_bind_allows_its_own_address_as_host_and_origin(ui: Path, backend: Backend) -> None:
    c = client(ui, backend, host="10.0.0.5")
    assert c.get("/api/meta", headers={"host": "10.0.0.5:8765", "origin": "http://10.0.0.5:8765"}).status_code == 200
    assert c.get("/api/meta", headers={"host": "10.0.0.6:8765"}).status_code == 403
    assert client(ui, backend).get("/api/meta", headers={"host": "10.0.0.5"}).status_code == 403


def test_a_foreign_origin_is_refused_on_the_api(ui: Path, backend: Backend) -> None:
    c = client(ui, backend)
    for origin in ("https://evil.example", "null", "http://127.0.0.1.evil.example"):
        assert c.get("/api/meta", headers={"origin": origin}).status_code == 403, origin
        assert c.get("/api/events", headers={"origin": origin}).status_code == 403, origin
    assert c.get("/api/meta", headers={"origin": "http://localhost:5173"}).status_code == 200


def test_host_name_strips_the_port() -> None:
    assert host_name("127.0.0.1:8765") == "127.0.0.1"
    assert host_name("[::1]:8765") == "::1"
    assert host_name("localhost") == "localhost"


def test_without_a_build_every_route_says_it_is_not_built(tmp_path: Path, backend: Backend) -> None:
    for ui_dir in (None, tmp_path):
        response = client(ui_dir, backend).get("/runs")
        assert response.status_code == 503
        assert "not built" in response.text


# Signing in with the listener secret (DESIGN §22)


def test_with_a_secret_the_app_loads_but_every_api_route_needs_a_session(ui: Path, backend: Backend) -> None:
    c = client(ui, backend, key=SECRET)
    assert c.get("/").status_code == 200
    assert c.get("/assets/index-abc123.js").status_code == 200
    assert c.get("/api/session").json() == {"signed_in": False, "token": None}
    paths = ("/api/meta", "/api/attention", "/api/runs", "/api/tickets", "/api/tickets/ABC-102", "/api/events")
    # A transcript is agent output from a file, and a review's diff the PR's text: as much the operator's as the rest.
    files = ("/api/runs/39", "/api/runs/39/transcript", "/api/ticks/2/transcript", "/api/reviews", "/api/reviews/4")
    for path in (*paths, *files):
        assert c.get(path).status_code == 401, path
    assert c.post("/api/tickets/ABC-102/start", headers={"origin": ORIGIN}).status_code == 401


def test_a_wrong_secret_is_refused_slowly_and_sets_no_cookie(
    ui: Path, backend: Backend, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("canopy.serve.api.FAILED_SIGN_IN_SECONDS", 0.2)
    c = client(ui, backend, key=SECRET)
    began = time.monotonic()
    response = c.post("/api/session", json={"secret": SECRET + "x"})
    assert response.status_code == 401
    assert time.monotonic() - began >= 0.2
    assert "set-cookie" not in response.headers
    assert c.post("/api/session", json={"secret": ""}).status_code == 422


def test_signing_in_sets_an_httponly_strict_cookie_named_for_the_port_and_scoped_to_the_base(
    ui: Path, backend: Backend
) -> None:
    c = client(ui, backend, key=SECRET, base_path="/canopy", port=9001)
    response = c.post("/canopy/api/session", json={"secret": SECRET})
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("canopy_session_9001=v1.")
    for attribute in ("HttpOnly", "Path=/canopy/", "SameSite=strict", f"Max-Age={SESSION_SECONDS}"):
        assert attribute in cookie
    assert SECRET not in cookie
    assert c.get("/canopy/api/meta").status_code == 200
    session = c.get("/canopy/api/session").json()
    assert session["signed_in"] is True
    assert session["token"] == response.json()["token"]


def test_a_write_needs_the_sessions_token_and_an_origin(ui: Path, backend: Backend) -> None:
    c = client(ui, backend, key=SECRET)
    headers = signed_in(c)
    url = "/api/tickets/ABC-102/replies"
    body = {"body": "red", "submission": "submission-1"}
    assert c.post(url, json=body, headers={"origin": ORIGIN}).status_code == 403
    assert c.post(url, json=body, headers={**headers, "x-canopy-token": "forged"}).status_code == 403
    assert c.post(url, json=body, headers={"x-canopy-token": headers["x-canopy-token"]}).status_code == 403
    assert c.post(url, json=body, headers={**headers, "origin": "https://evil.example"}).status_code == 403
    assert c.post(url, json=body, headers=headers).status_code == 200


def test_signing_out_clears_the_cookie(ui: Path, backend: Backend) -> None:
    c = client(ui, backend, key=SECRET)
    signed_in(c)
    response = c.delete("/api/session", headers={"origin": ORIGIN})
    assert response.json() == {"signed_in": False, "token": None}
    assert c.get("/api/meta").status_code == 401


def test_a_session_is_signed_with_the_secret_and_expires() -> None:
    clock = [1_000_000.0]
    hosts = frozenset({"127.0.0.1"})
    sessions = Sessions(SECRET, port=1, base_path="", hosts=hosts, clock=lambda: clock[0])
    value = sessions.issue()
    signed = sessions.check(value)
    assert signed is not None
    # Another secret's server, a loop after `canopy secret --rotate`, does not accept it.
    assert Sessions("other" * 10, port=1, base_path="", hosts=hosts, clock=lambda: clock[0]).check(value) is None
    version, issued, nonce, mac = value.split(".")
    assert sessions.check(f"{version}.{int(issued) + 1}.{nonce}.{mac}") is None
    assert sessions.check(f"{version}.{issued}.{nonce}x.{mac}") is None
    assert sessions.check("garbage") is None
    assert sessions.token(signed) not in value
    clock[0] += SESSION_SECONDS + 1
    assert sessions.check(value) is None


def test_without_a_secret_mock_data_needs_no_session(ui: Path, backend: Backend) -> None:
    c = client(ui, backend)
    assert c.get("/api/session").json() == {"signed_in": True, "token": "open"}
    assert c.get("/api/meta").json()["mock"] is True


# The listener secret's file


def test_canopy_secret_files_are_the_operators_alone(tmp_path: Path) -> None:
    file = tmp_path / "config" / secret.FILE_NAME
    with pytest.raises(secret.SecretError, match="canopy secret"):
        secret.read(file)
    value, written = secret.create(file, rotate=False)
    assert written
    assert len(value) >= secret.MIN_LENGTH
    assert stat.S_IMODE(file.stat().st_mode) == 0o600
    assert secret.read(file) == value
    assert secret.create(file, rotate=False) == (value, False)
    rotated, written = secret.create(file, rotate=True)
    assert written
    assert rotated != value

    file.chmod(0o640)
    with pytest.raises(secret.SecretError, match="chmod 600"):
        secret.read(file)
    file.chmod(0o600)
    file.write_text("short\n")
    with pytest.raises(secret.SecretError, match="32"):
        secret.read(file)
    file.write_text("x" * 40 + " y\n")
    with pytest.raises(secret.SecretError):
        secret.read(file)
    target = tmp_path / "elsewhere"
    target.write_text("x" * 40)
    target.chmod(0o600)
    file.unlink()
    file.symlink_to(target)
    with pytest.raises(secret.SecretError, match="symlink"):
        secret.read(file)


# The event stream


@pytest.fixture
def served(ui: Path, backend: Backend) -> Iterator[int]:
    """The mock app on a real socket, on a port the OS picks: TestClient waits for an endless stream to end."""
    options = ServeOptions(ui_dir=ui, mock=True, mock_event_seconds=0.05)
    sessions = Sessions(None, port=options.port, base_path="", hosts=options.hosts)
    config = uvicorn.Config(create_app(options, backend, sessions), host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        yield server.servers[0].sockets[0].getsockname()[1]
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def read_events(port: int, n: int) -> tuple[httpx2.Headers, list[StreamEvent]]:
    found: list[StreamEvent] = []
    with httpx2.stream("GET", f"http://127.0.0.1:{port}/api/events", timeout=10) as response:
        for line in response.iter_lines():
            if line.startswith("data: "):
                found.append(StreamEvent.model_validate_json(line.removeprefix("data: ")))
            if len(found) == n:
                return response.headers, found
    raise AssertionError(f"the stream ended after {len(found)} events")


def test_the_stream_starts_with_every_list_then_sends_what_changed(served: int) -> None:
    headers, events = read_events(served, 9)
    assert headers["content-type"].startswith("text/event-stream")
    assert headers["x-accel-buffering"] == "no"
    assert headers["cache-control"] == "no-cache"
    first, runs, tickets, chores, spend, tick, loop, changed, spent = (e.root for e in events)
    assert isinstance(first, AttentionUpdated)
    assert isinstance(runs, RunsUpdated)
    assert isinstance(tickets, TicketsUpdated)
    assert isinstance(chores, ChoresUpdated)
    assert [c.name for c in chores.chores] == ["build-health", "deps"]
    assert isinstance(spend, SpendUpdated)
    assert isinstance(tick, TickUpdated)
    assert tick.tick is not None
    assert (tick.tick.id, tick.tick.status, tick.acknowledged) == (2, "ok", 8)
    assert isinstance(loop, LoopUpdated)
    assert loop.paused is None
    # The mock journal moves the running run's cost: only the runs list and the spend are sent again.
    assert isinstance(changed, RunsUpdated)
    before = next(r for r in runs.runs if r.id == mock.LIVE_RUN)
    after = next(r for r in changed.runs if r.id == mock.LIVE_RUN)
    assert after.cost_usd is not None
    assert before.cost_usd is not None
    assert after.cost_usd > before.cost_usd
    assert isinstance(spent, SpendUpdated)
    assert (spent.spend.day.hours, spent.spend.month.hours) == (24, 720)
    for was, now in ((spend.spend.day, spent.spend.day), (spend.spend.month, spent.spend.month)):
        assert now.cost_usd is not None
        assert was.cost_usd is not None
        assert now.cost_usd == pytest.approx(was.cost_usd + after.cost_usd - before.cost_usd)


def test_a_change_to_a_ticket_sends_the_list_and_names_the_ticket(served: int, backend: Backend) -> None:
    def reply_soon() -> None:
        time.sleep(0.3)
        with backend.open() as ctx:
            ctx.conn.execute(
                "INSERT INTO messages (subject_kind, subject_id, at, source, kind, channel, body) "
                "VALUES ('ticket', 'ABC-103', '2026-10-08T13:00:00.000Z', 'operator', 'reply', 'cli', 'later')"
            )

    threading.Thread(target=reply_soon, daemon=True).start()
    found: list[StreamEvent] = []
    with httpx2.stream("GET", f"http://127.0.0.1:{served}/api/events", timeout=10) as response:
        for line in response.iter_lines():
            if line.startswith("data: "):
                found.append(StreamEvent.model_validate_json(line.removeprefix("data: ")))
            if any(isinstance(e.root, TicketChanged) for e in found):
                break
    changed = next(e.root for e in found if isinstance(e.root, TicketChanged))
    assert changed.key == "ABC-103"
    lists = [e.root for e in found if isinstance(e.root, TicketsUpdated)]
    assert len(lists) == 2
    assert lists[1].tickets[0].key == "ABC-103"


# The development server and the schema


def test_the_mock_journal_covers_every_run_state_and_message_source(ui: Path, backend: Backend) -> None:
    c = client(ui, backend)
    assert {r["state"] for r in c.get("/api/runs").json()} == {"running", "blocked", "done", "failed"}
    sources = {
        m["source"]
        for key in ("ABC-101", "ABC-102", "ABC-103")
        for m in c.get(f"/api/tickets/{key}").json()["messages"]
    }
    assert sources == {"worker", "operator", "tracker"}


def test_the_development_server_serves_mock_data_only(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["serve"])
    assert "--mock" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["serve", "--mock", "--host", "10.0.0.5"])
    assert "loopback" in capsys.readouterr().err


def test_openapi_names_the_stream_event_and_every_route(capsys: pytest.CaptureFixture[str]) -> None:
    main(["openapi"])
    schema = json.loads(capsys.readouterr().out)
    names = {
        "Run",
        "RunState",
        "TicketSummary",
        "TicketDetail",
        "Message",
        "AttentionItem",
        "StreamEvent",
        "Pool",
        "Spend",
        "SpendWindow",
        "Tick",
        "ChoreSummary",
        "ChoreDetail",
        "TickDetail",
        "Decision",
        "Transcript",
        "TranscriptStatus",
        "SearchResults",
        "SearchHit",
        "LoopState",
        "Pause",
        "PauseChanged",
    }
    assert names <= set(schema["components"]["schemas"])
    paths = {
        "/api/session",
        "/api/meta",
        "/api/attention",
        "/api/runs",
        "/api/runs/{run_id}",
        "/api/runs/{run_id}/transcript",
        "/api/spend",
        "/api/tick",
        "/api/tickets",
        "/api/tickets/{key}",
        "/api/tickets/{key}/start",
        "/api/tickets/{key}/stop",
        "/api/tickets/{key}/replies",
        "/api/tickets/{key}/forget",
        "/api/chores",
        "/api/chores/{name}",
        "/api/chores/{name}/replies",
        "/api/ticks",
        "/api/ticks/{tick_id}",
        "/api/ticks/{tick_id}/transcript",
        "/api/worktrees",
        "/api/search",
        "/api/events",
        "/api/loop",
        "/api/reviews",
        "/api/reviews/{run_id}",
        "/api/loop/pause",
        "/api/loop/resume",
    }
    assert set(schema["paths"]) == paths
