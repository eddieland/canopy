"""The subcommands the overseer calls during a tick, and `canopy status`."""

import sqlite3

import pytest
from conftest import CanopyEnv

from canopy import attention, db, resources
from canopy.cli import main


@pytest.fixture
def conn(canopy_env: CanopyEnv) -> sqlite3.Connection:
    c = db.connect(canopy_env.state_dir / "canopy.db")
    db.migrate(c, resources.migrations_dir())
    return c


def in_tick(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, *, dry_run: bool = True) -> int:
    tick_id = db.start_tick(conn, dry_run=dry_run)
    monkeypatch.setenv("CANOPY_TICK_ID", str(tick_id))
    return tick_id


@pytest.mark.parametrize(
    "argv",
    [
        ["dispatch", "{key}", "--kind", "implement"],
        ["decide", "{key}", "wait", "--rationale", "r"],
        ["attention", "{key}", "needs_reviewer", "--detail", "d"],
        ["ticket", "set", "{key}", "--phase", "ready"],
    ],
)
@pytest.mark.parametrize("key", ["-rf", "PROJ 1", "PROJ-1;id", "../x", "#12", "", "_x"])
def test_every_key_taking_command_rejects_bad_keys(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str], argv: list[str], key: str
) -> None:
    with pytest.raises(SystemExit) as exc:
        main([a.replace("{key}", key) for a in argv])
    assert exc.value.code == 2  # noqa: PLR2004
    assert "invalid ticket key" in capsys.readouterr().err or key.startswith("-")


def test_journal_commands_need_a_running_tick(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["decide", "PROJ-1", "wait", "--rationale", "r"]) == 1
    assert "CANOPY_TICK_ID is not set" in capsys.readouterr().err
    tick_id = in_tick(conn, monkeypatch)
    db.finish_tick(conn, tick_id, "ok", "done")
    assert main(["attention", "PROJ-1", "needs_reviewer", "--detail", "d"]) == 1
    assert "does not name a running tick" in capsys.readouterr().err
    assert conn.execute("SELECT count(*) FROM decisions").fetchone()[0] == 0


def test_decide_records_and_touches_ticket(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    tick_id = in_tick(conn, monkeypatch)
    assert main(["decide", "PROJ-1", "skip", "--rationale", "  blocked by PROJ-0  "]) == 0
    assert main(["decide", "skip", "--rationale", "mcp_unavailable: tracker"]) == 0
    rows = [(d["ticket_key"], d["action"], d["rationale"]) for d in db.decisions_for_tick(conn, tick_id)]
    assert rows == [("PROJ-1", "skip", "blocked by PROJ-0"), (None, "skip", "mcp_unavailable: tracker")]
    ticket = conn.execute("SELECT * FROM tickets WHERE key = 'PROJ-1'").fetchone()
    assert ticket["repo"] == str(canopy_env.repo)


def test_decide_needs_a_key_except_for_skip(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    in_tick(conn, monkeypatch)
    assert main(["decide", "wait", "--rationale", "r"]) == 2  # noqa: PLR2004
    with pytest.raises(SystemExit):
        main(["decide", "PROJ-1", "dispatch:implement", "--rationale", "r"])
    with pytest.raises(SystemExit):
        main(["decide", "PROJ-1", "wait", "--rationale", "   "])


def test_long_text_is_truncated(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    tick_id = in_tick(conn, monkeypatch)
    assert main(["decide", "PROJ-1", "wait", "--rationale", "x" * 5000]) == 0
    [row] = db.decisions_for_tick(conn, tick_id)
    assert len(row["rationale"]) == 2000  # noqa: PLR2004


def test_attention_reason_format(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    in_tick(conn, monkeypatch)
    with pytest.raises(SystemExit):
        main(["attention", "PROJ-1", "Needs Reviewer", "--detail", "d"])


def test_dispatch_outside_dry_run_is_refused_and_recorded(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    tick_id = in_tick(conn, monkeypatch, dry_run=False)
    assert main(["dispatch", "PROJ-1", "--kind", "fix-ci"]) == 1
    [row] = db.decisions_for_tick(conn, tick_id)
    assert row["action"] == "refused:not_implemented"


def test_dry_run_dispatch_records_base_and_context(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    tick_id = in_tick(conn, monkeypatch)
    args = ["dispatch", "PROJ-2", "--kind", "implement", "--base", "agent/PROJ-1-x", "--context", "ctx.md"]
    assert main(args) == 0
    [row] = db.decisions_for_tick(conn, tick_id)
    assert row["action"] == "dispatch:implement"
    assert row["rationale"] == "dry run: not dispatched (base=agent/PROJ-1-x; context=ctx.md)"


def test_ticket_set_outside_a_tick_advances_cursors(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    args = ["ticket", "set", "PROJ-1", "--cursor", "comment=10001", "--cursor", "review=PRR_kw1", "--done"]
    assert main(args) == 0
    row = conn.execute("SELECT * FROM tickets WHERE key = 'PROJ-1'").fetchone()
    assert (row["last_comment_id"], row["last_review_id"], row["done"]) == ("10001", "PRR_kw1", 1)


@pytest.mark.parametrize("value", ["pr=1", "comment", "comment=", "comment=a b", "ci=$(id)"])
def test_bad_cursors_are_rejected(canopy_env: CanopyEnv, value: str) -> None:
    with pytest.raises(SystemExit):
        main(["ticket", "set", "PROJ-1", "--cursor", value])


def test_status_and_attention_ages(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["status"]) == 0
    assert "No ticks yet." in capsys.readouterr().out

    def tick(items: list[tuple[str, str]], status: str = "ok") -> int:
        tick_id = db.start_tick(conn, dry_run=True)
        for key, reason in items:
            db.record_decision(conn, tick_id, key, f"attention:{reason}", f"https://example.test/{key}")
        db.finish_tick(conn, tick_id, status, "summary")
        return tick_id

    tick([("PROJ-1", "needs_reviewer")])
    conn.execute("UPDATE decisions SET created_at = '2020-01-01T00:00:00.000Z'")
    tick([("PROJ-1", "needs_reviewer"), ("PROJ-2", "ready_to_merge")])
    tick([("PROJ-9", "needs_author")], status="overseer_failed")  # a failed tick does not replace the list

    items = attention.current(conn)
    assert [(i.ticket_key, i.reason) for i in items] == [("PROJ-1", "needs_reviewer"), ("PROJ-2", "ready_to_merge")]
    assert items[0].since == "2020-01-01T00:00:00.000Z"

    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "Last tick: 3 overseer_failed (dry run)" in out
    assert "Attention (2):" in out
    assert "  needs_reviewer\n    PROJ-1  " in out
    assert "d  https://example.test/PROJ-1" in out  # age in days
    assert "Running workers (0/2):\n  none" in out

    tick([])
    assert attention.current(conn) == []


@pytest.mark.parametrize("key", ["PROJ-1\n", "PROJ-1\r\n", "PROJ-1\n\n"])
def test_trailing_line_breaks_are_not_part_of_a_valid_key(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    # `$` in a Python regex also matches before a trailing newline; validation must use the whole string.
    in_tick(conn, monkeypatch)
    with pytest.raises(SystemExit):
        main(["decide", key, "wait", "--rationale", "r"])
    with pytest.raises(SystemExit):
        main(["attention", "PROJ-1", "needs_reviewer\n", "--detail", "d"])
    with pytest.raises(SystemExit):
        main(["ticket", "set", "PROJ-1", "--cursor", "comment=1\n"])
    assert conn.execute("SELECT count(*) FROM decisions").fetchone()[0] == 0
