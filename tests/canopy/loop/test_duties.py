"""The overseer's duties, checked when a tick ends (DESIGN §6 step 5), and the query the harness records for it."""

import json
from pathlib import Path
from typing import Any

import pytest

from canopy.core import db
from canopy.core.vocab import TickStatus
from canopy.loop import attention, duties
from tests.canopy.helpers import LABEL, canopy, chore_toml, in_tick, seen, waits
from tests.canopy.scenario_helpers import Scenario, raises
from tests.conftest import TRACKER_SOURCE, CanopyEnv

#: A `tracker` source the fake connector plays, so the query is read by a source (DESIGN §30).
TRACKER = {"sources": {"jira": {"kind": "tracker", "cmd": "connector jira", "timeout_minutes": 1}}}


@pytest.fixture
def tracker(scenario: Scenario, connector_state: Path) -> Path:
    """A `tracker` source configured. Returns the fake connector's state, which reads everything asked until set."""
    scenario.configures("private", connect=TRACKER)
    return connector_state


def reads(state: Path, **jira: Any) -> None:  # noqa: ANN401 - the fake connector's keys, as JSON
    """Have the `tracker` source answer as `jira` says: `query=[...]` is the query's result, `end=None` cuts it off."""
    state.write_text(json.dumps({"jira": jira}))


def observed(key: str) -> dict[str, object]:
    """The `tracker` source's line for `key`, open with the queue label."""
    return {"kind": "ticket", "key": key, "title": key, "state": "open", "labels": [{"name": LABEL}]}


def test_a_tick_that_does_every_duty_closes_ok(scenario: Scenario) -> None:
    scenario.seen("PROJ-1")
    ticked = scenario.tick(*waits("PROJ-1", "PROJ-2"))
    assert ticked.tick.status == "ok"


def test_a_query_not_due_needs_no_record(scenario: Scenario) -> None:
    scenario.configures(tracker={"query_every_minutes": 60})
    ticks = [scenario.tick(), scenario.tick()]
    assert [(t.tick.query_due, t.tick.status) for t in ticks] == [(True, "ok"), (False, "ok")]


def test_a_query_a_source_read_is_recorded_by_the_harness(
    scenario: Scenario,
    tracker: Path,
) -> None:
    reads(tracker, query=["PROJ-9", "PROJ-2", "PROJ-9"], lines=[observed("PROJ-2")])
    scenario.seen("PROJ-2")
    ticked = scenario.tick(*waits("PROJ-2"))
    assert ticked.tick.status == "ok"
    # Recorded before the overseer ran, each ticket touched into the journal.
    assert [(d.action, d.rationale) for d in ticked.decisions if d.action == "queried"] == [
        ("queried", "the query returned these open tickets: PROJ-9 PROJ-2"),
    ]
    assert scenario.state()["observations"]["query"]["result"] == ["PROJ-9", "PROJ-2", "PROJ-9"]
    # One the source has not read yet waits for the read that does, by the harness (DESIGN §39).
    assert [t["key"] for t in scenario.state()["tickets"]] == ["PROJ-2"]
    assert [h["ticket"] for h in scenario.state()["harness"]] == ["PROJ-9"]
    assert duties.last_queried(scenario.conn) == {"PROJ-2", "PROJ-9"}


def test_each_ticket_a_source_read_query_returned_is_owed_a_decision(scenario: Scenario, tracker: Path) -> None:
    reads(tracker, query=["PROJ-9"], lines=[observed("PROJ-9")])
    scenario.seen("PROJ-9")
    failed = scenario.tick(code=1)
    assert failed.tick.summary == "overseer left duties undone: no decision for PROJ-9"


