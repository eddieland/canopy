"""The overseer's journal tools, and what the operator reads of what they recorded.

The tools are `decide`, `attention`, and `ticket-set` (DESIGN §27); the operator reads them with `canopy decisions` and
`canopy status`.
"""

import json
import sqlite3
from collections.abc import Callable, Iterable, Mapping
from importlib.metadata import version
from pathlib import Path

import pytest

from canopy.core import db
from canopy.core.vocab import TickStatus
from canopy.loop import attention
from canopy.runtime.report import Usage
from tests.canopy.helpers import (
    Called,
    agent_runs,
    calls,
    decides,
    in_tick,
    overseer_calls,
    raises,
    ticket_sets,
    tracker_holds,
    waits,
)
from tests.canopy.observation_helpers import comment
from tests.canopy.scenario_helpers import Scenario, dispatches, pushes
from tests.conftest import TRACKER_SOURCE, GitPool

#: A review cursor as canopy keeps one: the newest handled item's journal number (DESIGN §35).
REVIEWED: Mapping[str, str] = {"review": "4127"}


#: Each tool that takes a ticket's key, as a call of it that names the key given.
KEYED: Mapping[str, Callable[[str], Called]] = {
    "dispatch": dispatches,
    "decide": lambda key: decides(key, "wait", "r"),
    "attention": lambda key: raises(key, "needs_author", "d"),
    "ticket-set": lambda key: ticket_sets(key, repo="repo", phase="ready"),
}


@pytest.mark.parametrize("move", list(KEYED.values()), ids=list(KEYED))
@pytest.mark.parametrize("key", ["-rf", "PROJ 1", "PROJ-1;id", "../x", "#12", "", "_x"])
def test_every_key_taking_tool_rejects_bad_keys(
    conn: sqlite3.Connection,
    move: Callable[[str], Called],
    key: str,
) -> None:
    with in_tick(conn):
        said = overseer_calls(move(key))
    assert said.error
    assert "invalid ticket key" in said.text
    assert conn.execute("SELECT count(*) FROM decisions").fetchone()[0] == 0


def test_journal_tools_need_a_running_tick(conn: sqlite3.Connection) -> None:
    outside = "CANOPY_TICK_ID is not set"
    assert outside in overseer_calls(decides("PROJ-1", "wait", "r")).text
    # ticket-set too: the operator has no command to set a ticket outside a tick, and the tool takes nothing there.
    said = overseer_calls(ticket_sets("PROJ-1", repo="repo", cursors={"comment": "10001"}, done=True))
    assert said.error
    assert outside in said.text
    with in_tick(conn) as tick_id:
        db.finish_tick(conn, tick_id, TickStatus.OK, "done")
        said = overseer_calls(raises("PROJ-1", "needs_author", "d"))
        assert said.error
        assert "does not name a running tick" in said.text
        assert conn.execute("SELECT count(*) FROM decisions").fetchone()[0] == 0
    assert db.get_ticket(conn, "PROJ-1") is None


def test_decide_records_and_touches_ticket(scenario: Scenario) -> None:
    conn = scenario.conn
    with scenario.ticking() as tick_id:
        scenario.overseer(decides("PROJ-1", "skip", "  blocked by PROJ-0  "))
    rows = [(d.ticket_key, d.action, d.rationale) for d in db.decisions_for_tick(conn, tick_id)]
    assert rows == [("PROJ-1", "skip", "blocked by PROJ-0")]
    ticket = conn.execute("SELECT * FROM tickets WHERE key = 'PROJ-1'").fetchone()
    assert ticket["repo"] == str(scenario.env.root)


def test_decide_needs_a_key_an_action_it_takes_and_a_rationale(scenario: Scenario) -> None:
    with scenario.ticking() as tick_id:
        refused = [
            scenario.overseer(calls("canopy_decide", decisions=[{"action": "wait", "rationale": "r"}]), error=True),
            scenario.overseer(decides("PROJ-1", "dispatch:implement", "r"), error=True),
            scenario.overseer(decides("PROJ-1", "wait", "   "), error=True),
        ]
    assert [said.text.partition(":")[0] for said in refused] == [
        "decisions.0.key",
        "decisions.0.action",
        "decisions.0.rationale",
    ]
    assert db.decisions_for_tick(scenario.conn, tick_id) == []


