"""The web UI's audit of write requests: what it records of a signed-in session's writes, and what it never keeps."""

import sqlite3
from unittest import mock

from fastapi.testclient import TestClient

from canopy.core import db, records, sql
from canopy.core.context import Context
from canopy.serve import audit
from canopy.serve.api import session
from canopy.serve.backend import Backend
from tests.canopy.web_helpers import ORIGIN, SECRET, client, signed_in, signed_in_client

KEY = "PROJ-1"


def writes(conn: sqlite3.Connection) -> list[records.WebWrite]:
    return records.fetch_all(conn, records.WebWrite, sql.frag("SELECT * FROM web_writes ORDER BY id"))


def test_a_sessions_writes_are_recorded_from_its_sign_in_with_their_paths_and_statuses(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    c.get("/api/session")
    c.post(f"/api/tickets/{KEY}/start", headers=headers)
    c.post(f"/api/tickets/{KEY}/stop", json={"now": False}, headers=headers)
    c.delete("/api/session", headers=headers)

    rows = writes(ctx.conn)
    assert [(w.method, w.path, w.code) for w in rows] == [
        ("POST", "/api/session", 200),
        ("POST", f"/api/tickets/{KEY}/start", 200),
        ("POST", f"/api/tickets/{KEY}/stop", 200),
        ("DELETE", "/api/session", 200),
    ]
    # The session it signed in is the one its writes carry, named by a fingerprint, never by its cookie or token.
    assert len({w.session for w in rows}) == 1
    session = rows[0].session
    assert session is not None
    assert len(session) == 16
    assert session not in c.cookies.values()
    assert session != headers["x-canopy-token"]
    assert {w.client for w in rows} == {"testclient"}
    assert all(db.parse_time(w.at) for w in rows)


def test_a_signed_in_write_any_guard_refuses_is_recorded(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    c.post(f"/api/tickets/{KEY}/stop", json={"now": False}, headers=headers)
    c.post(f"/api/tickets/{KEY}/start", headers={"origin": ORIGIN})
    c.post(f"/api/tickets/{KEY}/start", headers={**headers, "origin": "http://evil.test"})
    c.post("/api/nowhere", headers=headers)

    assert [(w.path, w.code) for w in writes(ctx.conn)[1:]] == [
        (f"/api/tickets/{KEY}/stop", 409),
        (f"/api/tickets/{KEY}/start", 403),
        (f"/api/tickets/{KEY}/start", 403),
        ("/api/nowhere", 405),
    ]


def test_a_write_without_a_session_and_a_read_are_not_recorded(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    stranger = TestClient(c.app, base_url=ORIGIN)
    with mock.patch.object(session, "FAILED_SIGN_IN_SECONDS", 0):
        assert stranger.post("/api/session", json={"secret": "x" * 40}).status_code == 401
    assert stranger.post(f"/api/tickets/{KEY}/start", headers=headers).status_code == 401
    c.get(f"/api/tickets/{KEY}")

    assert [w.path for w in writes(ctx.conn)] == ["/api/session"]


def test_a_writes_body_query_and_long_path_are_never_kept(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    c.post(f"/api/tickets/{KEY}/start", headers=headers)
    said = "Blue, to match the header."
    c.post(f"/api/tickets/{KEY}/replies?q=hidden", json={"body": said, "submission": "form-0001"}, headers=headers)
    c.post("/api/" + "x" * 1000, headers=headers)

    replied, long = writes(ctx.conn)[2:]
    assert (replied.path, replied.code) == (f"/api/tickets/{KEY}/replies", 200)
    kept = " ".join(str(v) for v in vars(replied).values())
    assert said not in kept
    assert "hidden" not in kept
    assert len(long.path) == audit.MAX_PATH


def test_the_mock_server_records_its_writes_with_no_session(backend: Backend) -> None:
    c = client(None, backend)
    c.post("/api/loop/pause", headers={"origin": ORIGIN})

    with backend.open() as ctx:
        [write] = writes(ctx.conn)
    assert (write.path, write.code, write.session) == ("/api/loop/pause", 200, None)


def test_a_write_the_journal_cannot_take_is_logged_and_still_answered(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)
    holder = sqlite3.connect(ctx.conn.execute("PRAGMA database_list").fetchone()["file"], autocommit=True)
    holder.execute("BEGIN IMMEDIATE")
    try:
        with mock.patch.object(db, "BUSY_SECONDS", 0.01), mock.patch.object(audit, "_log", autospec=True) as log:
            assert c.delete("/api/session", headers=headers).status_code == 200
    finally:
        holder.execute("ROLLBACK")
        holder.close()

    log.warning.assert_called_once()
    assert log.warning.call_args.args == ("web UI write not recorded: %s %s", "DELETE", "/api/session")
    assert log.warning.call_args.kwargs["extra"]["path"] == "/api/session"
    assert [w.method for w in writes(ctx.conn)] == ["POST"]


def test_a_second_sign_in_is_a_new_session(backend: Backend) -> None:
    c = client(None, backend, key=SECRET)
    signed_in(c)
    c.cookies.clear()
    signed_in(c)

    with backend.open() as ctx:
        first, second = writes(ctx.conn)
    assert first.session != second.session
