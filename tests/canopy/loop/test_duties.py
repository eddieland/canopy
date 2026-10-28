"""The overseer's duties, checked when a tick ends (DESIGN §6 step 5), and `canopy queried`, which records the query."""

import json
from pathlib import Path
from typing import Any, Final

import pytest

from canopy.cli.main import main
from canopy.core import db
from canopy.core.vocab import TickStatus
from canopy.loop import attention, duties
from tests.canopy.helpers import LABEL, canopy, chore_toml, in_tick, seen, waits
from tests.canopy.scenario_helpers import Scenario, dispatches, pushes, raises, skips_tick
from tests.conftest import CanopyEnv, GitPool

#: A `tracker` source the fake connector plays, so the query is read by a source (DESIGN §30).
TRACKER: Final = {"sources": {"jira": {"kind": "tracker", "cmd": "connector jira", "timeout_minutes": 1}}}
#: How a tick that owed the query and did not record it ends.
UNQUERIED: Final = "overseer left duties undone: the tracker query was due and no `canopy queried` recorded it"


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
    ticked = scenario.tick(*waits("PROJ-1", "PROJ-2"), queried=["PROJ-1", "PROJ-2"])
    assert ticked.tick.status == "ok"


def test_a_due_query_with_no_record_fails_the_tick_and_stays_due(scenario: Scenario) -> None:
    failed = scenario.tick(queried=None, code=1)
    assert failed.tick.status == "overseer_failed"
    assert "no `canopy queried` recorded it" in failed.tick.summary
    # Not counted as run: the next tick's block says it is due again.
    scenario.configures(tracker={"query_every_minutes": 60})
    scenario.tick()
    assert scenario.state()["query_due"] is True


def test_a_query_not_due_needs_no_record(scenario: Scenario) -> None:
    scenario.configures(tracker={"query_every_minutes": 60})
    ticks = [scenario.tick(), scenario.tick()]
    assert [(t.tick.query_due, t.tick.status) for t in ticks] == [(True, "ok"), (False, "ok")]


def test_a_query_a_source_read_is_recorded_by_the_harness_and_owes_no_canopy_queried(
    scenario: Scenario,
    tracker: Path,
) -> None:
    reads(tracker, query=["PROJ-9", "PROJ-2", "PROJ-9"], lines=[observed("PROJ-2")])
    scenario.seen("PROJ-2")
    ticked = scenario.tick(*waits("PROJ-2"), queried=None)
    assert ticked.tick.status == "ok"
    # Recorded before the overseer ran, as `canopy queried` would, each ticket touched into the journal.
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
    failed = scenario.tick(queried=None, code=1)
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
    """The overseer reads no tracker where a source does (DESIGN §39): it owes no `canopy queried` for it to run."""
    reads(tracker, **run)
    ticked = scenario.tick(queried=None)
    assert (ticked.tick.status, ticked.tick.query_due) == ("ok", False)
    assert ticked.actions == ["attention:connector_failed"]
    # Not counted as run, so the next tick runs it, once a read is whole.
    scenario.configures(tracker={"query_every_minutes": 60})
    reads(tracker, query=["PROJ-9"])
    ticked = scenario.tick(queried=None)
    assert ticked.tick.query_due is True
    assert "queried" in ticked.actions


def test_a_query_read_longer_ago_than_its_age_is_not_run(scenario: Scenario, tracker: Path) -> None:
    reads(tracker, query=[])
    scenario.tick(queried=None)
    scenario.time_passes(minutes=31)
    reads(tracker, end=None)
    ticked = scenario.tick(queried=None)
    assert (ticked.tick.status, ticked.tick.query_due) == ("ok", False)
    assert "queried" not in ticked.actions


def test_the_overseer_may_record_no_query_and_skip_no_tick_tracker_unsupported_where_a_source_reads(
    scenario: Scenario,
    tracker: Path,
) -> None:
    reads(tracker, query=[])
    refused = scenario.overseer("queried", "PROJ-1", code=1)
    assert "a `tracker` source reads the query" in refused.err
    refused = scenario.overseer("decide", "skip", "--rationale", "tracker_unsupported: no labels", code=1)
    assert "no tick is skipped 'tracker_unsupported'" in refused.err
    # A GitHub outage is still one the overseer may skip a tick over.
    scenario.overseer("decide", "skip", "--rationale", "mcp_unavailable: github")


def test_a_query_not_due_is_not_recorded_though_a_source_read_it(scenario: Scenario, tracker: Path) -> None:
    scenario.configures(tracker={"query_every_minutes": 60})
    reads(tracker, query=["PROJ-9"])
    ticks = [scenario.tick(*waits("PROJ-9"), queried=None), scenario.tick(*waits("PROJ-9"), queried=None)]
    assert [(t.tick.query_due, sorted(t.actions)) for t in ticks] == [(True, ["queried", "wait"]), (False, ["wait"])]


def test_a_ticket_left_out_fails_the_tick_and_keeps_its_attention_item(scenario: Scenario) -> None:
    scenario.tick(raises("PROJ-1", "needs_author", "https://example.test/pr/1"), *waits("PROJ-2"))
    # A phase is not a decision, and PROJ-2 gets none at all.
    failed = scenario.tick(canopy("ticket", "set", "PROJ-1", "--phase", "approved"), code=1)
    assert failed.tick.status == "overseer_failed"
    assert failed.tick.summary == "overseer left duties undone: no decision for PROJ-1, PROJ-2"
    # The items of the tickets it left out are not taken as resolved.
    assert scenario.attention() == [("PROJ-1", "needs_author")]