def test_decide_records_several_in_one_call(scenario: Scenario) -> None:
    def decide(*decisions: tuple[str, str, str]) -> Called:
        return calls("canopy_decide", decisions=[{"key": k, "action": a, "rationale": r} for k, a, r in decisions])

    with scenario.ticking() as tick_id:
        said = scenario.overseer(decide(("PROJ-1", "wait", "checks pending"), ("PROJ-2", "done", "merged")))
        assert said.text == "recorded wait for PROJ-1\nrecorded done for PROJ-2"
        # Every decision names its ticket and an action decide takes, or the call records none of them.
        scenario.overseer(
            calls(
                "canopy_decide",
                decisions=[
                    {"key": "PROJ-3", "action": "wait", "rationale": "r"},
                    {"action": "skip", "rationale": "mcp_unavailable: x"},
                ],
            ),
            error=True,
        )
        scenario.overseer(decide(("PROJ-3", "wait", "r"), ("PROJ-4", "later", "s")), error=True)
    rows = [(d.ticket_key, d.action, d.rationale) for d in db.decisions_for_tick(scenario.conn, tick_id)]
    assert rows == [("PROJ-1", "wait", "checks pending"), ("PROJ-2", "done", "merged")]
    assert {row["key"] for row in scenario.conn.execute("SELECT key FROM tickets")} == {"PROJ-1", "PROJ-2"}


def test_every_skip_is_a_tickets_own(scenario: Scenario) -> None:
    """The overseer reads no tracker nor GitHub, which the sources read (DESIGN §39): no skip is the whole tick's."""
    with scenario.ticking() as tick_id:
        whole = calls("canopy_decide", decisions=[{"action": "skip", "rationale": "tracker_unsupported: labels"}])
        assert scenario.overseer(whole, error=True).text == "decisions.0.key: Field required"
        scenario.overseer(decides("PROJ-1", "skip", "mcp_unavailable: github, for its PR"))
    rows = [(d.ticket_key, d.rationale) for d in db.decisions_for_tick(scenario.conn, tick_id)]
    assert rows == [("PROJ-1", "mcp_unavailable: github, for its PR")]


def test_long_text_is_truncated(scenario: Scenario) -> None:
    with scenario.ticking() as tick_id:
        scenario.overseer(decides("PROJ-1", "wait", "x" * 5000))
    [row] = db.decisions_for_tick(scenario.conn, tick_id)
    assert len(row.rationale) == 2000


def test_attention_reason_format(scenario: Scenario) -> None:
    said = scenario.overseer(raises("PROJ-1", "Needs Reviewer", "d"), error=True)
    assert said.text.startswith("reason: invalid reason 'Needs Reviewer'")


def test_dry_run_dispatch_records_branch_cursors_and_context(scenario: Scenario, connector_state: Path) -> None:
    conn = scenario.conn
    # The tracker shows a comment on PROJ-2, its first item, so journal number 1 (DESIGN §35).
    said = {"kind": "comment", "ticket": "PROJ-2", "id": "c7", "author": "acc-1", "time": "2026-10-18T10:00:00Z"}
    connector_state.write_text(json.dumps({TRACKER_SOURCE: {"lines": [said]}}))
    ticked = scenario.tick(
        dispatches("PROJ-2", context="see comment 7", cursors={"comment": "1"}),
        dispatches("PROJ-3", slug="add-login"),
        dry_run=True,
    )
    assert ticked.actions == ["queried", "dispatch:implement", "dispatch:implement"]
    assert [d.rationale for d in ticked.decisions[1:]] == [
        (
            "dry run: not dispatched; would work on agent/PROJ-2-work in repo; label agent-ready-tester; "
            "cursor comment=1; context=see comment 7"
        ),
        "dry run: not dispatched; would work on agent/PROJ-3-add-login in repo; label agent-ready-tester",
    ]
    ticket = conn.execute("SELECT * FROM tickets WHERE key = 'PROJ-2'").fetchone()
    assert (ticket["comment_cursor"], ticket["last_comment_id"]) == (None, None)  # a dry run never advances cursors
    assert ticket["branch"] is None  # nor records a branch


