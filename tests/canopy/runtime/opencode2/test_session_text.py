"""The text of every OpenCode 2 session, read from OpenCode 2.1.4's database (ROADMAP M72, stage 0)."""

import contextlib
import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest

from canopy.runtime.opencode2 import session_text
from canopy.runtime.report import KeptSession, TextRow
from tests.canopy.helpers import Kept, called, replied, runtime_database, runtime_record, sent, wrote


@pytest.fixture
def data_home(tmp_path: Path) -> Iterator[Path]:
    """The operator's `$XDG_DATA_HOME`, under which the runtime and each sandbox role keep their records."""
    with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(tmp_path)}):
        yield tmp_path


def role(data_home: Path, name: str) -> Path:
    """Where a sandbox role's runtime keeps its record, under the operator's data home."""
    return runtime_database(data_home / "canopy" / "sandbox" / name)


def rows() -> list[TextRow | None]:
    return list(session_text.rows())


def test_each_part_of_a_session_is_read_from_where_its_record_keeps_it(data_home: Path) -> None:
    tool = {
        "type": "tool",
        "id": "call_2",
        "name": "read",
        "state": {"status": "error", "input": {"path": "a.py"}, "error": {"type": "x", "message": "no such file"}},
        "time": {"created": 1},
    }
    runtime_record(
        Kept(
            "ses_1",
            "/work/web",
            title="Fix the login form",
            messages=[
                ("model-switched", {"model": {"providerID": "anthropic", "id": "claude"}}),
                sent("make the button blue"),
                ("synthetic", {"text": "the subagent said done"}),
                replied(
                    {"type": "reasoning", "text": "think first"},
                    wrote("Done, it is blue."),
                    called("shell", {"command": "rg button", "timeout": 5}, "src/a.css"),
                    tool,
                ),
                ("shell", {"shellID": "sh_1", "command": "git status", "output": {"output": "clean", "size": 5}}),
                ("compaction", {"status": "completed", "reason": "auto", "summary": "the button work so far"}),
                ("idle", {"outcome": "succeeded"}),
            ],
        ),
    )

    assert sorted((r.part, r.text) for r in rows() if r is not None) == [
        ("given", "a.py"),
        ("given", "git status"),
        ("given", "rg button"),
        ("reasoning", "think first"),
        ("returned", "clean"),
        ("returned", "no such file"),
        ("returned", "src/a.css"),
        ("sent", "make the button blue"),
        ("sent", "the subagent said done"),
        ("summary", "the button work so far"),
        ("title", "Fix the login form"),
        ("wrote", "Done, it is blue."),
    ]


def test_a_message_canopy_cannot_read_is_passed_over_and_counted(data_home: Path) -> None:
    runtime_record(
        Kept(
            "ses_1",
            "/work",
            messages=[
                ("user", "not JSON"),
                ("user", {"text": 42}),
                ("assistant", {"content": "a string, not parts"}),
                ("assistant", {"content": [7, {"type": "text"}]}),
                sent("kept"),
            ],
        ),
        Kept("ses 2", "/work", title="an id canopy never prints"),
    )

    found = rows()

    # Not JSON, and parts that are not parts, hold no text; a text that is a number, and a title of an id no session
    # canopy prints has, are rows canopy cannot read.
    assert [(r.session_id, r.text) for r in found if r is not None] == [("ses_1", "kept")]
    assert found.count(None) == 2


def test_every_session_is_counted_with_the_session_it_ran_for_and_whether_it_was_archived(data_home: Path) -> None:
    runtime_record(
        Kept("ses_1", "/work"),
        Kept("ses_2", "/work", parent_id="ses_1", archived=True),
        Kept("ses 3", "/work"),
    )

    found = session_text.record()

    assert found.outcome == "found"
    assert found.sessions == [
        KeptSession("ses_1", None, "/work", archived=False),
        KeptSession("ses_2", "ses_1", "/work", archived=True),
    ]
    assert (found.databases, found.skipped, found.earlier_only) == (1, 1, 0)
    assert found.size_bytes == runtime_database().stat().st_size


def test_the_sessions_only_opencode_1s_table_holds_are_counted_never_read(data_home: Path) -> None:
    path = runtime_record(Kept("ses_1", "/work", title="kept by both"))
    with contextlib.closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("CREATE TABLE session (id text PRIMARY KEY, title text)")
        conn.executemany("INSERT INTO session VALUES (?, 'old')", [("ses_1",), ("ses_0",)])

    assert session_text.record().earlier_only == 1
    assert [r.text for r in rows() if r is not None] == ["kept by both"]


def test_a_database_of_opencode_1s_alone_holds_its_sessions_as_earlier_only(data_home: Path) -> None:
    path = runtime_database()
    path.parent.mkdir(parents=True)
    with contextlib.closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("CREATE TABLE session (id text PRIMARY KEY)")
        conn.execute("INSERT INTO session VALUES ('ses_0')")

    found = session_text.record()

    assert (found.outcome, found.sessions, found.earlier_only) == ("found", [], 1)
    assert rows() == []


def test_each_sandbox_roles_record_is_read_with_the_operators_and_one_canopy_cannot_read_passed_over(
    data_home: Path,
) -> None:
    runtime_record(Kept("ses_1", "/work", messages=[sent("the operator's")]))
    runtime_record(Kept("ses_2", "/work", messages=[sent("the worker's")]), path=role(data_home, "worker"))
    broken = role(data_home, "review")
    broken.parent.mkdir(parents=True)
    broken.write_text("not a database")

    found = session_text.record()

    assert [s.session_id for s in found.sessions] == ["ses_1", "ses_2"]
    assert (found.databases, found.passed_over) == (2, 1)
    assert sorted(r.text for r in rows() if r is not None) == ["the operator's", "the worker's"]
    assert session_text.scan(["worker"], {"sent"}) == [("ses_2", "sent")]


def test_a_record_that_is_missing_or_not_a_database_is_said_so(data_home: Path) -> None:
    assert session_text.record().outcome == "missing"
    runtime_database().parent.mkdir(parents=True)
    runtime_database().write_text("not a database")

    found = session_text.record()

    assert found.outcome == "failed"
    assert found.error is not None
    assert found.error.startswith("OpenCode's database could not be read")
    with pytest.raises(sqlite3.DatabaseError):
        rows()


def test_a_scan_finds_the_parts_that_hold_every_word_among_those_it_is_given(data_home: Path) -> None:
    runtime_record(
        Kept("ses_1", "/work", title="Blue button", messages=[sent("make the BUTTON blue")]),
        Kept("ses_2", "/work", messages=[replied(wrote("the button is red"))]),
        Kept("ses_3", "/work", messages=[sent("100% blue_button")]),
    )

    assert session_text.scan(["blue", "button"], {"title", "sent"}) == [
        ("ses_1", "sent"),
        ("ses_1", "title"),
        ("ses_3", "sent"),
    ]
    assert session_text.scan(["button"], {"wrote"}) == [("ses_2", "wrote")]
    # A word's wildcards are matched as themselves: `_` is no letter and `%` no run of them.
    assert session_text.scan(["e_b"], {"sent", "title"}) == [("ses_3", "sent")]
    assert session_text.scan(["0%"], {"sent"}) == [("ses_3", "sent")]
    assert session_text.scan(["n%b"], {"sent", "title"}) == []
