"""The overseer's duties, checked when a tick ends (DESIGN §6 step 5), and `canopy queried`, which records the query."""

from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import db
from canopy.core.vocab import TickStatus
from canopy.loop import attention, duties
from tests.canopy.helpers import canopy, chore_toml, in_tick, last_tick, operator, overseer_does, seen, state_block
from tests.conftest import CanopyEnv


def wait(key: str) -> list[str]:
    return canopy("decide", key, "wait", "--rationale", "nothing new")


@pytest.mark.usefixtures("treehouse_state", "agent_log")
def test_a_tick_that_does_every_duty_closes_ok(canopy_env: CanopyEnv) -> None:
    conn = canopy_env.journal()
    seen(conn, canopy_env, "PROJ-1")
    with overseer_does(wait("PROJ-1"), wait("PROJ-2"), queried='["PROJ-1", "PROJ-2"]'):
        assert main(["tick"]) == 0
    assert last_tick(conn).status == "ok"


@pytest.mark.usefixtures("treehouse_state")
def test_a_due_query_with_no_record_fails_the_tick_and_stays_due(canopy_env: CanopyEnv, agent_log: Path) -> None:
    conn = canopy_env.journal()
    with overseer_does(queried="skip"):
        assert main(["tick"]) == 1
    failed = last_tick(conn)
    assert failed.status == "overseer_failed"
    assert "no `canopy queried` recorded it" in failed.summary
    # Not counted as run: the next tick's block says it is due again.
    canopy_env.write_user(
        canopy_env.user_file.read_text().replace("[tracker]\n", "[tracker]\nquery_every_minutes = 60\n")
    )
    with overseer_does():
        assert main(["tick"]) == 0
    assert state_block(agent_log)["query_due"] is True


@pytest.mark.usefixtures("treehouse_state", "agent_log")
def test_a_query_not_due_needs_no_record(canopy_env: CanopyEnv) -> None:
    canopy_env.write_user(
        canopy_env.user_file.read_text().replace("[tracker]\n", "[tracker]\nquery_every_minutes = 60\n")
    )
    conn = canopy_env.journal()
    with overseer_does():
        assert main(["tick"]) == 0
        assert main(["tick"]) == 0
    assert [(r["query_due"], r["status"]) for r in conn.execute("SELECT * FROM ticks ORDER BY id")] == [
        (1, "ok"),
        (0, "ok"),
    ]


@pytest.mark.usefixtures("treehouse_state", "agent_log")
def test_a_ticket_left_out_fails_the_tick_and_keeps_its_attention_item(canopy_env: CanopyEnv) -> None:
    conn = canopy_env.journal()
    needs_reviewer = canopy("attention", "PROJ-1", "needs_reviewer", "--detail", "https://example.test/pr/1")
    with overseer_does(needs_reviewer, wait("PROJ-2")):
        assert main(["tick"]) == 0
    # A mirror is not a decision, and PROJ-2 gets none at all.
    mirror = ["mirror", "PROJ-1", "--comment", "10", "--author", "acct-1", "--at", "2026-10-15T10:00:00Z"]
    with overseer_does(canopy(*mirror, "--body", "hello")):
        assert main(["tick"]) == 1
    failed = last_tick(conn)
    assert failed.status == "overseer_failed"
    assert failed.summary == "overseer left duties undone: no decision for PROJ-1, PROJ-2"
    # The items of the tickets it left out are not taken as resolved.
    assert [(i.ticket_key, i.reason) for i in attention.current(conn)] == [("PROJ-1", "needs_reviewer")]


@pytest.mark.usefixtures("treehouse_state")
def test_a_ticket_the_query_found_is_owed_a_decision_and_kept_for_the_next_tick(
    canopy_env: CanopyEnv, agent_log: Path
) -> None:
    conn = canopy_env.journal()
    with overseer_does(queried='["PROJ-9"]'):
        assert main(["tick"]) == 1
    assert last_tick(conn).summary == "overseer left duties undone: no decision for PROJ-9"
    with overseer_does(wait("PROJ-9")):
        assert main(["tick"]) == 0
    assert [t["key"] for t in state_block(agent_log)["tickets"]] == ["PROJ-9"]