def test_dry_run_ticket_set_records_the_phase_only(scenario: Scenario) -> None:
    conn = scenario.conn
    sets = ticket_sets("PROJ-1", repo="repo", phase="merged", cursors=REVIEWED, done=True)
    scenario.tick(sets, *waits("PROJ-1"), dry_run=True)
    # What the overseer read back from the tool, in the dry tick it called it in.
    [said] = [t for t in agent_runs(scenario.agent_log)[-1]["tools"] if t["name"] == sets.name]
    assert (said["text"], said["error"]) == (
        "updated PROJ-1 (repo); dry run, cursors not advanced and not marked done",
        False,
    )
    row = conn.execute("SELECT * FROM tickets WHERE key = 'PROJ-1'").fetchone()
    assert (row["phase"], row["done"]) == (None, 0)
    # A phase about the PR is the unit's, implied in a single repository; its review cursor was not advanced.
    [unit] = db.units(conn, "PROJ-1")
    assert (unit.phase, unit.review_cursor) == ("merged", None)
    assert [t.key for t in db.open_tickets(conn)] == ["PROJ-1"]  # the first live tick still sees it


def test_decisions_prints_a_ticks_plan(scenario: Scenario) -> None:
    conn = scenario.conn
    assert scenario.operator("decisions").out == "No ticks yet.\n"
    first = db.start_tick(conn, dry_run=True)
    db.record_decision(conn, first, "PROJ-1", "dispatch:implement", "dry run: not dispatched;\nwould work on x")
    db.record_decision(conn, first, None, "skip", "nothing else")
    db.finish_tick(conn, first, TickStatus.OK, "dry run; 2 decisions")
    second = db.start_tick(conn, dry_run=False)
    db.finish_tick(conn, second, TickStatus.OK, "0 decisions: none")

    out = scenario.operator("decisions").out
    assert out.startswith("Tick 2: ok, started ")
    assert out.endswith("Decisions (0):\n  none\n")

    lines = scenario.operator("decisions", str(first)).out.splitlines()
    assert lines[0].startswith("Tick 1: ok (dry run), started ")
    assert lines[0].endswith(f" ago) on canopy {version('canopy')}")
    assert lines[1] == "  dry run; 2 decisions"
    assert lines[-3:] == [
        "Decisions (2):",
        "  PROJ-1  dispatch:implement  dry run: not dispatched; would work on x",
        "  -       skip                nothing else",
    ]

    assert "no tick 9" in scenario.operator("decisions", "9", code=1).err


def test_status_prints_what_a_running_ticks_overseer_did_last(scenario: Scenario) -> None:
    """Its latest tool call while it runs, as a running run's (DESIGN §8), and nothing once the tick ends."""
    conn = scenario.conn
    tick_id = db.start_tick(conn, dry_run=False)
    assert "  overseer  last" not in scenario.operator("status").out
    db.set_progress(conn, "ticks", tick_id, "ses_o1", did=("canopy_decide", "decide 2 tickets"))
    assert "\n  overseer  last canopy_decide: decide 2 tickets 0s ago\n" in scenario.operator("status").out
    db.finish_tick(conn, tick_id, TickStatus.OK, "2 decisions")
    assert "  overseer  last" not in scenario.operator("status").out


def test_decisions_and_status_print_what_a_tick_cost(scenario: Scenario) -> None:
    conn = scenario.conn
    tick_id = db.start_tick(conn, dry_run=False)
    usage = Usage(0.5, input=9000, output=1000, reasoning=0, cache_read=40_000, cache_write=0, peak_context=26_000)
    db.set_tick_report(conn, tick_id, "ses_o1", usage)
    db.finish_tick(conn, tick_id, TickStatus.OK, "0 decisions: none")

    assert (
        "\n  overseer session ses_o1  $0.50, 10.0k tokens, 26.0k peak context\n" in scenario.operator("decisions").out
    )
    status = scenario.operator("status").out
    assert "Last tick: 1 ok, started 0s ago  $0.50, 10.0k tokens, 26.0k peak context\n" in status