def test_a_ticket_the_query_found_is_owed_a_decision_and_kept_for_the_next_tick(scenario: Scenario) -> None:
    failed = scenario.tick(queried=["PROJ-9"], code=1)
    assert failed.tick.summary == "overseer left duties undone: no decision for PROJ-9"
    scenario.tick(*waits("PROJ-9"))
    assert [t["key"] for t in scenario.state()["tickets"]] == ["PROJ-9"]


def test_stopped_and_recently_done_tickets_are_owed_nothing(scenario: Scenario, canopy_env: CanopyEnv) -> None:
    conn = scenario.conn
    with in_tick(conn) as tick_id:
        db.record_decision(conn, tick_id, None, duties.QUERIED_ACTION, duties.queried_rationale(["PROJ-2"]))
        db.set_ticket(conn, "PROJ-2", str(canopy_env.root), done=True)
        db.record_decision(conn, tick_id, "PROJ-2", "done", "merged")
        db.finish_tick(conn, tick_id, TickStatus.OK, "")
    scenario.operator("start", "PROJ-1")
    scenario.operator("stop", "PROJ-1")
    # The query still finds both open in the tracker, and the overseer names them as it found them.
    assert scenario.tick(queried=["PROJ-1", "PROJ-2"]).tick.status == "ok"


def test_a_done_ticket_the_last_query_left_out_is_owed_a_decision_once_found(
    scenario: Scenario,
    canopy_env: CanopyEnv,
) -> None:
    # Reopened, or labeled again, after the query stopped finding it: the overseer reads it again (DESIGN §7).
    with in_tick(scenario.conn) as tick_id:
        db.set_ticket(scenario.conn, "PROJ-2", str(canopy_env.root), done=True)
        db.record_decision(scenario.conn, tick_id, "PROJ-2", "done", "merged")
        db.finish_tick(scenario.conn, tick_id, TickStatus.OK, "")
    failed = scenario.tick(queried=["PROJ-2"], code=1)
    assert failed.tick.summary == "overseer left duties undone: no decision for PROJ-2"


def test_a_due_chore_left_undecided_fails_the_tick(scenario: Scenario, canopy_env: CanopyEnv) -> None:
    prompt = canopy_env.home / "chores" / "build-health.md"
    prompt.parent.mkdir()
    prompt.write_text("# Build health\n")
    canopy_env.append_user(chore_toml(extra='when = "Weekdays only."\n'))
    failed = scenario.tick(code=1)
    assert failed.tick.summary == "overseer left duties undone: no run or wait for chore build-health"
    scenario.tick(canopy("chore", "wait", "build-health", "--rationale", "not now"))


def test_a_tick_wide_skip_is_not_held_to_the_duties(scenario: Scenario) -> None:
    scenario.seen("PROJ-1")
    skipped = scenario.tick(skips_tick("mcp_unavailable: tracker"), queried=None, code=1)
    assert skipped.tick.status == "skipped"


def test_a_tick_wide_skip_keeps_what_the_overseer_started_before_it(scenario: Scenario, git_pool: GitPool) -> None:
    # An outage of one server does not hold work that needs nothing from it (DESIGN §15): the run stands.
    scenario.seen("PROJ-1", "PROJ-2")
    skipped = scenario.tick(
        dispatches("PROJ-1"),
        skips_tick("mcp_unavailable: tracker"),
        worker=pushes(),
        queried=None,
        code=1,
    )
    assert skipped.tick.status == "skipped"
    # The dispatch's decision is recorded as the tick starts it, once the overseer's run has ended (DESIGN §40).
    assert skipped.actions == ["skip", "dispatch:implement"]
    assert [r.row["status"] for r in skipped.runs] == ["done"]
    assert git_pool.remote_head("agent/PROJ-1-work") is not None


def test_decisions_before_the_overseer_ran_are_the_harnesss(canopy_env: CanopyEnv) -> None:
    conn = canopy_env.journal()
    with in_tick(conn) as tick_id:
        seen(conn, canopy_env, "PROJ-1", "PROJ-2")
        db.record_decision(conn, tick_id, "PROJ-1", f"{attention.ACTION_PREFIX}crashed", "run 1 crashed")
        owed = duties.owed(
            conn,
            tick_id,
            query_due=False,
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
            query_due=False,
            tickets=db.open_tickets(conn),
            stopped=[],
            recently_done=[],
            chores=[],
        )
        assert duties.undone(conn, tick_id, owed) == [f"no decision for {', '.join(keys[:10])} and 2 more"]


def test_queried_records_the_query_and_touches_each_ticket(scenario: Scenario) -> None:
    conn = scenario.conn
    with scenario.ticking() as tick_id:
        scenario.overseer("queried", "PROJ-3", "PROJ-1", "PROJ-3")
        scenario.overseer("queried")
    recorded = [(d.ticket_key, d.action, d.rationale) for d in db.decisions_for_tick(conn, tick_id)]
    assert recorded == [
        (None, "queried", "the query returned these open tickets: PROJ-3 PROJ-1"),
        (None, "queried", "the query returned no open ticket"),
    ]
    assert duties.queried_keys(recorded[0][2]) == ["PROJ-3", "PROJ-1"]
    assert duties.queried_keys(recorded[1][2]) == []
    assert [t.key for t in db.open_tickets(conn)] == ["PROJ-1", "PROJ-3"]


def test_queried_refuses_outside_a_tick_a_bad_key_and_a_result_too_long_for_one_call(scenario: Scenario) -> None:
    conn = scenario.conn
    assert main(["queried", "PROJ-1"]) == 1  # no tick named: not the overseer's
    with scenario.ticking() as tick_id:
        scenario.overseer("queried", "PROJ-1;rm", code=2)
        scenario.overseer("queried", *(f"PROJ-{n}" for n in range(300)), code=2)
    assert db.decisions_for_tick(conn, tick_id) == []
    assert db.open_tickets(conn) == []
