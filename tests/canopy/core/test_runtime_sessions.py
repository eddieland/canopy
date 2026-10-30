"""Every session the agent runtime keeps, canopy's and not, as the journal records it."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

from canopy.core import db, records, runtime_sessions
from canopy.core.vocab import SessionsRead
from canopy.runtime import sessions
from canopy.runtime.implementation import Version
from canopy.runtime.report import ModelUse, SessionPage, SessionSpend

if TYPE_CHECKING:
    import sqlite3

#: 2026-10-24T12:00:00Z, in milliseconds since the epoch.
NOON_MS = 1_792_843_200_000
DAY = ("2026-10-24T00:00:00.000Z", "2026-10-25T00:00:00.000Z")
#: The workspace's state directory, where its chores run by default.
STATE_DIR = Path("/work/.canopy")


def session(
    session_id: str,
    *,
    cost: float = 0.5,
    updated_ms: int = NOON_MS,
    created_ms: int = NOON_MS,
    parent: str | None = None,
    directory: str = "/work/api",
    models: tuple[ModelUse, ...] = (),
) -> SessionSpend:
    """A session as the runtime reports it."""
    return SessionSpend(
        session_id=session_id,
        parent_id=parent,
        directory=directory,
        created_ms=created_ms,
        updated_ms=updated_ms,
        cost_usd=cost,
        input=1,
        output=2,
        reasoning=3,
        cache_read=4,
        cache_write=5,
        models=models,
    )


def found(*spent: SessionSpend, skipped: int = 0) -> SessionPage:
    """A page the runtime returns, its cursor after the last session in it."""
    last = spent[-1]
    return SessionPage("found", spent, cursor=(last.updated_ms, last.session_id), skipped=skipped)


def ran_in(conn: sqlite3.Connection, session_id: str) -> None:
    """Record a tick whose overseer ran in session `session_id`."""
    tick_id = db.start_tick(conn, dry_run=False)
    records.update(records.Tick).set(session_id=session_id).where("id = ?", tick_id).run(conn)


def test_a_page_is_recorded_with_each_sessions_models_and_the_cursor_after_it(conn: sqlite3.Connection) -> None:
    opus = ModelUse("anthropic/claude-opus", 3, 0.5)
    runtime_sessions.record(conn, found(session("ses_1", models=(opus,)), session("ses_2", updated_ms=NOON_MS + 1)))

    row = runtime_sessions.of_session(conn, "ses_1")
    assert row is not None
    assert (row.started_at, row.updated_ms, row.cost_usd, row.directory) == (
        "2026-10-24T12:00:00.000Z",
        NOON_MS,
        0.5,
        "/work/api",
    )
    assert (row.tokens_input, row.tokens_output, row.tokens_reasoning) == (1, 2, 3)
    assert (row.tokens_cache_read, row.tokens_cache_write) == (4, 5)
    assert [(m.model, m.replies, m.cost_usd) for m in runtime_sessions.models_of(conn, "ses_1")] == [
        ("anthropic/claude-opus", 3, 0.5),
    ]
    assert runtime_sessions.cursor(conn) == (NOON_MS + 1, "ses_2")


def test_a_session_read_again_replaces_its_row_and_models(conn: sqlite3.Connection) -> None:
    runtime_sessions.record(conn, found(session("ses_1", models=(ModelUse("a/x", 1, 0.5),))))
    runtime_sessions.record(conn, found(session("ses_1", cost=2.0, updated_ms=NOON_MS + 5, models=())))

    row = runtime_sessions.of_session(conn, "ses_1")
    assert row is not None
    assert (row.cost_usd, row.updated_ms) == (2.0, NOON_MS + 5)
    assert runtime_sessions.models_of(conn, "ses_1") == []


def test_a_read_that_fails_keeps_the_cursor_and_says_why(conn: sqlite3.Connection) -> None:
    runtime_sessions.record(conn, found(session("ses_1"), skipped=2))
    runtime_sessions.record(conn, SessionPage("failed", error="the record could not be read"))

    read = runtime_sessions.last_read(conn)
    assert read is not None
    assert (read.status, read.error, read.skipped) == (SessionsRead.FAILED, "the record could not be read", 2)
    assert runtime_sessions.cursor(conn) == (NOON_MS, "ses_1")


def test_read_next_starts_after_the_cursor(conn: sqlite3.Connection) -> None:
    runtime_sessions.record(conn, found(session("ses_1")))
    with mock.patch.object(sessions, "updated_after", autospec=True, return_value=found(session("ses_2"))) as read:
        page = runtime_sessions.read_next(conn, limit=10, version=Version.ONE)

    read.assert_called_once_with((NOON_MS, "ses_1"), version=Version.ONE, limit=10)
    assert [s.session_id for s in page.sessions] == ["ses_2"]
    assert runtime_sessions.cursor(conn) == (NOON_MS, "ses_2")


def test_spend_tells_canopys_sessions_and_their_subagents_from_the_rest(conn: sqlite3.Connection) -> None:
    ran_in(conn, "ses_overseer")
    runtime_sessions.record(
        conn,
        found(
            session("ses_overseer", cost=1.0),
            session("ses_sub", cost=0.25, parent="ses_overseer"),
            session("ses_subsub", cost=0.125, parent="ses_sub"),
            session("ses_mine", cost=2.0, directory="/home/me/notes"),
            session("ses_mine_sub", cost=0.5, parent="ses_mine", directory="/home/me/notes"),
            session("ses_other", cost=0.75, directory="/work/web"),
            session("ses_yesterday", cost=9.0, created_ms=NOON_MS - 86_400_000),
        ),
    )

    spent = runtime_sessions.spend(conn, *DAY, state_dir=STATE_DIR)

    assert spent.canopy == runtime_sessions.Share(sessions=3, cost_usd=1.375)
    assert spent.outside == runtime_sessions.Share(sessions=3, cost_usd=3.25)
    assert spent.directories == [
        runtime_sessions.DirectorySpend("/home/me/notes", 2, 2.5),
        runtime_sessions.DirectorySpend("/work/web", 1, 0.75),
    ]
    assert spent.status is SessionsRead.FOUND


def test_spend_counts_the_sessions_in_the_state_directory_as_canopys(conn: sqlite3.Connection) -> None:
    """A chore tried with --no-record runs in its own directory there, and no run of the journal names its session."""
    runtime_sessions.record(
        conn,
        found(
            session("ses_try", cost=1.0, directory="/work/.canopy/chores/build-health"),
            session("ses_try_sub", cost=0.25, parent="ses_try", directory="/home/me/notes"),
            session("ses_state", cost=0.5, directory="/work/.canopy"),
            session("ses_beside", cost=2.0, directory="/work/.canopy-old/chores/build-health"),
            session("ses_other", cost=0.75, directory="/other/.canopy/chores/build-health"),
        ),
    )

    spent = runtime_sessions.spend(conn, *DAY, state_dir=STATE_DIR)

    assert spent.canopy == runtime_sessions.Share(sessions=3, cost_usd=1.75)
    assert spent.outside == runtime_sessions.Share(sessions=2, cost_usd=2.75)


def test_spend_before_any_read_says_so(conn: sqlite3.Connection) -> None:
    spent = runtime_sessions.spend(conn, *DAY, state_dir=STATE_DIR)

    assert (spent.canopy.sessions, spent.outside.sessions, spent.read_at, spent.status) == (0, 0, None, None)