def test_decisions_filters_by_ticket_and_reports_no_match(scenario: Scenario) -> None:
    conn = scenario.conn
    tick_id = db.start_tick(conn, dry_run=True)
    db.record_decision(conn, tick_id, "GH-1", "wait", "checks pending")
    db.record_decision(conn, tick_id, "GH-10", "done", "merged")
    db.record_decision(conn, tick_id, None, "skip", "nothing to do")
    db.finish_tick(conn, tick_id, TickStatus.OK, "3 decisions")

    out = scenario.operator("decisions", "--ticket", "GH-1").out
    assert "Decisions (1):" in out
    assert "GH-1  wait  checks pending" in out
    assert "GH-10" not in out
    assert "nothing to do" not in out

    out = scenario.operator("decisions", str(tick_id), "--ticket", "GH-2").out
    assert "Decisions (0):" in out
    assert "none for ticket GH-2" in out


def test_ticket_set_advances_cursors_and_marks_done(scenario: Scenario) -> None:
    conn = scenario.conn
    # A `tracker` source numbers the comments it observes, so the comment cursor is a journal number (DESIGN §35).
    tracker_holds(conn)
    seen = comment(conn, "c7", "acc-1", "2026-10-18T10:00:00.000Z", "See the login page.")
    scenario.overseer(ticket_sets("PROJ-1", repo="repo", cursors={"comment": str(seen), **REVIEWED}, done=True))
    row = conn.execute("SELECT * FROM tickets WHERE key = 'PROJ-1'").fetchone()
    assert (row["comment_cursor"], row["done"]) == (seen, 1)
    # In a single repository, the review cursor goes to the ticket's one unit without naming it.
    [unit] = db.units(conn, "PROJ-1")
    assert (unit.repo, unit.review_cursor) == ("repo", 4127)


def test_ticket_set_sets_several_tickets_each_its_own_or_none(scenario: Scenario) -> None:
    conn = scenario.conn
    updated = scenario.overseer(ticket_sets("PROJ-1", "PROJ-2", phase="ready", done=True))
    assert updated.text == "updated PROJ-1\nupdated PROJ-2"
    rows = conn.execute("SELECT key, phase, done FROM tickets ORDER BY key").fetchall()
    assert [tuple(r) for r in rows] == [("PROJ-1", "ready", 1), ("PROJ-2", "ready", 1)]
    titled = [{"key": "PROJ-1", "title": "Fix the login loop"}, {"key": "PROJ-2", "title": "Add the logout button"}]
    scenario.overseer(calls("canopy_ticket-set", tickets=titled))
    titles = conn.execute("SELECT key, title FROM tickets ORDER BY key").fetchall()
    assert [tuple(r) for r in titles] == [("PROJ-1", "Fix the login loop"), ("PROJ-2", "Add the logout button")]
    # A call one of whose tickets is refused records none of them.
    refused = [{"key": "PROJ-3", "phase": "ready"}, {"key": "PROJ-1", "title": " \n "}]
    said = scenario.overseer(calls("canopy_ticket-set", tickets=refused), error=True)
    assert said.text == "tickets.1.title: must not be empty"
    assert db.get_ticket(conn, "PROJ-3") is None


def test_a_ticket_is_named_on_one_line_and_renamed(scenario: Scenario, git_pool: GitPool) -> None:
    def title() -> object:
        return scenario.conn.execute("SELECT title FROM tickets WHERE key = 'PROJ-1'").fetchone()["title"]

    scenario.overseer(ticket_sets("PROJ-1", title="  Fix the\n\tlogin\x1b[2J loop "))
    assert title() == "Fix the login [2J loop"
    scenario.overseer(ticket_sets("PROJ-1", title="x" * 100))
    assert title() == "x" * 77 + "..."
    scenario.overseer(ticket_sets("PROJ-1", title=" \n "), error=True)
    scenario.overseer(ticket_sets("PROJ-1", phase="ready"))
    assert title() == "x" * 77 + "..."  # a set without a title keeps it
    scenario.overseer(ticket_sets("PROJ-1", title="Fix the login loop"))

    run = scenario.run(dispatches(slug="login"), worker=pushes("agent/PROJ-1-login"))
    assert "\n  PROJ-1: Fix the login loop  implement  done  " in scenario.operator("status").out
    assert "\n  title Fix the login loop\n" in scenario.operator("show", "PROJ-1").out
    shown = scenario.operator("show", f"run:{run.id}").out
    assert f"run:{run.id}: implement of PROJ-1: Fix the login loop, done" in shown


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("pr", "1"),
        ("comment", ""),
        ("comment", "a b"),
        ("ci", "$(id)"),
        ("review", "2026-10-07T20:58:50+00:00"),
    ],
)
def test_bad_cursors_are_rejected(scenario: Scenario, name: str, value: str) -> None:
    said = scenario.overseer(ticket_sets("PROJ-1", repo="repo", cursors={name: value}), error=True)
    assert said.text.startswith("tickets.0.cursors")
    assert db.get_ticket(scenario.conn, "PROJ-1") is None


