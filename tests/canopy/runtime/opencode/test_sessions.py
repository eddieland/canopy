"""What every OpenCode session cost, read from OpenCode 1.19.3's database."""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from typing import TYPE_CHECKING
from unittest import mock

from canopy.runtime.opencode import sessions
from canopy.runtime.report import ModelUse, SessionPage

if TYPE_CHECKING:
    from pathlib import Path

#: The columns of OpenCode 1.19.3's tables that the reader reads, and those it must fill to write a row.
SCHEMA = """
CREATE TABLE session (
    id text PRIMARY KEY, project_id text NOT NULL, parent_id text, slug text NOT NULL, directory text NOT NULL,
    title text NOT NULL, version text NOT NULL, cost real DEFAULT 0 NOT NULL,
    tokens_input integer DEFAULT 0 NOT NULL, tokens_output integer DEFAULT 0 NOT NULL,
    tokens_reasoning integer DEFAULT 0 NOT NULL, tokens_cache_read integer DEFAULT 0 NOT NULL,
    tokens_cache_write integer DEFAULT 0 NOT NULL, model text,
    time_created integer NOT NULL, time_updated integer NOT NULL
);
CREATE TABLE message (
    id text PRIMARY KEY, session_id text NOT NULL, time_created integer NOT NULL, time_updated integer NOT NULL,
    data text NOT NULL
);
CREATE TABLE account (id text PRIMARY KEY, access_token text NOT NULL);
"""


def database(tmp_path: Path) -> Path:
    """An empty database of OpenCode 1's tables, where OpenCode keeps it under `tmp_path` as `$XDG_DATA_HOME`."""
    path = tmp_path / "opencode" / "opencode.db"
    path.parent.mkdir(parents=True)
    with contextlib.closing(sqlite3.connect(path)) as conn:
        conn.executescript(SCHEMA)
    return path


def add_session(
    path: Path,
    session_id: str,
    *,
    updated: int,
    created: int = 1_000,
    cost: float = 0.0,
    parent: str | None = None,
    directory: str = "/work/api",
    tokens: tuple[int, int, int, int, int] = (0, 0, 0, 0, 0),
) -> None:
    """Write a session row as OpenCode does, its tokens as input, output, reasoning, cache read and write."""
    with contextlib.closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "INSERT INTO session VALUES (?, 'global', ?, 'slug', ?, 'a title', '1.19.3', ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
            (session_id, parent, directory, cost, *tokens, created, updated),
        )


def add_message(path: Path, message_id: str, session_id: str, data: dict[str, object] | str) -> None:
    """Write a message row as OpenCode does, its info as JSON."""
    with contextlib.closing(sqlite3.connect(path)) as conn, conn:
        text = data if isinstance(data, str) else json.dumps(data)
        conn.execute("INSERT INTO message VALUES (?, ?, 1, 1, ?)", (message_id, session_id, text))


def reply(provider: str, model: str, cost: float, *, variant: str | None = None) -> dict[str, object]:
    """An assistant message's info, as OpenCode keeps it; it leaves `variant` out for the model's default."""
    info: dict[str, object] = {"role": "assistant", "providerID": provider, "modelID": model, "cost": cost}
    if variant is not None:
        info["variant"] = variant
    return info


def read(tmp_path: Path, cursor: tuple[int, str] | None = None, *, limit: int = 500) -> SessionPage:
    """Read the sessions with `tmp_path` as `$XDG_DATA_HOME`."""
    with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(tmp_path)}):
        return sessions.updated_after(cursor, limit=limit)


def test_a_session_is_read_with_its_totals_and_each_models_cost(tmp_path: Path) -> None:
    path = database(tmp_path)
    add_session(path, "ses_1", updated=2_000, created=1_500, cost=0.75, tokens=(10, 20, 3, 400, 50))
    add_message(path, "msg_1", "ses_1", {"role": "user", "model": {"providerID": "anthropic", "modelID": "asked"}})
    add_message(path, "msg_2", "ses_1", reply("anthropic", "claude-opus", 0.5, variant="high"))
    add_message(path, "msg_3", "ses_1", reply("anthropic", "claude-opus", 0.125, variant="high"))
    add_message(path, "msg_4", "ses_1", reply("openai", "gpt-5", 0.125))

    page = read(tmp_path)

    assert page.outcome == "found"
    assert page.cursor == (2_000, "ses_1")
    [found] = page.sessions
    assert (found.session_id, found.parent_id, found.directory) == ("ses_1", None, "/work/api")
    assert (found.created_ms, found.updated_ms, found.cost_usd) == (1_500, 2_000, 0.75)
    assert (found.input, found.output, found.reasoning, found.cache_read, found.cache_write) == (10, 20, 3, 400, 50)
    assert found.models == (ModelUse("anthropic/claude-opus@high", 2, 0.625), ModelUse("openai/gpt-5", 1, 0.125))


