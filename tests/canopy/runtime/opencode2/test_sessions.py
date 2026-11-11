"""What every OpenCode 2 session cost, read from OpenCode 2.1.4's database."""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from typing import TYPE_CHECKING
from unittest import mock

from canopy.runtime.opencode2 import sessions
from canopy.runtime.report import ModelUse

if TYPE_CHECKING:
    from pathlib import Path

#: The columns of OpenCode 2.1.4's tables that the reader reads, and those it must fill to write a row.
SCHEMA = """
CREATE TABLE session_v2 (
    id text PRIMARY KEY, project_id text NOT NULL, parent_id text, slug text NOT NULL, directory text NOT NULL,
    version text NOT NULL, cost real DEFAULT 0 NOT NULL,
    tokens_input integer DEFAULT 0 NOT NULL, tokens_output integer DEFAULT 0 NOT NULL,
    tokens_reasoning integer DEFAULT 0 NOT NULL, tokens_cache_read integer DEFAULT 0 NOT NULL,
    tokens_cache_write integer DEFAULT 0 NOT NULL, model text,
    time_created integer NOT NULL, time_updated integer NOT NULL
);
CREATE TABLE session_message (
    id text PRIMARY KEY, session_id text NOT NULL, type text NOT NULL, seq integer NOT NULL,
    time_created integer NOT NULL, time_updated integer NOT NULL, data text NOT NULL
);
"""


def test_a_session_is_read_with_its_totals_and_each_models_cost(tmp_path: Path) -> None:
    path = tmp_path / "opencode" / "opencode.db"
    path.parent.mkdir()
    opus = {"providerID": "anthropic", "id": "claude-opus", "variant": "high"}
    rows: list[tuple[str, str, dict[str, object]]] = [
        ("msg_0", "model-switched", {"model": {"providerID": "anthropic", "id": "asked"}}),
        ("msg_1", "user", {"text": "hi", "files": []}),
        ("msg_2", "assistant", {"agent": "build", "model": opus, "content": [], "cost": 0.5}),
        ("msg_3", "assistant", {"model": {"providerID": "openai", "id": "gpt-5"}, "cost": 0.25}),
        ("msg_4", "assistant", {"model": {"providerID": "openai"}, "cost": 1}),
    ]
    with contextlib.closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO session_v2 VALUES ('ses_2', 'p', 'ses_1', 's', '/work/web', '2.1.4', 0.75, 1, 2, 3, 4, 5,"
            " NULL, 1000, 2000)",
        )
        conn.executemany(
            "INSERT INTO session_message VALUES (?, 'ses_2', ?, ?, 1, 1, ?)",
            [(i, kind, n, json.dumps(data)) for n, (i, kind, data) in enumerate(rows)],
        )

    with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(tmp_path)}):
        page = sessions.updated_after(None)

    [found] = page.sessions
    assert (found.session_id, found.parent_id, found.directory, found.cost_usd) == ("ses_2", "ses_1", "/work/web", 0.75)
    assert (found.input, found.output, found.reasoning, found.cache_read, found.cache_write) == (1, 2, 3, 4, 5)
    assert found.models == (ModelUse("anthropic/claude-opus@high", 1, 0.5), ModelUse("openai/gpt-5", 1, 0.25))
    assert page.cursor == (2000, "ses_2")


def test_a_read_asked_for_titles_keeps_each_and_when_it_was_archived(tmp_path: Path) -> None:
    path = tmp_path / "opencode" / "opencode.db"
    path.parent.mkdir()
    with contextlib.closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript(SCHEMA)
        conn.execute("ALTER TABLE session_v2 ADD COLUMN title text")
        conn.execute("ALTER TABLE session_v2 ADD COLUMN time_archived integer")
        for n, (title, archived) in enumerate([("Plan the\tmigration", None), (None, 3000)]):
            conn.execute(
                "INSERT INTO session_v2 VALUES (?, 'p', NULL, 's', '/work/web', '2.1.4', 0, 0, 0, 0, 0, 0, NULL, 1000,"
                " ?, ?, ?)",
                (f"ses_{n}", 2000 + n, title, archived),
            )

    with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(tmp_path)}):
        page = sessions.updated_after(None, titles=True)

    assert [(s.session_id, s.title, s.archived_ms) for s in page.sessions] == [
        ("ses_0", "Plan the migration", None),
        ("ses_1", None, 3000),
    ]


def test_a_session_is_reopened_in_its_directory_as_opencode_1s_is() -> None:
    assert sessions.reopen("ses_1", "/work/web") == "cd /work/web && opencode --session ses_1"