@pytest.mark.usefixtures("treehouse_state", "agent_log")
def test_stopped_and_recently_done_tickets_are_owed_nothing(canopy_env: CanopyEnv) -> None:
    conn = canopy_env.journal()
    repo = str(canopy_env.root)
    with in_tick(conn) as tick_id:
        db.set_ticket(conn, "PROJ-2", repo, done=True)
        db.record_decision(conn, tick_id, "PROJ-2", "done", "merged")
        db.finish_tick(conn, tick_id, TickStatus.OK, "")
    assert operator("start", "PROJ-1") == 0
    assert operator("stop", "PROJ-1") == 0
    # The query still finds both open in the tracker, and the overseer names them as it found them.
    with overseer_does(queried='["PROJ-1", "PROJ-2"]'):
        assert main(["tick"]) == 0
    assert last_tick(conn).status == "ok"


@pytest.mark.usefixtures("treehouse_state", "agent_log")
def test_a_due_chore_left_undecided_fails_the_tick(canopy_env: CanopyEnv) -> None:
    prompt = canopy_env.home / "chores" / "build-health.md"
    prompt.parent.mkdir()
    prompt.write_text("# Build health\n")
    canopy_env.append_user(chore_toml())
    conn = canopy_env.journal()
    with overseer_does():
        assert main(["tick"]) == 1
    assert last_tick(conn).summary == "overseer left duties undone: no run or wait for chore build-health"
    with overseer_does(canopy("chore", "wait", "build-health", "--rationale", "not now")):
        assert main(["tick"]) == 0


@pytest.mark.usefixtures("treehouse_state", "agent_log")
def test_a_tick_wide_skip_is_not_held_to_the_duties(canopy_env: CanopyEnv) -> None:
    conn = canopy_env.journal()
    seen(conn, canopy_env, "PROJ-1")
    with overseer_does(canopy("decide", "skip", "--rationale", "mcp_unavailable: tracker"), queried="skip"):
        assert main(["tick"]) == 1
    assert last_tick(conn).status == "skipped"


def test_decisions_before_the_overseer_ran_are_the_harnesss(canopy_env: CanopyEnv) -> None:
    conn = canopy_env.journal()
    with in_tick(conn) as tick_id:
        seen(conn, canopy_env, "PROJ-1", "PROJ-2")
        db.record_decision(conn, tick_id, "PROJ-1", f"{attention.ACTION_PREFIX}crashed", "run 1 crashed")
        owed = duties.owed(
            conn, tick_id, query_due=False, tickets=db.open_tickets(conn), stopped=[], recently_done=[], chores=[]
        )
        db.record_decision(conn, tick_id, "PROJ-2", "wait", "running")
        assert duties.undone(conn, tick_id, owed) == ["no decision for PROJ-1"]


def test_a_long_list_of_tickets_left_out_is_counted(canopy_env: CanopyEnv) -> None:
    conn = canopy_env.journal()
    keys = [f"PROJ-{n:02}" for n in range(12)]
    with in_tick(conn) as tick_id:
        seen(conn, canopy_env, *keys)
        owed = duties.owed(
            conn, tick_id, query_due=False, tickets=db.open_tickets(conn), stopped=[], recently_done=[], chores=[]
        )
        assert duties.undone(conn, tick_id, owed) == [f"no decision for {', '.join(keys[:10])} and 2 more"]


def test_queried_records_the_query_and_touches_each_ticket(canopy_env: CanopyEnv) -> None:
    conn = canopy_env.journal()
    with in_tick(conn) as tick_id:
        assert main(["queried", "PROJ-3", "PROJ-1", "PROJ-3"]) == 0
        assert main(["queried"]) == 0
        recorded = [(d.ticket_key, d.action, d.rationale) for d in db.decisions_for_tick(conn, tick_id)]
    assert recorded == [
        (None, "queried", "the query returned these open tickets: PROJ-3 PROJ-1"),
        (None, "queried", "the query returned no open ticket"),
    ]
    assert duties.queried_keys(recorded[0][2]) == ["PROJ-3", "PROJ-1"]
    assert duties.queried_keys(recorded[1][2]) == []
    assert [t.key for t in db.open_tickets(conn)] == ["PROJ-1", "PROJ-3"]


def test_queried_refuses_outside_a_tick_a_bad_key_and_a_result_too_long_for_one_call(canopy_env: CanopyEnv) -> None:
    conn = canopy_env.journal()
    assert main(["queried", "PROJ-1"]) == 1
    with in_tick(conn) as tick_id:
        assert main(["queried", "PROJ-1;rm"]) == 2
        assert main(["queried", *(f"PROJ-{n}" for n in range(300))]) == 2
        assert db.decisions_for_tick(conn, tick_id) == []
    assert db.open_tickets(conn) == []