@pytest.mark.parametrize(
    "run",
    [
        pytest.param({"end": None}, id="failed"),
        pytest.param({"end": {"tickets": []}}, id="query-not-read-to-its-end"),
    ],
)
def test_a_query_no_source_read_this_tick_is_not_run_and_stays_due(
    scenario: Scenario,
    tracker: Path,
    run: dict[str, Any],
) -> None:
    """The overseer reads no tracker (DESIGN §39): a query the source did not read is not run, and owes it nothing."""
    reads(tracker, **run)
    ticked = scenario.tick()
    assert (ticked.tick.status, ticked.tick.query_due) == ("ok", False)
    assert ticked.actions == ["attention:connector_failed"]
    # Not counted as run, so the next tick runs it, once a read is whole.
    scenario.configures(tracker={"query_every_minutes": 60})
    reads(tracker, query=["PROJ-9"])
    ticked = scenario.tick()
    assert ticked.tick.query_due is True
    assert "queried" in ticked.actions


def test_a_query_read_longer_ago_than_its_age_is_not_run(scenario: Scenario, tracker: Path) -> None:
    reads(tracker, query=[])
    scenario.tick()
    scenario.time_passes(minutes=31)
    reads(tracker, end=None)
    ticked = scenario.tick()
    assert (ticked.tick.status, ticked.tick.query_due) == ("ok", False)
    assert "queried" not in ticked.actions


def test_the_overseer_records_no_query_and_skips_no_tick(scenario: Scenario) -> None:
    """It reads no tracker nor GitHub, which the sources read (DESIGN §39): the query is canopy's, no outage its own."""
    with scenario.ticking() as tick_id:
        refused = scenario.overseer("decide", "skip", "--rationale", "mcp_unavailable: github", code=2)
        assert "expected KEY ACTION for each of 1 --rationale; got 1 arguments" in refused.err
        assert "No such command 'queried'" in scenario.overseer("queried", "PROJ-1", code=2).err
    assert db.decisions_for_tick(scenario.conn, tick_id) == []


def test_a_query_not_due_is_not_recorded_though_a_source_read_it(scenario: Scenario, tracker: Path) -> None:
    scenario.configures(tracker={"query_every_minutes": 60})
    reads(tracker, query=["PROJ-9"])
    ticks = [scenario.tick(*waits("PROJ-9")), scenario.tick(*waits("PROJ-9"))]
    assert [(t.tick.query_due, sorted(t.actions)) for t in ticks] == [(True, ["queried", "wait"]), (False, ["wait"])]


def test_a_ticket_left_out_fails_the_tick_and_keeps_its_attention_item(scenario: Scenario) -> None:
    scenario.tick(raises("PROJ-1", "needs_author", "https://example.test/pr/1"), *waits("PROJ-2"))
    # A phase is not a decision, and PROJ-2 gets none at all.
    failed = scenario.tick(canopy("ticket", "set", "PROJ-1", "--phase", "approved"), code=1)
    assert failed.tick.status == "overseer_failed"
    assert failed.tick.summary == "overseer left duties undone: no decision for PROJ-1, PROJ-2"
    # The items of the tickets it left out are not taken as resolved.
    assert scenario.attention() == [("PROJ-1", "needs_author")]


def test_a_ticket_the_query_found_is_owed_a_decision_and_kept_for_the_next_tick(
    scenario: Scenario,
    connector_state: Path,
) -> None:
    # The tests' tracker source: its query finds PROJ-9, which it reads whole on the next tick's read (DESIGN §39).
    connector_state.write_text(json.dumps({TRACKER_SOURCE: {"query": ["PROJ-9"]}}))
    found = scenario.tick()
    # It is the harness's to wait on until then, the overseer left nothing.
    assert (found.actions, found.tick.overseer_ran) == (["wait", "queried"], False)
    failed = scenario.tick(code=1)
    assert failed.tick.summary == "overseer left duties undone: no decision for PROJ-9"
    scenario.tick(*waits("PROJ-9"))
    assert [t["key"] for t in scenario.state()["tickets"]] == ["PROJ-9"]