def test_a_subagents_session_is_read_with_the_session_it_ran_for(tmp_path: Path) -> None:
    path = database(tmp_path)
    add_session(path, "ses_1", updated=2_000)
    add_session(path, "ses_2", updated=2_001, parent="ses_1", cost=1.25)

    page = read(tmp_path)

    assert [(s.session_id, s.parent_id, s.cost_usd) for s in page.sessions] == [
        ("ses_1", None, 0.0),
        ("ses_2", "ses_1", 1.25),
    ]


def test_sessions_are_read_a_page_at_a_time_in_the_order_of_their_update(tmp_path: Path) -> None:
    path = database(tmp_path)
    add_session(path, "ses_c", updated=3_000)
    add_session(path, "ses_b", updated=2_000)
    add_session(path, "ses_a", updated=2_000)

    first = read(tmp_path, limit=2)
    second = read(tmp_path, first.cursor, limit=2)
    third = read(tmp_path, second.cursor, limit=2)

    assert [s.session_id for s in first.sessions] == ["ses_a", "ses_b"]
    assert [s.session_id for s in second.sessions] == ["ses_c"]
    assert third == SessionPage("found", cursor=(3_000, "ses_c"))


def test_a_session_updated_since_the_cursor_is_read_again(tmp_path: Path) -> None:
    path = database(tmp_path)
    add_session(path, "ses_1", updated=2_000)
    cursor = read(tmp_path).cursor
    with contextlib.closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("UPDATE session SET time_updated = 2500, cost = 2 WHERE id = 'ses_1'")

    page = read(tmp_path, cursor)

    assert [(s.session_id, s.cost_usd) for s in page.sessions] == [("ses_1", 2.0)]


def test_a_row_canopy_cannot_read_is_passed_over_and_counted(tmp_path: Path) -> None:
    path = database(tmp_path)
    add_session(path, "ses_1", updated=2_000, cost=-1)
    add_session(path, "--not an id", updated=2_001)
    add_session(path, "ses_3", updated=2_002, parent="no such\nid")
    add_session(path, "ses_4", updated=2_003)

    page = read(tmp_path)

    assert [s.session_id for s in page.sessions] == ["ses_4"]
    assert (page.skipped, page.cursor) == (3, (2_003, "ses_4"))


def test_a_row_whose_update_or_id_is_mistyped_never_stops_the_reading(tmp_path: Path) -> None:
    path = database(tmp_path)
    add_session(path, "ses_1", updated=2_000)
    with contextlib.closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "INSERT INTO session (id, project_id, slug, directory, title, version, time_created, time_updated)"
            " VALUES ('ses_2', 'g', 's', '/d', 't', 'v', 1, 'soon')",
        )
        conn.execute(
            "INSERT INTO session (id, project_id, slug, directory, title, version, time_created, time_updated)"
            " VALUES (X'33', 'g', 's', '/d', 't', 'v', 1, 2001)",
        )

    first = read(tmp_path)
    add_session(path, "ses_4", updated=2_002)
    second = read(tmp_path, first.cursor)

    assert ([s.session_id for s in first.sessions], first.cursor) == (["ses_1"], (2_000, "ses_1"))
    assert [s.session_id for s in second.sessions] == ["ses_4"]


def test_a_reply_canopy_cannot_read_is_left_out_of_its_sessions_models(tmp_path: Path) -> None:
    path = database(tmp_path)
    add_session(path, "ses_1", updated=2_000)
    add_message(path, "msg_1", "ses_1", "not json")
    add_message(path, "msg_2", "ses_1", reply("anthropic", "claude-opus", 0.5) | {"cost": "a lot"})
    add_message(path, "msg_3", "ses_1", {"role": "assistant", "providerID": "anthropic", "cost": 1})
    add_message(path, "msg_4", "ses_1", reply("anthropic", "claude-opus", 0.5) | {"cost": -1})
    add_message(path, "msg_5", "ses_1", reply("anthropic", "claude-sonnet", 0.25))

    [found] = read(tmp_path).sessions

    assert found.models == (ModelUse("anthropic/claude-sonnet", 1, 0.25),)


def test_a_directory_is_kept_printable(tmp_path: Path) -> None:
    path = database(tmp_path)
    add_session(path, "ses_1", updated=2_000, directory="/work/\x1b[31mapi")

    [found] = read(tmp_path).sessions

    assert found.directory == "/work/[31mapi"


def test_no_database_is_missing(tmp_path: Path) -> None:
    assert read(tmp_path) == SessionPage("missing")


