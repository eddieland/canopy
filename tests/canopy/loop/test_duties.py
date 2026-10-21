"""The overseer's duties, checked when a tick ends (DESIGN §6 step 5), and `canopy queried`, which records the query."""

from canopy.cli.main import main
from canopy.core import db
from canopy.core.vocab import TickStatus
from canopy.loop import attention, duties
from tests.canopy.helpers import canopy, chore_toml, in_tick, seen, waits
from tests.canopy.scenario_helpers import Scenario, raises, skips_tick
from tests.conftest import CanopyEnv


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


def test_a_ticket_left_out_fails_the_tick_and_keeps_its_attention_item(scenario: Scenario) -> None:
    scenario.tick(raises("PROJ-1", "needs_reviewer", "https://example.test/pr/1"), *waits("PROJ-2"))
    # A mirror is not a decision, and PROJ-2 gets none at all.
    mirror = ["mirror", "PROJ-1", "--comment", "10", "--author", "acct-1", "--at", "2026-10-15T10:00:00Z"]
    failed = scenario.tick(canopy(*mirror, "--body", "hello"), code=1)
    assert failed.tick.status == "overseer_failed"
    assert failed.tick.summary == "overseer left duties undone: no decision for PROJ-1, PROJ-2"
    # The items of the tickets it left out are not taken as resolved.
    assert scenario.attention() == [("PROJ-1", "needs_reviewer")]


def test_a_ticket_the_query_found_is_owed_a_decision_and_kept_for_the_next_tick(scenario: Scenario) -> None:
    failed = scenario.tick(queried=["PROJ-9"], code=1)
    assert failed.tick.summary == "overseer left duties undone: no decision for PROJ-9"
    scenario.tick(*waits("PROJ-9"))
    assert [t["key"] for t in scenario.state()["tickets"]] == ["PROJ-9"]


def test_stopped_and_recently_done_tickets_are_owed_nothing(scenario: Scenario, canopy_env: CanopyEnv) -> None:
    conn = scenario.conn
    with in_tick(conn) as tick_id:
        db.set_ticket(conn, "PROJ-2", str(canopy_env.root), done=True)
        db.record_decision(conn, tick_id, "PROJ-2", "done", "merged")
        db.finish_tick(conn, tick_id, TickStatus.OK, "")
    scenario.operator("start", "PROJ-1")
    scenario.operator("stop", "PROJ-1")
    # The query still finds both open in the tracker, and the overseer names them as it found them.
    assert scenario.tick(queried=["PROJ-1", "PROJ-2"]).tick.status == "ok"


def test_a_due_chore_left_undecided_fails_the_tick(scenario: Scenario, canopy_env: CanopyEnv) -> None:
    prompt = canopy_env.home / "chores" / "build-health.md"
    prompt.parent.mkdir()
    prompt.write_text("# Build health\n")
    canopy_env.append_user(chore_toml())
    failed = scenario.tick(code=1)
    assert failed.tick.summary == "overseer left duties undone: no run or wait for chore build-health"
    scenario.tick(canopy("chore", "wait", "build-health", "--rationale", "not now"))


def test_a_tick_wide_skip_is_not_held_to_the_duties(scenario: Scenario) -> None:
    scenario.seen("PROJ-1")
    skipped = scenario.tick(skips_tick("mcp_unavailable: tracker"), queried=None, code=1)
    assert skipped.tick.status == "skipped"


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
