"""The web UI's server (canopy.serve) and the mock journal.

The guard, the SPA fallback and caching, base paths, signing in, and the stream. The API over a real journal, and the
loop serving it, are in test_web.py.
"""

import asyncio
import dataclasses
import json
import logging
import re
import sqlite3
import stat
import threading
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager, suppress
from importlib.metadata import version
from pathlib import Path
from typing import override
from unittest import mock

import anyio
import httpx2
import pytest
import uvicorn
from pydantic import ValidationError
from starlette.types import Message, Receive, Scope, Send

from canopy.core import conversation, db, review_runs
from canopy.core.context import Context, db_path
from canopy.infra import logs
from canopy.runs import tasks
from canopy.serve import live, secret, server, views
from canopy.serve import mock as serve_mock
from canopy.serve import options as serve_options
from canopy.serve.__main__ import KEEP_ALIVE_SECONDS, main
from canopy.serve.api import session
from canopy.serve.app import create_app
from canopy.serve.auth import SESSION_SECONDS, Sessions
from canopy.serve.backend import Backend
from canopy.serve.guard import MAX_BODY_BYTES, host_name
from canopy.serve.mock import reviews as mock_reviews
from canopy.serve.options import ServeOptions
from canopy.serve.schema import TicketSummary
from canopy.serve.schema.event import (
    AttentionUpdated,
    ChoresUpdated,
    LoopUpdated,
    ReviewRequestsUpdated,
    ReviewsUpdated,
    RunsUpdated,
    SpendUpdated,
    StreamEnding,
    StreamEvent,
    TaskChanged,
    TasksUpdated,
    TicketChanged,
    TicketsUpdated,
    TickUpdated,
)
from canopy.serve.spa import content_security_policy
from canopy.serve.sse import QuietLeaving
from tests.canopy.helpers import granted_meanwhile, present
from tests.canopy.web_helpers import DEFAULT_CAPACITY, ORIGIN, SECRET, client, free_port, signed_in
from tests.conftest import Journals, invoke

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


def test_index_html_carries_the_build_meta_reports_and_a_rebuild_changes_it(ui: Path, backend: Backend) -> None:
    c = client(ui, backend)
    build = c.get("/api/meta").json()["build"]
    assert isinstance(build, str)
    assert f'<meta name="canopy-build" content="{build}" />' in c.get("/runs").text

    (ui / "index.html").write_text(INDEX.replace("abc123", "def456"))
    rebuilt = c.get("/api/meta").json()["build"]
    assert rebuilt != build
    assert f'content="{rebuilt}"' in c.get("/").text


def test_meta_reports_no_build_when_the_ui_is_not_built(tmp_path: Path, backend: Backend) -> None:
    assert client(None, backend).get("/api/meta").json()["build"] is None
    assert client(tmp_path, backend).get("/api/meta").json()["build"] is None


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


def test_the_schema_and_its_docs_page_are_served_under_the_api_behind_the_session(ui: Path, backend: Backend) -> None:
    c = client(ui, dataclasses.replace(backend, mock=False), key=SECRET, mock=False, base_path="/canopy")
    assert c.get("/canopy/api/docs").status_code == 401
    assert c.get("/canopy/api/openapi.json").status_code == 401
    signed_in(c, base="/canopy")
    page = c.get("/canopy/api/docs")
    assert page.status_code == 200
    # Swagger UI from the UI's build, never a CDN, and the inline script allowed by its hash alone.
    assert '<script src="/canopy/api-docs/swagger-ui-bundle.js">' in page.text
    assert '"openapi": "/canopy/api/openapi.json"' in page.text
    assert "http" not in page.text
    assert page.headers["content-security-policy"] == content_security_policy(page.text)
    assert "'sha256-" in page.headers["content-security-policy"]
    assert c.get("/canopy/api/openapi.json").json()["info"]["title"] == "canopy"
    assert c.get("/canopy/docs", follow_redirects=False).headers["location"] == "/canopy/api/docs"
    for path in ("/canopy/api/redoc", "/docs", "/openapi.json", "/docs/oauth2-redirect"):
        assert c.get(path).status_code == 404, path


def test_each_app_serves_its_own_backend_and_sessions(ui: Path, tmp_path: Path) -> None:
    # The routers are shared by every app in the process; what a route is handed is bound per app.
    first = client(ui, serve_mock.seed(tmp_path / "first"))
    second = client(ui, serve_mock.seed(tmp_path / "second"), key=SECRET, base_path="/canopy")
    assert second.get("/canopy/api/meta").status_code == 401
    headers = signed_in(second, base="/canopy")
    before = second.get("/canopy/api/loop", headers=headers).json()
    paused = first.post("/api/loop/pause", headers={"origin": ORIGIN}).json()
    assert paused["already"] is False
    assert first.get("/api/loop").json() == paused["loop"] != before
    assert second.get("/canopy/api/loop", headers=headers).json() == before


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


def test_a_body_too_large_is_refused_before_the_session_check(ui: Path, backend: Backend) -> None:
    # Not signed in: FastAPI would read the whole body before the session check refused it with a 401.
    c = client(ui, backend, key=SECRET)
    json_body = {"content-type": "application/json"}
    for path in ("/api/session", "/api/tickets/PROJ-1/replies"):
        big = c.post(path, content=b"x" * (MAX_BODY_BYTES + 1), headers=json_body)
        assert big.status_code == 413, path
        assert big.headers["x-frame-options"] == "DENY"
        chunked = c.post(path, content=iter([b'{"secret": "x"}']), headers=json_body)
        assert chunked.status_code == 411, path
    # The route is a signed-in one: a body within the limit gets as far as the session check.
    assert c.post("/api/tickets/PROJ-1/replies", json={"body": "hi", "submission": "abcdefgh"}).status_code == 401