def test_a_database_without_opencode_1s_tables_fails(tmp_path: Path) -> None:
    path = tmp_path / "opencode" / "opencode.db"
    path.parent.mkdir()
    with contextlib.closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE session_v2 (id text)")

    page = read(tmp_path)

    assert page.outcome == "failed"
    assert page.error == "OpenCode's database could not be read: no such table: session"


def test_the_database_is_read_without_being_written(tmp_path: Path) -> None:
    path = database(tmp_path)
    add_session(path, "ses_1", updated=2_000)
    before = path.read_bytes()

    read(tmp_path)

    assert path.read_bytes() == before
    assert sorted(p.name for p in path.parent.iterdir()) == ["opencode.db"]


def test_the_database_is_under_the_users_data_directory(tmp_path: Path) -> None:
    with mock.patch.dict(os.environ, {"XDG_DATA_HOME": "", "HOME": str(tmp_path)}):
        assert sessions.database() == tmp_path / ".local" / "share" / "opencode" / "opencode.db"
    with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(tmp_path / "data")}):
        assert sessions.database() == tmp_path / "data" / "opencode" / "opencode.db"


def sandbox(tmp_path: Path, role: str) -> Path:
    """An empty database where a sandbox role's OpenCode keeps it, `tmp_path` being the operator's `$XDG_DATA_HOME`."""
    return database(tmp_path / "canopy" / "sandbox" / role)


def endless(path: Path) -> Path:
    """A database at `path` whose `session` is a view that never ends, as a run could write one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(sqlite3.connect(path)) as conn:
        conn.execute(
            "CREATE VIEW session AS WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n)"
            " SELECT 'ses_' || i AS id, NULL AS parent_id, '/d' AS directory, 1 AS time_created, i AS time_updated,"
            " 0 AS cost, 0 AS tokens_input, 0 AS tokens_output, 0 AS tokens_reasoning, 0 AS tokens_cache_read,"
            " 0 AS tokens_cache_write FROM n",
        )
    return path


def test_each_sandbox_roles_sessions_are_read_with_the_operators_in_the_order_of_their_update(tmp_path: Path) -> None:
    operators = database(tmp_path)
    add_session(operators, "ses_a", updated=1_000)
    add_session(operators, "ses_d", updated=4_000)
    worker = sandbox(tmp_path, "worker")
    add_session(worker, "ses_b", updated=2_000, cost=0.5)
    add_message(worker, "msg_1", "ses_b", reply("anthropic", "claude-opus", 0.5))
    add_session(sandbox(tmp_path, "review"), "ses_c", updated=3_000)

    first = read(tmp_path, limit=2)
    second = read(tmp_path, first.cursor, limit=2)

    assert ([s.session_id for s in first.sessions], first.cursor) == (["ses_a", "ses_b"], (2_000, "ses_b"))
    assert first.sessions[1].models == (ModelUse("anthropic/claude-opus", 1, 0.5),)
    assert ([s.session_id for s in second.sessions], second.cursor) == (["ses_c", "ses_d"], (4_000, "ses_d"))


def test_a_sandbox_roles_sessions_are_read_when_the_operator_has_no_database(tmp_path: Path) -> None:
    add_session(sandbox(tmp_path, "chore"), "ses_1", updated=2_000)

    assert [s.session_id for s in read(tmp_path).sessions] == ["ses_1"]


def test_a_sandbox_roles_database_canopy_cannot_read_is_passed_over(tmp_path: Path) -> None:
    """A run writes its role's database, so one it broke keeps only that role's sessions from being read."""
    add_session(database(tmp_path), "ses_1", updated=2_000)
    broken = tmp_path / "canopy" / "sandbox" / "review" / "opencode" / "opencode.db"
    broken.parent.mkdir(parents=True)
    broken.write_bytes(b"not a database")
    endless(tmp_path / "canopy" / "sandbox" / "worker" / "opencode" / "opencode.db")

    with mock.patch.object(sessions, "READ_SECONDS", 0.1):
        page = read(tmp_path)

    assert ([s.session_id for s in page.sessions], page.outcome) == (["ses_1"], "found")


def test_a_read_that_runs_too_long_is_stopped(tmp_path: Path) -> None:
    endless(tmp_path / "opencode" / "opencode.db")

    with mock.patch.object(sessions, "READ_SECONDS", 0.1):
        page = read(tmp_path)

    assert page == SessionPage("failed", error="OpenCode's database could not be read: interrupted")


def test_a_sandbox_roles_database_a_link_leads_out_of_its_directory_is_not_read(tmp_path: Path) -> None:
    elsewhere = database(tmp_path / "elsewhere")
    add_session(elsewhere, "ses_1", updated=2_000)
    role = tmp_path / "canopy" / "sandbox" / "worker"
    role.mkdir(parents=True)
    (role / "opencode").symlink_to(elsewhere.parent)

    assert read(tmp_path) == SessionPage("missing")
