"""The subcommands the overseer calls during a tick, and `canopy status`."""

import sqlite3

import pytest

from canopy.cli.main import main
from canopy.core import db
from canopy.infra import resources
from canopy.loop import attention
from tests.conftest import CanopyEnv


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
        ["dispatch", "{key}", "--label", "agent-ready-tester", "--kind", "implement"],
        ["decide", "{key}", "wait", "--rationale", "r"],
        ["attention", "{key}", "needs_reviewer", "--detail", "d"],
        ["ticket", "set", "{key}", "--phase", "ready"],
    ],
)
@pytest.mark.parametrize("key", ["-rf", "PROJ 1", "PROJ-1;id", "../x", "#12", "", "_x"])
def test_every_key_taking_command_rejects_bad_keys(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str], argv: list[str], key: str
) -> None:
    assert main([a.replace("{key}", key) for a in argv]) == 2
    err = capsys.readouterr().err
    assert "invalid ticket key" in err or (key.startswith("-") and "No such option" in err)


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
    assert main(["decide", "wait", "--rationale", "r"]) == 2
    assert main(["decide", "PROJ-1", "dispatch:implement", "--rationale", "r"]) == 2
    assert main(["decide", "PROJ-1", "wait", "--rationale", "   "]) == 2
    assert main(["decide", "PROJ-1", "wait", "extra", "--rationale", "r"]) == 2


def test_long_text_is_truncated(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    tick_id = in_tick(conn, monkeypatch)
    assert main(["decide", "PROJ-1", "wait", "--rationale", "x" * 5000]) == 0
    [row] = db.decisions_for_tick(conn, tick_id)
    assert len(row["rationale"]) == 2000


def test_attention_reason_format(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    in_tick(conn, monkeypatch)
    assert main(["attention", "PROJ-1", "Needs Reviewer", "--detail", "d"]) == 2


def test_dry_run_dispatch_records_branch_cursors_and_context(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    tick_id = in_tick(conn, monkeypatch)
    assert (
        main(
            [
                "dispatch",
                "PROJ-2",
                "--label",
                "agent-ready-tester",
                "--kind",
                "implement",
                "--context",
                "see comment 7",
                "--cursor",
                "comment=7",
            ]
        )
        == 0
    )
    assert (
        main(["dispatch", "PROJ-3", "--label", "agent-ready-tester", "--kind", "implement", "--slug", "add-login"]) == 0
    )
    rows = [(d["action"], d["rationale"]) for d in db.decisions_for_tick(conn, tick_id)]
    assert rows == [
        (
            "dispatch:implement",
            (
                "dry run: not dispatched; would work on agent/PROJ-2-work; label agent-ready-tester; cursor comment=7; "
                "context=see comment 7"
            ),
        ),
        (
            "dispatch:implement",
            "dry run: not dispatched; would work on agent/PROJ-3-add-login; label agent-ready-tester",
        ),
    ]
    ticket = conn.execute("SELECT * FROM tickets WHERE key = 'PROJ-2'").fetchone()
    assert ticket["last_comment_id"] is None  # a dry run never advances cursors
    assert ticket["branch"] is None  # nor records a branch


def test_dry_run_ticket_set_records_the_phase_only(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    in_tick(conn, monkeypatch)
    assert main(["ticket", "set", "PROJ-1", "--phase", "merged", "--cursor", "review=9", "--done"]) == 0
    assert capsys.readouterr().out == "updated PROJ-1; dry run, cursors not advanced and not marked done\n"
    row = conn.execute("SELECT * FROM tickets WHERE key = 'PROJ-1'").fetchone()
    assert (row["phase"], row["done"]) == (None, 0)
    # A phase about the PR is the unit's, implied in a single repository; its review cursor was not advanced.
    [unit] = db.units(conn, "PROJ-1")
    assert (unit["phase"], unit["last_review_id"]) == ("merged", None)
    assert [t["key"] for t in db.open_tickets(conn)] == ["PROJ-1"]  # the first live tick still sees it


def test_decisions_prints_a_ticks_plan(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["decisions"]) == 0
    assert capsys.readouterr().out == "No ticks yet.\n"
    first = db.start_tick(conn, dry_run=True)
    db.record_decision(conn, first, "PROJ-1", "dispatch:implement", "dry run: not dispatched;\nwould work on x")
    db.record_decision(conn, first, None, "skip", "nothing else")
    db.finish_tick(conn, first, "ok", "dry run; 2 decisions")
    second = db.start_tick(conn, dry_run=False)
    db.finish_tick(conn, second, "ok", "0 decisions: none")

    assert main(["decisions"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Tick 2: ok, started ")
    assert out.endswith("Decisions (0):\n  none\n")

    assert main(["decisions", str(first)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("Tick 1: ok (dry run), started ")
    assert lines[1] == "  dry run; 2 decisions"
    assert lines[-3:] == [
        "Decisions (2):",
        "  PROJ-1  dispatch:implement  dry run: not dispatched; would work on x",
        "  -       skip                nothing else",
    ]

    assert main(["decisions", "9"]) == 1
    assert "no tick 9" in capsys.readouterr().err


def test_ticket_set_outside_a_tick_advances_cursors(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    args = ["ticket", "set", "PROJ-1", "--cursor", "comment=10001", "--cursor", "review=PRR_kw1", "--done"]
    assert main(args) == 0
    row = conn.execute("SELECT * FROM tickets WHERE key = 'PROJ-1'").fetchone()
    assert (row["last_comment_id"], row["done"]) == ("10001", 1)
    # In a single repository, the review cursor goes to the ticket's one unit without naming it.
    [unit] = db.units(conn, "PROJ-1")
    assert (unit["repo"], unit["last_review_id"]) == ("repo", "PRR_kw1")


@pytest.mark.parametrize("value", ["pr=1", "comment", "comment=", "comment=a b", "ci=$(id)"])
def test_bad_cursors_are_rejected(canopy_env: CanopyEnv, value: str) -> None:
    assert main(["ticket", "set", "PROJ-1", "--cursor", value]) == 2


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
    assert main(["decide", key, "wait", "--rationale", "r"]) == 2
    assert main(["attention", "PROJ-1", "needs_reviewer\n", "--detail", "d"]) == 2
    assert main(["ticket", "set", "PROJ-1", "--cursor", "comment=1\n"]) == 2
    assert conn.execute("SELECT count(*) FROM decisions").fetchone()[0] == 0