def test_the_largest_reply_fits_the_body_limit(ui: Path, backend: Backend) -> None:
    c = client(ui, backend, key=SECRET)
    # The worst case: a character outside the BMP, which `ensure_ascii` escapes as a surrogate pair, 12 bytes.
    body = json.dumps({"body": "\U0001f600" * 20_000, "submission": "abcdefgh"}).encode()
    assert len(body) > 240_000
    assert len(body) <= MAX_BODY_BYTES
    response = c.post(
        "/api/tickets/PROJ-1/replies",
        content=body,
        headers={**signed_in(c), "content-type": "application/json"},
    )
    assert response.status_code not in {411, 413, 422}


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
    files = ("/api/runs/39", "/api/runs/39/transcript", "/api/runs/40/output", "/api/ticks/2/transcript")
    reviews = ("/api/reviews", "/api/reviews/4", "/api/reviews/4/transcript", "/api/reviews/4/output")
    chores = ("/api/chores/deps/runs/2", "/api/chores/deps/runs/2/transcript")
    for path in (*paths, *files, *reviews, *chores):
        assert c.get(path).status_code == 401, path
    assert c.post("/api/tickets/ABC-102/start", headers={"origin": ORIGIN}).status_code == 401


def test_a_wrong_secret_is_refused_slowly_and_sets_no_cookie(ui: Path, backend: Backend) -> None:
    with mock.patch.object(session, "FAILED_SIGN_IN_SECONDS", 0.2):
        c = client(ui, backend, key=SECRET)
        began = time.monotonic()
        response = c.post("/api/session", json={"secret": SECRET + "x"})
        assert response.status_code == 401
        assert time.monotonic() - began >= 0.2
        assert "set-cookie" not in response.headers
        assert c.post("/api/session", json={"secret": ""}).status_code == 422