def test_stopped_and_recently_done_tickets_are_owed_nothing(
    scenario: Scenario,
    canopy_env: CanopyEnv,
    connector_state: Path,
) -> None:
    conn = scenario.conn
    with in_tick(conn) as tick_id:
        db.record_decision(conn, tick_id, None, duties.QUERIED_ACTION, duties.queried_rationale(["PROJ-2"]))
        db.set_ticket(conn, "PROJ-2", str(canopy_env.root), done=True)
        db.record_decision(conn, tick_id, "PROJ-2", "done", "merged")
        db.finish_tick(conn, tick_id, TickStatus.OK, "")
    scenario.operator("start", "PROJ-1")
    scenario.operator("stop", "PROJ-1")
    # The query still finds both open in the tracker, and the harness records them as it found them.
    connector_state.write_text(json.dumps({TRACKER_SOURCE: {"query": ["PROJ-1", "PROJ-2"]}}))
    ticked = scenario.tick()
    assert ticked.tick.status == "ok"
    assert duties.queried_keys(next(d.rationale for d in ticked.decisions if d.action == "queried")) == [
        "PROJ-1",
        "PROJ-2",
    ]


def test_a_done_ticket_the_last_query_left_out_is_owed_a_decision_once_found(
    scenario: Scenario,
    canopy_env: CanopyEnv,
    connector_state: Path,
) -> None:
    # Reopened, or labeled again, after the query stopped finding it: the overseer reads it again (DESIGN §7).
    with in_tick(scenario.conn) as tick_id:
        db.set_ticket(scenario.conn, "PROJ-2", str(canopy_env.root), done=True)
        db.record_decision(scenario.conn, tick_id, "PROJ-2", "done", "merged")
        db.finish_tick(scenario.conn, tick_id, TickStatus.OK, "")
    connector_state.write_text(json.dumps({TRACKER_SOURCE: {"query": ["PROJ-2"]}}))
    failed = scenario.tick(code=1)
    assert failed.tick.summary == "overseer left duties undone: no decision for PROJ-2"


def test_a_due_chore_left_undecided_fails_the_tick(scenario: Scenario, canopy_env: CanopyEnv) -> None:
    prompt = canopy_env.home / "chores" / "build-health.md"
    prompt.parent.mkdir()
    prompt.write_text("# Build health\n")
    canopy_env.append_user(chore_toml(extra='when = "Weekdays only."\n'))
    failed = scenario.tick(code=1)
    assert failed.tick.summary == "overseer left duties undone: no run or wait for chore build-health"
    scenario.tick(canopy("chore", "wait", "build-health", "--rationale", "not now"))


def test_decisions_before_the_overseer_ran_are_the_harnesss(canopy_env: CanopyEnv) -> None:
    conn = canopy_env.journal()
    with in_tick(conn) as tick_id:
        seen(conn, canopy_env, "PROJ-1", "PROJ-2")
        db.record_decision(conn, tick_id, "PROJ-1", f"{attention.ACTION_PREFIX}crashed", "run 1 crashed")
        owed = duties.owed(
            conn,
            tick_id,
            tickets=db.open_tickets(conn),
            stopped=[],
            recently_done=[],
            chores=[],
        )
        db.record_decision(conn, tick_id, "PROJ-2", "wait", "running")
        assert duties.undone(conn, tick_id, owed) == ["no decision for PROJ-1"]


def test_a_long_list_of_tickets_left_out_is_counted(canopy_env: CanopyEnv) -> None:
    conn = canopy_env.journal()
    keys = [f"PROJ-{n:02}" for n in range(12)]
    with in_tick(conn) as tick_id:
        seen(conn, canopy_env, *keys)
        owed = duties.owed(
            conn,
            tick_id,
            tickets=db.open_tickets(conn),
            stopped=[],
            recently_done=[],
            chores=[],
        )
        assert duties.undone(conn, tick_id, owed) == [f"no decision for {', '.join(keys[:10])} and 2 more"]