@pytest.mark.parametrize(
    "value",
    [
        "run:12",
        "PRR_kw1",
        "2026-10-07T20:58:50Z",  # the time form an earlier canopy kept, gone with journal numbers
        "1.5",
    ],
)
def test_a_review_cursor_is_a_journal_number(scenario: Scenario, value: str) -> None:
    refused = scenario.overseer(ticket_sets("PROJ-1", repo="repo", cursors={"review": value}), error=True)
    assert "a review cursor is an item's journal number" in refused.text
    scenario.overseer(ticket_sets("PROJ-1", repo="repo", cursors=REVIEWED))
    [unit] = db.units(scenario.conn, "PROJ-1")
    assert unit.review_cursor == 4127


def test_status_and_attention_ages(scenario: Scenario) -> None:
    conn = scenario.conn
    assert "No ticks yet." in scenario.operator("status").out

    def tick(items: Iterable[tuple[str, str]], status: TickStatus = TickStatus.OK, waits: Iterable[str] = ()) -> int:
        tick_id = db.start_tick(conn, dry_run=True)
        for key, reason in items:
            db.record_decision(conn, tick_id, key, f"attention:{reason}", f"https://example.test/{key}")
        for key in waits:
            db.record_decision(conn, tick_id, key, "wait", "nothing to do yet")
        db.finish_tick(conn, tick_id, status, "summary")
        return tick_id

    tick([("PROJ-1", "needs_author")])
    conn.execute("UPDATE decisions SET created_at = '2020-01-01T00:00:00.000Z'")
    tick([("PROJ-1", "needs_author"), ("PROJ-2", "multi_repo")])
    tick([("PROJ-9", "needs_author")], status=TickStatus.OVERSEER_FAILED)  # a failed tick does not replace the list

    items = attention.current(conn)
    assert [(i.ticket_key, i.reason) for i in items] == [("PROJ-1", "needs_author"), ("PROJ-2", "multi_repo")]
    assert items[0].since == "2020-01-01T00:00:00.000Z"

    out = scenario.operator("status").out
    assert "Last tick: 3 overseer_failed (dry run)" in out
    assert "Attention (2):" in out
    assert "  needs_author\n    PROJ-1  " in out
    assert "d  https://example.test/PROJ-1" in out  # age in days
    assert "Running workers (0/2):\n  none" in out

    # A tick that decides nothing about a ticket did not give the overseer it, so its items stand (DESIGN §37).
    tick([])
    assert len(attention.current(conn)) == 2
    tick([], waits=["PROJ-1", "PROJ-2"])
    assert attention.current(conn) == []


@pytest.mark.parametrize("key", ["PROJ-1\n", "PROJ-1\r\n", "PROJ-1\n\n"])
def test_trailing_line_breaks_are_not_part_of_a_valid_key(scenario: Scenario, key: str) -> None:
    # `$` in a Python regex also matches before a trailing newline; validation must use the whole string.
    with scenario.ticking():
        scenario.overseer(decides(key, "wait", "r"), error=True)
        scenario.overseer(raises("PROJ-1", "needs_author\n", "d"), error=True)
        scenario.overseer(ticket_sets("PROJ-1", repo="repo", cursors={"comment": "1\n"}), error=True)
    assert scenario.conn.execute("SELECT count(*) FROM decisions").fetchone()[0] == 0
