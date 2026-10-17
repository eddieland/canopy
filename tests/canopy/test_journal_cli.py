"""The subcommands the overseer calls during a tick, and `canopy status`."""

import sqlite3
from collections.abc import Iterable

import pytest

from canopy.cli.main import main
from canopy.core import agent_output, db
from canopy.core.vocab import TickStatus
from canopy.loop import attention
from tests.canopy.helpers import in_tick
from tests.conftest import CanopyEnv


@pytest.mark.parametrize(
    "argv",
    [
        ["dispatch", "{key}", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"],
        ["decide", "{key}", "wait", "--rationale", "r"],
        ["attention", "{key}", "needs_reviewer", "--detail", "d"],
        ["ticket", "set", "{key}", "--repo", "repo", "--phase", "ready"],
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
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["decide", "PROJ-1", "wait", "--rationale", "r"]) == 1
    assert "CANOPY_TICK_ID is not set" in capsys.readouterr().err
    with in_tick(conn) as tick_id:
        db.finish_tick(conn, tick_id, TickStatus.OK, "done")
        assert main(["attention", "PROJ-1", "needs_reviewer", "--detail", "d"]) == 1
        assert "does not name a running tick" in capsys.readouterr().err
        assert conn.execute("SELECT count(*) FROM decisions").fetchone()[0] == 0


def test_decide_records_and_touches_ticket(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    with in_tick(conn) as tick_id:
        assert main(["decide", "PROJ-1", "skip", "--rationale", "  blocked by PROJ-0  "]) == 0
        assert main(["decide", "skip", "--rationale", "mcp_unavailable: tracker"]) == 0
        rows = [(d.ticket_key, d.action, d.rationale) for d in db.decisions_for_tick(conn, tick_id)]
        assert rows == [("PROJ-1", "skip", "blocked by PROJ-0"), (None, "skip", "mcp_unavailable: tracker")]
        ticket = conn.execute("SELECT * FROM tickets WHERE key = 'PROJ-1'").fetchone()
        assert ticket["repo"] == str(canopy_env.root)


def test_decide_needs_a_key_except_for_skip(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    with in_tick(conn):
        assert main(["decide", "wait", "--rationale", "r"]) == 2
        assert main(["decide", "PROJ-1", "dispatch:implement", "--rationale", "r"]) == 2
        assert main(["decide", "PROJ-1", "wait", "--rationale", "   "]) == 2
        assert main(["decide", "PROJ-1", "wait", "extra", "--rationale", "r"]) == 2


def test_only_a_tick_wide_reason_skips_the_tick(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    with in_tick(conn) as tick_id:
        assert main(["decide", "skip", "--rationale", "wanted to relabel PROJ-1"]) == 2
        assert "a skip about one ticket names its key" in capsys.readouterr().err
        assert main(["decide", "queue", "skip", "--rationale", "tracker_unsupported: queue is not an issue"]) == 2
        assert "'tracker_unsupported' skips the whole tick and names no key" in capsys.readouterr().err
        assert main(["decide", "skip", "--rationale", "tracker_unsupported: labels"]) == 0
        assert main(["decide", "PROJ-1", "wait", "--rationale", "mcp_unavailable: github, for its PR"]) == 0
        rows = [(d.ticket_key, d.rationale) for d in db.decisions_for_tick(conn, tick_id)]
        assert rows == [(None, "tracker_unsupported: labels"), ("PROJ-1", "mcp_unavailable: github, for its PR")]


def test_long_text_is_truncated(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    with in_tick(conn) as tick_id:
        assert main(["decide", "PROJ-1", "wait", "--rationale", "x" * 5000]) == 0
        [row] = db.decisions_for_tick(conn, tick_id)
        assert len(row.rationale) == 2000


def test_attention_reason_format(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    with in_tick(conn):
        assert main(["attention", "PROJ-1", "Needs Reviewer", "--detail", "d"]) == 2


def test_dry_run_dispatch_records_branch_cursors_and_context(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    with in_tick(conn, dry_run=True) as tick_id:
        assert (
            main(
                [
                    "dispatch",
                    "PROJ-2",
                    "--repo",
                    "repo",
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
            main(
                [
                    "dispatch",
                    "PROJ-3",
                    "--repo",
                    "repo",
                    "--label",
                    "agent-ready-tester",
                    "--kind",
                    "implement",
                    "--slug",
                    "add-login",
                ]
            )
            == 0
        )
        rows = [(d.action, d.rationale) for d in db.decisions_for_tick(conn, tick_id)]
        assert rows == [
            (
                "dispatch:implement",
                (
                    "dry run: not dispatched; would work on agent/PROJ-2-work in repo; label agent-ready-tester; "
                    "cursor comment=7; context=see comment 7"
                ),
            ),
            (
                "dispatch:implement",
                "dry run: not dispatched; would work on agent/PROJ-3-add-login in repo; label agent-ready-tester",
            ),
        ]
        ticket = conn.execute("SELECT * FROM tickets WHERE key = 'PROJ-2'").fetchone()
        assert ticket["last_comment_id"] is None  # a dry run never advances cursors
        assert ticket["branch"] is None  # nor records a branch


def test_dry_run_ticket_set_records_the_phase_only(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    with in_tick(conn, dry_run=True):
        assert (
            main(
                [
                    "ticket",
                    "set",
                    "PROJ-1",
                    "--repo",
                    "repo",
                    "--phase",
                    "merged",
                    "--cursor",
                    "review=2026-10-07T20:58:50Z",
                    "--done",
                ]
            )
            == 0
        )
        assert capsys.readouterr().out == "updated PROJ-1 (repo); dry run, cursors not advanced and not marked done\n"
        row = conn.execute("SELECT * FROM tickets WHERE key = 'PROJ-1'").fetchone()
        assert (row["phase"], row["done"]) == (None, 0)
        # A phase about the PR is the unit's, implied in a single repository; its review cursor was not advanced.
        [unit] = db.units(conn, "PROJ-1")
        assert (unit["phase"], unit["last_review_id"]) == ("merged", None)
        assert [t.key for t in db.open_tickets(conn)] == ["PROJ-1"]  # the first live tick still sees it


def test_decisions_prints_a_ticks_plan(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["decisions"]) == 0
    assert capsys.readouterr().out == "No ticks yet.\n"
    first = db.start_tick(conn, dry_run=True)
    db.record_decision(conn, first, "PROJ-1", "dispatch:implement", "dry run: not dispatched;\nwould work on x")
    db.record_decision(conn, first, None, "skip", "nothing else")
    db.finish_tick(conn, first, TickStatus.OK, "dry run; 2 decisions")
    second = db.start_tick(conn, dry_run=False)
    db.finish_tick(conn, second, TickStatus.OK, "0 decisions: none")

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


def test_decisions_and_status_print_what_a_tick_cost(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    tick_id = db.start_tick(conn, dry_run=False)
    usage = agent_output.Usage(
        0.5, input=9000, output=1000, reasoning=0, cache_read=40_000, cache_write=0, peak_context=26_000
    )
    db.set_tick_report(conn, tick_id, "ses_o1", usage)
    db.finish_tick(conn, tick_id, TickStatus.OK, "0 decisions: none")

    assert main(["decisions"]) == 0
    assert "\n  overseer session ses_o1  $0.50, 10.0k tokens, 26.0k peak context\n" in capsys.readouterr().out
    assert main(["status"]) == 0
    assert "Last tick: 1 ok, started 0s ago  $0.50, 10.0k tokens, 26.0k peak context\n" in capsys.readouterr().out


def test_decisions_filters_by_ticket_and_reports_no_match(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    tick_id = db.start_tick(conn, dry_run=True)
    db.record_decision(conn, tick_id, "GH-1", "wait", "checks pending")
    db.record_decision(conn, tick_id, "GH-10", "done", "merged")
    db.record_decision(conn, tick_id, None, "skip", "nothing to do")
    db.finish_tick(conn, tick_id, TickStatus.OK, "3 decisions")

    assert main(["decisions", "--ticket", "GH-1"]) == 0
    out = capsys.readouterr().out
    assert "Decisions (1):" in out
    assert "GH-1  wait  checks pending" in out
    assert "GH-10" not in out
    assert "nothing to do" not in out

    assert main(["decisions", str(tick_id), "--ticket", "GH-2"]) == 0
    out = capsys.readouterr().out
    assert "Decisions (0):" in out
    assert "none for ticket GH-2" in out


def test_ticket_set_outside_a_tick_advances_cursors(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    args = [
        "ticket",
        "set",
        "PROJ-1",
        "--repo",
        "repo",
        "--cursor",
        "comment=10001",
        "--cursor",
        "review=2026-10-07T20:58:50Z",
        "--done",
    ]
    assert main(args) == 0
    row = conn.execute("SELECT * FROM tickets WHERE key = 'PROJ-1'").fetchone()
    assert (row["last_comment_id"], row["done"]) == ("10001", 1)
    # In a single repository, the review cursor goes to the ticket's one unit without naming it.
    [unit] = db.units(conn, "PROJ-1")
    assert (unit["repo"], unit["last_review_id"]) == ("repo", "2026-10-07T20:58:50Z")


def test_a_ticket_is_named_on_one_line_and_renamed(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    def title() -> object:
        return conn.execute("SELECT title FROM tickets WHERE key = 'PROJ-1'").fetchone()["title"]

    assert main(["ticket", "set", "PROJ-1", "--title", "  Fix the\n\tlogin\x1b[2J loop "]) == 0
    assert title() == "Fix the login [2J loop"
    assert main(["ticket", "set", "PROJ-1", "--title", "x" * 100]) == 0
    assert title() == "x" * 77 + "..."
    assert main(["ticket", "set", "PROJ-1", "--title", " \n "]) == 2
    assert main(["ticket", "set", "PROJ-1", "--phase", "ready"]) == 0
    assert title() == "x" * 77 + "..."  # a set without --title keeps it
    assert main(["ticket", "set", "PROJ-1", "--title", "Fix the login loop"]) == 0
    capsys.readouterr()

    tick_id = db.start_tick(conn, dry_run=False)
    run_id = db.insert_run(
        conn,
        tick_id=tick_id,
        key="PROJ-1",
        kind="implement",
        branch="agent/PROJ-1-login",
        slots=[],
        runs_dir=canopy_env.state_dir / "runs",
    )
    conn.execute("UPDATE runs SET status = 'done', ended_at = started_at WHERE id = ?", (run_id,))
    db.finish_tick(conn, tick_id, TickStatus.OK, "test")
    assert main(["status"]) == 0
    assert "\n  PROJ-1: Fix the login loop  implement  done  " in capsys.readouterr().out
    assert main(["show", "PROJ-1"]) == 0
    assert "\n  title Fix the login loop\n" in capsys.readouterr().out
    assert main(["show", f"run:{run_id}"]) == 0
    assert f"run:{run_id}: implement of PROJ-1: Fix the login loop, done" in capsys.readouterr().out


@pytest.mark.parametrize(
    "value", ["pr=1", "comment", "comment=", "comment=a b", "ci=$(id)", "review=2026-10-07T20:58:50+00:00"]
)
def test_bad_cursors_are_rejected(canopy_env: CanopyEnv, value: str) -> None:
    assert main(["ticket", "set", "PROJ-1", "--repo", "repo", "--cursor", value]) == 2


@pytest.mark.parametrize(
    "value",
    [
        "5448282907",  # a review's id: review comments and review runs are numbered apart from reviews
        "run:12",
        "PRR_kw1",
        "2026-10-07T20:58:50.000Z",  # one form only, so cursors compare as strings
        "2026-02-30T00:00:00Z",  # not a moment at all
    ],
)
def test_a_review_cursor_is_a_time(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str], value: str
) -> None:
    assert main(["ticket", "set", "PROJ-1", "--repo", "repo", "--cursor", f"review={value}"]) == 2
    assert "a review cursor is the newest handled item's time in UTC" in capsys.readouterr().err
    assert main(["ticket", "set", "PROJ-1", "--repo", "repo", "--cursor", "review=2026-10-07T20:58:50Z"]) == 0
    [unit] = db.units(conn, "PROJ-1")
    assert unit["last_review_id"] == "2026-10-07T20:58:50Z"


def test_status_and_attention_ages(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["status"]) == 0
    assert "No ticks yet." in capsys.readouterr().out

    def tick(items: Iterable[tuple[str, str]], status: TickStatus = TickStatus.OK) -> int:
        tick_id = db.start_tick(conn, dry_run=True)
        for key, reason in items:
            db.record_decision(conn, tick_id, key, f"attention:{reason}", f"https://example.test/{key}")
        db.finish_tick(conn, tick_id, status, "summary")
        return tick_id

    tick([("PROJ-1", "needs_reviewer")])
    conn.execute("UPDATE decisions SET created_at = '2020-01-01T00:00:00.000Z'")
    tick([("PROJ-1", "needs_reviewer"), ("PROJ-2", "ready_to_merge")])
    tick([("PROJ-9", "needs_author")], status=TickStatus.OVERSEER_FAILED)  # a failed tick does not replace the list

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
    canopy_env: CanopyEnv, conn: sqlite3.Connection, key: str
) -> None:
    # `$` in a Python regex also matches before a trailing newline; validation must use the whole string.
    with in_tick(conn):
        assert main(["decide", key, "wait", "--rationale", "r"]) == 2
        assert main(["attention", "PROJ-1", "needs_reviewer\n", "--detail", "d"]) == 2
        assert main(["ticket", "set", "PROJ-1", "--repo", "repo", "--cursor", "comment=1\n"]) == 2
        assert conn.execute("SELECT count(*) FROM decisions").fetchone()[0] == 0