def test_signing_in_sets_an_httponly_strict_cookie_named_for_the_port_and_scoped_to_the_base(
    ui: Path,
    backend: Backend,
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


def test_a_write_that_waits_out_a_held_journal_is_a_503_saying_so(
    ui: Path,
    backend: Backend,
    journals: Journals,
) -> None:
    c = client(ui, backend)
    url = "/api/tickets/ABC-102/replies"
    body = {"body": "red", "submission": "submission-1"}
    holder = journals.open(db_path(backend.workspace), migrate=False)
    holder.execute("BEGIN IMMEDIATE")
    handler = _Records()
    log = logging.getLogger("canopy")
    log.addHandler(handler)
    try:
        with mock.patch.object(db, "BUSY_SECONDS", 0.05):
            response = c.post(url, json=body, headers={"origin": ORIGIN})
            assert response.status_code == 503, response.text
            assert response.json() == {
                "detail": "the journal is busy: another writer held it for over 0.05s; try again",
            }
            assert c.get("/api/tickets").status_code == 200
            holder.execute("ROLLBACK")
            assert c.post(url, json=body, headers={"origin": ORIGIN}).status_code == 200
    finally:
        log.removeHandler(handler)
    warned = [r.getMessage() for r in handler.records if r.levelno >= logging.WARNING]
    # The audit cannot record the 503 either while the journal is held.
    assert warned == [
        f"journal busy: POST {url} waited 0.05s for the write lock",
        f"web UI write not recorded: POST {url}",
    ]


def test_any_other_operational_error_stays_a_500(ui: Path, backend: Backend) -> None:
    c = client(ui, backend)
    broken = sqlite3.OperationalError("no such table: tickets")
    with (
        mock.patch.object(Backend, "open", autospec=True, side_effect=broken),
        pytest.raises(sqlite3.OperationalError, match="no such table"),
    ):
        c.get("/api/tickets")


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
    signed = present(sessions.check(value))
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
    with serving(ui, backend) as port:
        yield port


@contextmanager
def serving(ui: Path, backend: Backend) -> Iterator[int]:
    """Serve the mock app until the block ends, then stop: uvicorn waits for every request to end first."""
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
        assert not thread.is_alive(), "the server did not stop"


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
    headers, events = read_events(served, 12)
    assert headers["content-type"].startswith("text/event-stream")
    assert headers["x-accel-buffering"] == "no"
    assert headers["cache-control"] == "no-cache"
    first, runs, tickets, chores, tasks_event, reviews, requested, spend, tick, loop, changed, spent = (
        e.root for e in events
    )
    assert isinstance(first, AttentionUpdated)
    assert isinstance(runs, RunsUpdated)
    assert isinstance(tickets, TicketsUpdated)
    assert isinstance(chores, ChoresUpdated)
    assert [c.name for c in chores.chores] == ["build-health", "deps"]
    assert isinstance(tasks_event, TasksUpdated)
    assert [t.id for t in tasks_event.tasks] == [7, 6, 5, 4, 3, 2, 1]
    assert isinstance(reviews, ReviewsUpdated)
    assert reviews.reviews
    assert isinstance(requested, ReviewRequestsUpdated)
    assert [r.pr_url for r in requested.requests] == [mock_reviews.PR_95]
    assert isinstance(spend, SpendUpdated)
    assert isinstance(tick, TickUpdated)
    assert tick.tick is not None
    assert (tick.tick.id, tick.tick.status, tick.acknowledged) == (2, "ok", 8)
    assert isinstance(loop, LoopUpdated)
    assert loop.paused is None
    # The mock journal moves the running run's cost: only the runs list and the spend are sent again.
    assert isinstance(changed, RunsUpdated)
    before = next(r for r in runs.runs if r.id == serve_mock.LIVE_RUN)
    after = next(r for r in changed.runs if r.id == serve_mock.LIVE_RUN)
    assert after.cost_usd is not None
    assert before.cost_usd is not None
    assert after.cost_usd > before.cost_usd
    assert isinstance(spent, SpendUpdated)
    assert (spent.spend.day.hours, spent.spend.month.hours) == (24, 720)
    for was, now in ((spend.spend.day, spent.spend.day), (spend.spend.month, spent.spend.month)):
        assert now.cost_usd is not None
        assert was.cost_usd is not None
        assert now.cost_usd == pytest.approx(was.cost_usd + after.cost_usd - before.cost_usd)
    assert spend.spend.total_usd is not None
    assert spent.spend.total_usd == pytest.approx(spend.spend.total_usd + after.cost_usd - before.cost_usd)


def test_the_mock_journal_waits_for_a_held_lock_off_the_event_loop(backend: Backend, journals: Journals) -> None:
    holder = journals.open(db_path(backend.workspace), migrate=False)

    def cost() -> float:
        return float(holder.execute("SELECT cost_usd FROM runs WHERE id = ?", (serve_mock.LIVE_RUN,)).fetchone()[0])

    before = cost()

    async def hold() -> float:
        moving = asyncio.create_task(serve_mock.changes(backend, 0.01))
        holder.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        await asyncio.sleep(0.2)
        held = time.monotonic() - started
        holder.execute("ROLLBACK")
        async with asyncio.timeout(5):
            while cost() == before:  # noqa: ASYNC110  (the write is on another thread, with nothing to set an Event)
                await asyncio.sleep(0.01)
        moving.cancel()
        with suppress(asyncio.CancelledError):
            await moving
        return held

    # Blocking the loop, the write would hold up the sleep until its busy timeout ran out.
    with mock.patch.object(db, "BUSY_SECONDS", 2):
        held = asyncio.run(hold())
    assert held < 1
    assert cost() > before


@pytest.mark.parametrize(
    ("ref", "kind", "repo", "reads", "insert"),
    [
        (
            "ABC-100",
            "resume",
            "web",
            "_limits",
            "INSERT INTO attempt_grants (ticket_key, repo, kind, runs, granted_at) VALUES (?, 'web', 'resume', 1, ?)",
        ),
        (
            "https://github.com/acme/web/pull/88",
            "review",
            None,
            "_review_limit",
            "INSERT INTO review_grants (pr_url, runs, granted_at) VALUES (?, 1, ?)",
        ),
    ],
)
def test_a_grant_on_the_mock_reports_the_limit_of_its_own_transaction(
    backend: Backend,
    ref: str,
    kind: str,
    repo: str | None,
    reads: str,
    insert: str,
) -> None:
    with backend.open() as ctx:
        before = backend.review_limit(ctx, ref) if repo is None else backend.limits(ctx, ref)[1]
        # No other grant commits between this one's read of its limit and its insert (#341).
        with granted_meanwhile(ctx.conn, serve_mock, reads, insert, ref, db.now()) as tried:
            granted = backend.grant(ctx, conversation.parse_ref(ref), kind, repo)
        assert tried == ["locked"]
        assert (granted.repo, granted.runs, granted.limit) == (repo, present(before).runs, present(before).limit + 1)


def test_a_stream_with_a_lifetime_ends_on_its_own_after_its_first_events(ui: Path, backend: Backend) -> None:
    # TestClient reads a stream to its end, so an endless one would hang here.
    response = client(ui, backend, stream_seconds=0.3).get("/api/events")
    assert response.status_code == 200
    events = [
        StreamEvent.model_validate_json(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert {type(e.root) for e in events} >= {AttentionUpdated, RunsUpdated, TicketsUpdated}
    assert isinstance(events[-1].root, StreamEnding)
    assert not any(isinstance(e.root, StreamEnding) for e in events[:-1])


def test_every_server_ends_its_streams_on_its_own(ui: Path, backend: Backend) -> None:
    # A forwarder can hold a stream open after its page has gone (#1299): only the lifetime ends it then.
    with mock.patch.object(serve_options, "STREAM_SECONDS", 0.3):
        response = client(ui, backend).get("/api/events")
    assert response.text.rstrip().endswith('data: {"type":"stream.ending"}')


def test_the_stream_reads_every_list_from_one_snapshot(backend: Backend) -> None:
    recent = db.recent_tickets
    replied: list[bool] = []

    def then_a_reply(conn: sqlite3.Connection, limit: int, *, key: str | None = None) -> list[sqlite3.Row]:
        rows = recent(conn, limit, key=key)
        if not replied:
            replied.append(True)
            with backend.open() as other:
                other.conn.execute(
                    "INSERT INTO messages (subject_kind, subject_id, at, source, kind, channel, body) "
                    "VALUES ('ticket', 'ABC-103', '2026-10-08T13:00:00.000Z', 'operator', 'reply', 'cli', 'later')",
                )
        return rows

    with backend.open() as ctx:
        sent = live._Sent()  # noqa: SLF001  (the stream's own record of what it sent)
        sent.changes(backend, ctx)
        with mock.patch.object(db, "recent_tickets", autospec=True, side_effect=then_a_reply):
            # The reply commits after the tickets' order is read: the rest of this read does not see it either, so no
            # ticket's summary changes beside an order from before it.
            assert sent.changes(backend, ctx) == []
            assert replied == [True]
            # The next read sees it whole: the order and the summary.
            events = [e.root for e in sent.changes(backend, ctx)]
    [tickets] = [e for e in events if isinstance(e, TicketsUpdated)]
    assert tickets.tickets[0].key == "ABC-103"
    assert [e.key for e in events if isinstance(e, TicketChanged)] == ["ABC-103"]


def test_a_task_submitted_sends_the_tasks_again(backend: Backend) -> None:
    with backend.open() as ctx:
        sent = live._Sent()  # noqa: SLF001  (the stream's own record of what it sent)
        sent.changes(backend, ctx)
        task = tasks.submit(ctx.conn, ctx.workspace, "Tidy the README.", repo="web", project=None, channel="cli")
        events = [e.root for e in sent.changes(backend, ctx)]
    [tasks_event] = [e for e in events if isinstance(e, TasksUpdated)]
    assert [(t.id, t.standing) for t in tasks_event.tasks[:1]] == [(task.id, "queued")]


def test_a_message_about_a_task_names_the_task_though_its_summary_holds(backend: Backend) -> None:
    with backend.open() as ctx:
        task = tasks.submit(ctx.conn, ctx.workspace, "Tidy the README.", repo="web", project=None, channel="cli")
        sent = live._Sent()  # noqa: SLF001  (the stream's own record of what it sent)
        first = [e.root for e in sent.changes(backend, ctx)]
        # A reply while its run still runs queues nothing: the list is as it was, but its page shows the reply.
        ctx.conn.execute(
            "INSERT INTO messages (subject_kind, subject_id, at, source, kind, channel, body) "
            "VALUES ('task', ?, '2026-10-08T13:00:00.000Z', 'operator', 'reply', 'cli', 'later')",
            (str(task.id),),
        )
        events = [e.root for e in sent.changes(backend, ctx)]
    # The first read names no task: there was nothing sent before it to differ from.
    assert not any(isinstance(e, TaskChanged) for e in first)
    assert not any(isinstance(e, TasksUpdated) for e in events)
    assert [e.id for e in events if isinstance(e, TaskChanged)] == [task.id]


def test_a_review_run_starting_sends_the_reviews_again(backend: Backend, tmp_path: Path) -> None:
    with backend.open() as ctx:
        sent = live._Sent()  # noqa: SLF001  (the stream's own record of what it sent)
        sent.changes(backend, ctx)
        run_id = review_runs.insert_review_run(
            ctx.conn,
            tick_id=1,
            pr_url="https://github.com/acme/web/pull/91",
            sha="abc1234",
            ticket="ABC-103",
            repo="web",
            purpose="own",
            logs_dir=tmp_path,
        )
        events = [e.root for e in sent.changes(backend, ctx)]
    [reviewed] = [e for e in events if isinstance(e, ReviewsUpdated)]
    assert (reviewed.reviews[0].id, reviewed.reviews[0].state) == (run_id, "running")


def test_a_review_of_a_requested_pr_starting_takes_it_off_the_requests_waiting(
    backend: Backend,
    tmp_path: Path,
) -> None:
    with backend.open() as ctx:
        sent = live._Sent()  # noqa: SLF001  (the stream's own record of what it sent)
        sent.changes(backend, ctx)
        review_runs.insert_review_run(
            ctx.conn,
            tick_id=1,
            pr_url=mock_reviews.PR_95,
            sha="abc1234",
            ticket=None,
            repo="web",
            purpose="request",
            logs_dir=tmp_path,
        )
        events = [e.root for e in sent.changes(backend, ctx)]
    [requested] = [e for e in events if isinstance(e, ReviewRequestsUpdated)]
    assert requested.requests == []


def test_a_budget_changed_sends_the_spend_again_though_no_cost_did(backend: Backend) -> None:
    with backend.open() as ctx:
        sent = live._Sent()  # noqa: SLF001  (the stream's own record of what it sent)
        sent.changes(backend, ctx)
        # Read again on the same journal, no cost has moved: nothing about the spend is sent.
        assert not any(isinstance(e.root, SpendUpdated) for e in sent.changes(backend, ctx))
        raised = ctx.config.model_copy(update={"spend": ctx.config.spend.model_copy(update={"monthly_budget_usd": 80})})
        events = [e.root for e in sent.changes(backend, dataclasses.replace(ctx, config=raised))]
    [spent] = [e for e in events if isinstance(e, SpendUpdated)]
    assert spent.spend.budget is not None
    assert spent.spend.budget.budget_usd == 80


def test_the_stream_sends_the_chores_again_when_the_loop_reads_its_config_again(backend: Backend) -> None:
    async def first_and_after_a_reload() -> tuple[list[StreamEvent], StreamEvent]:
        with closing(live.Stream(backend)) as opened:
            stream = opened.events(poll_seconds=0.01)
            first = [await anext(stream) for _ in range(10)]
            # A reload commits nothing to the journal: the stream sees it in the config it serves.
            chores = {k: v for k, v in backend.config.chores.items() if k == "deps"}
            backend.use(backend.config.model_copy(update={"chores": chores}), backend.workspace)
            after = await asyncio.wait_for(anext(stream), timeout=5)
        return first, after

    first, after = asyncio.run(first_and_after_a_reload())
    [before] = [e.root for e in first if isinstance(e.root, ChoresUpdated)]
    assert [c.name for c in before.chores] == ["build-health", "deps"]
    assert isinstance(after.root, ChoresUpdated)
    assert [c.name for c in after.root.chores] == ["deps"]


def test_a_change_to_a_ticket_sends_the_list_and_names_the_ticket(served: int, backend: Backend) -> None:
    found: list[StreamEvent] = []
    replied = False
    with httpx2.stream("GET", f"http://127.0.0.1:{served}/api/events", timeout=10) as response:
        for line in response.iter_lines():
            if line.startswith("data: "):
                found.append(StreamEvent.model_validate_json(line.removeprefix("data: ")))
            # The reply goes in once the first list has been sent, not after a fixed wait: a reply the first read
            # already saw would change nothing the stream sent, and no TicketChanged would ever come.
            if not replied and any(isinstance(e.root, TicketsUpdated) for e in found):
                replied = True
                with backend.open() as ctx:
                    ctx.conn.execute(
                        "INSERT INTO messages (subject_kind, subject_id, at, source, kind, channel, body) "
                        "VALUES ('ticket', 'ABC-103', '2026-10-08T13:00:00.000Z', 'operator', 'reply', 'cli', 'later')",
                    )
            if any(isinstance(e.root, TicketChanged) for e in found):
                break
    changed = next(e.root for e in found if isinstance(e.root, TicketChanged))
    assert changed.key == "ABC-103"
    lists = [e.root for e in found if isinstance(e.root, TicketsUpdated)]
    assert len(lists) == 2
    assert lists[1].tickets[0].key == "ABC-103"


def test_a_stream_dropped_during_its_first_events_closes_its_connection(served: int) -> None:
    """Issue 337: a client gone while the first events were still being sent left its journal connection open."""
    real = Backend.open
    opened: list[Context] = []
    closed: list[Context] = []

    @contextmanager
    def counted(self: Backend) -> Iterator[Context]:
        # The mock's writer and the other requests open connections of their own: only the streams' are counted.
        stream = threading.current_thread().name.startswith("canopy-stream")
        with real(self) as ctx:
            if stream:
                opened.append(ctx)
            yield ctx
        # Not reached when closing the connection raised, as it did off the thread that opened it.
        if stream:
            closed.append(ctx)

    with (
        mock.patch.object(Backend, "open", autospec=True, side_effect=counted),
        mock.patch.object(live._Reader, "read", autospec=True, side_effect=a_long_burst),  # noqa: SLF001
    ):
        for _ in range(10):
            read_events(served, 1)
        deadline = time.monotonic() + 10
        while len(closed) < len(opened) and time.monotonic() < deadline:
            time.sleep(0.05)
    assert len(opened) == 10
    assert len(closed) == 10


def test_a_client_leaving_a_stream_mid_send_logs_no_error(ui: Path, backend: Backend) -> None:
    """Issue 338: FastAPI's SSE teardown raises when a client leaves while it sends, and uvicorn logged it as an error.

    With a long burst, the client always leaves while the task feeding the stream waits to send, which is when FastAPI
    raises `BrokenResourceError`: without `sse.QuietLeaving`, every stream here logs `Exception in ASGI application`.
    """
    errors = _Records()
    uvicorn_log = logging.getLogger("uvicorn.error")
    with mock.patch.object(live._Reader, "read", autospec=True, side_effect=a_long_burst):  # noqa: SLF001
        try:
            # Added once serving, since uvicorn's config replaces its loggers' handlers, and kept until the server has
            # stopped, which waits for every stream's teardown.
            with serving(ui, backend) as port:
                uvicorn_log.addHandler(errors)
                for _ in range(10):
                    read_events(port, 1)
        finally:
            uvicorn_log.removeHandler(errors)
    assert [r.getMessage() for r in errors.records if r.levelno >= logging.ERROR] == []


def test_the_loop_stopping_its_server_with_a_stream_open_logs_the_cancel_as_info(ui: Path, backend: Backend) -> None:
    """Uvicorn cancels a request still open once the grace period ends, and logs its `CancelledError` as an exception.

    It would land in canopy.log, at ERROR with a traceback, for a tab left open when the loop stopped.
    """
    options = ServeOptions(ui_dir=ui, mock=True, mock_event_seconds=0.05, port=free_port())
    sessions = Sessions(None, port=options.port, base_path="", hosts=options.hosts)
    web = server.WebServer(create_app(options, backend, sessions), options, logs.for_tick(None))
    handler = _Records()
    canopy_log = logging.getLogger("canopy")
    opened = threading.Event()

    def holds_a_stream() -> None:
        with (
            suppress(httpx2.RemoteProtocolError),
            httpx2.stream("GET", f"http://127.0.0.1:{options.port}/api/events", timeout=10) as response,
        ):
            for _ in response.iter_lines():
                opened.set()

    client_thread = threading.Thread(target=holds_a_stream, daemon=True)
    canopy_log.addHandler(handler)
    try:
        with mock.patch.object(server, "GRACEFUL_SECONDS", 0.1):
            web.start()
            try:
                deadline = time.monotonic() + 10
                while not web.started and time.monotonic() < deadline:
                    time.sleep(0.01)
                client_thread.start()
                assert opened.wait(10), "the stream never opened"
            finally:
                web.stop()
                if client_thread.is_alive():
                    client_thread.join(10)
    finally:
        canopy_log.removeHandler(handler)
    assert not [r for r in handler.records if r.exc_info and isinstance(r.exc_info[1], asyncio.CancelledError)]
    [cancelled] = [r for r in handler.records if r.getMessage() == "web UI request cancelled as the server stopped"]
    assert cancelled.levelno == logging.INFO


_SHUTDOWN_CANCEL = "Task cancelled, timeout graceful shutdown exceeded"


def _while_handling(error: BaseException, handled: BaseException) -> BaseException:
    """`error`, as Python leaves it when raised in an `except` block that caught `handled`."""
    error.__context__ = handled
    return error


@pytest.mark.parametrize(
    ("error", "level"),
    [
        pytest.param(asyncio.CancelledError(_SHUTDOWN_CANCEL), logging.INFO, id="shutdown"),
        pytest.param(
            _while_handling(asyncio.CancelledError(), asyncio.CancelledError(_SHUTDOWN_CANCEL)),
            logging.INFO,
            id="raised by a task group while handling the shutdown",
        ),
        pytest.param(asyncio.CancelledError(), logging.ERROR, id="cancelled by the app"),
        pytest.param(
            _while_handling(asyncio.CancelledError(), asyncio.CancelledError("by the app")),
            logging.ERROR,
            id="cancelled by the app while handling another cancel",
        ),
        pytest.param(
            _while_handling(ValueError(), asyncio.CancelledError(_SHUTDOWN_CANCEL)),
            logging.ERROR,
            id="an error raised while handling the shutdown",
        ),
        pytest.param(
            ValueError(_SHUTDOWN_CANCEL),
            logging.ERROR,
            id="not a cancel",
        ),
    ],
)
def test_only_uvicorns_cancel_at_shutdown_reaches_canopy_log_at_info(error: BaseException, level: int) -> None:
    """Any other exception, a `CancelledError` the app raises itself among them, keeps its level and traceback."""
    handler = _Records()
    canopy_log = logging.getLogger("canopy")
    record = logging.LogRecord("uvicorn.error", logging.ERROR, __file__, 1, "Exception in ASGI application\n", (), None)
    record.exc_info = (type(error), error, None)
    canopy_log.addHandler(handler)
    try:
        server._ToCanopyLog().emit(record)  # noqa: SLF001  (the handler uvicorn's records reach canopy's log through)
    finally:
        canopy_log.removeHandler(handler)
    [handed] = handler.records
    assert handed.levelno == level
    assert (handed.exc_info is None) == (level == logging.INFO)


_READ = live._Reader.read  # noqa: SLF001  (the stream's reads, on its own thread)


def a_long_burst(reader: live._Reader) -> list[StreamEvent]:
    """A stream's read, with each burst ending in more events than the server sends before it sees its client gone.

    So the task reading them is always waiting to send one when the client leaves, never inside the generator, where a
    cancel would have finished it.
    """
    events = _READ(reader)
    return events + [StreamEvent(LoopUpdated(capacity=DEFAULT_CAPACITY, paused=None))] * 2000 if events else events


def _teardown() -> ExceptionGroup[anyio.BrokenResourceError]:
    return ExceptionGroup("unhandled errors in a TaskGroup", [anyio.BrokenResourceError()])


@pytest.mark.parametrize(
    ("content_type", "left", "error", "absorbed"),
    [
        pytest.param("text/event-stream", True, _teardown(), True, id="a stream's teardown after its client left"),
        pytest.param("text/event-stream", True, anyio.BrokenResourceError(), True, id="the same error, ungrouped"),
        pytest.param("text/event-stream", False, _teardown(), False, id="the client is still there"),
        pytest.param("application/json", True, _teardown(), False, id="not an event stream"),
        pytest.param(
            "text/event-stream",
            True,
            ExceptionGroup("unhandled errors in a TaskGroup", [anyio.BrokenResourceError(), ValueError("a real one")]),
            False,
            id="with a real failure beside it",
        ),
    ],
)
def test_quiet_leaving_absorbs_only_a_streams_teardown_once_its_client_left(
    content_type: str,
    left: bool,  # noqa: FBT001  (a parameter)
    error: BaseException,
    absorbed: bool,  # noqa: FBT001  (a parameter)
) -> None:
    """Anything else is raised as it came: the same exception, so its traceback and context are untouched."""

    async def app(_scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {"type": "http.response.start", "status": 200, "headers": [(b"content-type", content_type.encode())]},
        )
        await receive()
        raise error

    async def receive() -> Message:
        return {"type": "http.disconnect"} if left else {"type": "http.request", "body": b"", "more_body": True}

    async def send(_message: Message) -> None:
        pass

    run = QuietLeaving(app)({"type": "http"}, receive, send)
    if absorbed:
        asyncio.run(run)
        return
    with pytest.raises(type(error)) as raised:
        asyncio.run(run)
    assert raised.value is error


def test_a_stream_that_cannot_close_its_connection_logs_why(backend: Backend) -> None:
    """Nothing waits on the close, queued on the stream's thread: an error in it is logged, not lost."""
    handler = _Records()
    records = handler.records
    log = logging.getLogger("canopy")
    log.addHandler(handler)
    close = live._Reader.close  # noqa: SLF001  (closes the stream's connection, on its own thread)

    def closes_then_fails(self: live._Reader) -> None:
        close(self)
        raise sqlite3.ProgrammingError("closed on the wrong thread")

    try:
        with mock.patch.object(live._Reader, "close", autospec=True, side_effect=closes_then_fails):  # noqa: SLF001
            asyncio.run(read_once_and_close(backend))
        deadline = time.monotonic() + 5
        while not records and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        log.removeHandler(handler)
    [record] = records
    assert record.levelno == logging.ERROR
    assert record.error == "ProgrammingError: closed on the wrong thread"  # pyrefly: ignore[missing-attribute]


def test_a_stream_closed_before_its_first_read_has_nothing_to_close(backend: Backend) -> None:
    """A request torn down before its stream read anything queues no close, and a second close does nothing."""
    with mock.patch.object(live._Reader, "close", autospec=True) as close:  # noqa: SLF001
        stream = live.Stream(backend)
        stream.close()
        stream.close()
    close.assert_not_called()


async def read_once_and_close(backend: Backend) -> None:
    with closing(live.Stream(backend)) as stream:
        events = stream.events()
        await anext(events)
        await events.aclose()  # pyrefly: ignore[missing-attribute]


class _Records(logging.Handler):
    """Keeps the records it is handed."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    @override
    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_a_streams_read_never_holds_up_a_request(served: int) -> None:
    """A stream reads the lists on a thread of its own: a request is answered while a read is still under way."""
    reading, answered = threading.Event(), threading.Event()
    tickets = views.tickets

    def slow(ctx: Context) -> list[TicketSummary]:
        reading.set()
        answered.wait(timeout=10)
        return tickets(ctx)

    with mock.patch.object(views, "tickets", autospec=True, side_effect=slow):
        stream = threading.Thread(target=read_events, args=(served, 1), daemon=True)
        stream.start()
        assert reading.wait(timeout=10)
        try:
            response = httpx2.get(f"http://127.0.0.1:{served}/api/loop", timeout=5)
        finally:
            answered.set()
        assert response.status_code == 200
        stream.join(timeout=10)
        assert not stream.is_alive()


# The development server and the schema


def test_the_mock_journal_covers_every_run_state_and_message_source(ui: Path, backend: Backend) -> None:
    c = client(ui, backend)
    assert {r["state"] for r in c.get("/api/runs").json()} == {"running", "blocked", "done", "failed"}
    sources = {
        m["source"]
        for key in ("ABC-101", "ABC-102", "ABC-103")
        for m in c.get(f"/api/tickets/{key}").json()["messages"]
    }
    assert sources == {"worker", "operator", "tracker", "canopy"}


def test_the_development_server_serves_mock_data_only() -> None:
    unseeded = invoke(main, ["serve"])
    assert unseeded.exit_code == 2
    assert "--mock" in unseeded.stderr
    public = invoke(main, ["serve", "--mock", "--host", "10.0.0.5"])
    assert public.exit_code == 2
    assert "loopback" in public.stderr


def test_the_development_server_keeps_an_idle_connection_past_any_test(ui: Path) -> None:
    """The e2e tests' request contexts reuse a connection idle for 5 s, uvicorn's default, and read ECONNRESET."""
    with mock.patch.object(uvicorn, "run", autospec=True) as run:
        assert invoke(main, ["serve", "--mock", "--ui-dir", str(ui)]).exit_code == 0
    assert run.call_args.kwargs["timeout_keep_alive"] == KEEP_ALIVE_SECONDS
    # Past Playwright's 30 s test timeout, so no connection a test opens idles out while the test runs.
    assert KEEP_ALIVE_SECONDS > 30


def test_openapi_names_the_stream_event_and_every_route() -> None:
    schema = json.loads(invoke(main, ["openapi"]).stdout)
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
        "ChoreRunDetail",
        "TickDetail",
        "Decision",
        "Transcript",
        "TranscriptStatus",
        "SearchResults",
        "SearchHit",
        "LoopState",
        "Pause",
        "PauseChanged",
        "WorkerNotice",
        "NoticeRequest",
        "NoticeChanged",
        "ConfigReload",
    }
    assert names <= set(schema["components"]["schemas"])
    paths = {
        "/api/session",
        "/api/meta",
        "/api/attention",
        "/api/runs",
        "/api/runs/since",
        "/api/runs/{run_id}",
        "/api/runs/{run_id}/transcript",
        "/api/runs/{run_id}/output",
        "/api/runs/{run_id}/answers",
        "/api/runs/{run_id}/memory",
        "/api/memory",
        "/api/memory/search",
        "/api/memory/{memory_id}/promote",
        "/api/memory/{memory_id}/reject",
        "/api/memory/{memory_id}/renew",
        "/api/memory/{memory_id}/pin",
        "/api/memory/{memory_id}/unpin",
        "/api/memory/{memory_id}/edit",
        "/api/memory/{memory_id}/history",
        "/api/memory/{memory_id}/forget",
        "/api/tickets/{key}/memory",
        "/api/spend",
        "/api/spend/breakdown",
        "/api/reports/monthly",
        "/api/reports/checklist",
        "/api/reports/health",
        "/api/tick",
        "/api/tickets",
        "/api/tickets/{key}",
        "/api/tickets/{key}/start",
        "/api/tickets/{key}/stop",
        "/api/tickets/{key}/replies",
        "/api/tickets/{key}/forget",
        "/api/tickets/{key}/grants",
        "/api/tickets/{key}/personas",
        "/api/tickets/{key}/models",
        "/api/tickets/{key}/plans",
        "/api/tickets/{key}/plans/{plan_id}",
        "/api/tickets/{key}/plan",
        "/api/tickets/{key}/feedback-plan",
        "/api/tickets/{key}/plans/{plan_id}/file",
        "/api/tickets/{key}/plan-threads",
        "/api/tickets/{key}/plan-threads/{thread_id}",
        "/api/tickets/{key}/plan-threads/{thread_id}/replies",
        "/api/chores",
        "/api/chores/{name}",
        "/api/chores/{name}/replies",
        "/api/chores/{name}/dismissals",
        "/api/chores/{name}/tries",
        "/api/chores/{name}/runs/{run_id}",
        "/api/chores/{name}/runs/{run_id}/transcript",
        "/api/tasks",
        "/api/tasks/{task_id}",
        "/api/tasks/{task_id}/replies",
        "/api/tasks/{task_id}/stop",
        "/api/tasks/{task_id}/runs/{run_id}",
        "/api/tasks/{task_id}/runs/{run_id}/transcript",
        "/api/tasks/{task_id}/runs/{run_id}/report",
        "/api/tickets/{key}/attachments/{name}",
        "/api/tasks/{task_id}/attachments/{name}",
        "/api/ticks",
        "/api/ticks/{tick_id}",
        "/api/ticks/{tick_id}/transcript",
        "/api/ticks/{tick_id}/output",
        "/api/worktrees",
        "/api/host",
        "/api/host/samples",
        "/api/host/processes",
        "/api/search",
        "/api/events",
        "/api/loop",
        "/api/reviews",
        "/api/review-requests",
        "/api/reviews/{run_id}",
        "/api/reviews/{run_id}/transcript",
        "/api/reviews/{run_id}/output",
        "/api/reviews/{run_id}/answers",
        "/api/reviews/{run_id}/dismissals",
        "/api/reviews/{run_id}/sends",
        "/api/reviews/{run_id}/draft/body",
        "/api/reviews/{run_id}/draft/comments",
        "/api/reviews/{run_id}/draft/comments/{number}/edit",
        "/api/reviews/{run_id}/draft/comments/{number}/drop",
        "/api/reviews/{run_id}/draft/notes",
        "/api/reviews/{run_id}/draft/publish",
        "/api/reviews/{run_id}/draft/discard",
        "/api/seen",
        "/api/pull-requests",
        "/api/pull-request",
        "/api/pull-request/grants",
        "/api/pull-request/start",
        "/api/pull-request/stop",
        "/api/pull-request/threads",
        "/api/personas",
        "/api/models",
        "/api/skills",
        "/api/runs/{run_id}/drafts/{number}/edit",
        "/api/runs/{run_id}/drafts/{number}/drop",
        "/api/drafts/send",
        "/api/drafts/stage",
        "/api/loop/pause",
        "/api/loop/resume",
        "/api/loop/notice",
        "/api/loop/notice/clear",
        "/api/loop/reload",
        "/api/loop/tick",
        "/api/config",
        "/api/config/models",
    }
    assert set(schema["paths"]) == paths


def test_openapi_describes_every_route_parameter_error_and_field() -> None:
    schema = json.loads(invoke(main, ["openapi"]).stdout)
    assert schema["info"]["version"] == version("canopy")
    assert schema["info"]["description"]
    tags = {t["name"] for t in schema["tags"] if t["description"]}
    assert len(tags) == len(schema["tags"])
    used: set[str] = set()
    operation_ids: list[str] = []
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            where = f"{method.upper()} {path}"
            operation_ids.append(operation["operationId"])
            assert operation["summary"], where
            assert operation["description"], where
            [tag] = operation["tags"]
            assert tag in tags, where
            used.add(tag)
            assert all(p["description"] for p in operation.get("parameters", [])), where
            responses = operation["responses"]
            # Every error names the shape of its body.
            assert all("content" in r for code, r in responses.items() if code != "200"), where
            assert "403" in responses, where
            if path != "/api/session":
                assert "401" in responses, where
            assert ("503" in responses) == (path not in {"/api/session", "/api/events"}), where
            if "{key}" in path or "{name}" in path:
                assert "409" in responses, where
            if path.endswith(("_id}", "{key}", "{name}")) and method == "get":
                assert "404" in responses, where
    assert used == tags
    assert len(set(operation_ids)) == len(operation_ids)
    assert all(re.fullmatch(r"[a-z]+(?:[A-Z][a-z]+)*", o) for o in operation_ids), operation_ids
    fastapis = {"HTTPValidationError", "ValidationError"}
    for name, model in schema["components"]["schemas"].items():
        if name in fastapis:
            continue
        assert model.get("description"), name
        undescribed = [field for field, s in model.get("properties", {}).items() if not s.get("description")]
        assert not undescribed, name
