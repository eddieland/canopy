"""The harness decides what needs no judgment (DESIGN §37, ROADMAP M38).

The tests cover its decisions over journals written by hand, what it leaves whole to the overseer, and `decided` for
what the overseer records about a ticket it took.

A ticket the harness takes is one every row of whose derivation is in `harness.ROWS`, rows it reads from its own journal
alone, so the cases here write the derivation's observations fresh at `NOW` and derive at it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from canopy.cli.main import main
from canopy.core import db
from canopy.core.vocab import Decider, Phase, RunStatus, TickStatus
from canopy.loop import attention, harness, phases
from tests.canopy.helpers import (
    KEY,
    LABEL,
    UNOBSERVED,
    WORKER_PR,
    context,
    decisions,
    in_tick,
    mcp_session,
    messages,
    operator,
    running_run,
    tool_call,
    waits,
)
from tests.canopy.observation_helpers import (
    FRESH,
    NOW,
    OLD,
    PR,
    TRACKER,
    branches_read,
    check,
    held,
    observe_pr,
    observe_ticket,
    query_read,
)
from tests.canopy.scenario_helpers import dispatches, pushes, raises

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from tests.canopy.scenario_helpers import Scenario
    from tests.conftest import CanopyEnv, GitPool

#: What the harness records for a ticket a worker of which is running.
RUNNING = harness.Decision(KEY, Phase.RUNNING, "wait", "running: a worker of it is running")


@pytest.fixture
def observed(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> sqlite3.Connection:
    """A tracker source configured, and KEY held and observed open with the queue label at FRESH.

    Returns the journal.
    """
    canopy_env.configure(canopy_env.user_file, TRACKER)
    held(canopy_env, conn, KEY)
    observe_ticket(conn)
    conn.commit()
    return conn


def test_a_ticket_whose_worker_is_running_is_the_harnesss(canopy_env: CanopyEnv, observed: sqlite3.Connection) -> None:
    running_run(context(canopy_env), KEY, private=False)
    assert decided(canopy_env) == [RUNNING]


def test_a_private_tickets_unanswered_question_is_the_harnesss(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    # From the journal alone (DESIGN §22): its latest run ended `blocked`, and the operator has not answered. Its PR
    # closed unmerged, so its unit holds no row.
    assert operator("start", KEY) == 0
    ctx = context(canopy_env)
    run_id = running_run(ctx, KEY)
    conn.execute("UPDATE runs SET status = ?, ended_at = ? WHERE id = ?", (RunStatus.BLOCKED, FRESH, run_id))
    db.set_unit(conn, KEY, str(canopy_env.root), "repo", pr_url=PR)
    observe_pr(conn)
    conn.execute("UPDATE observed_prs SET state = 'closed'")
    conn.commit()
    question = "needs_human: its latest run asked the operator, who has not answered"
    assert decided(canopy_env) == [harness.Decision(KEY, Phase.NEEDS_HUMAN, "wait", question)]


def test_a_public_tickets_needs_human_rests_on_the_tracker_so_is_left_to_the_overseer(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
) -> None:
    # The tracker's label, which a connector observes: a row not enabled stays the overseer's (DESIGN §37).
    observed.execute(
        "UPDATE observed_tickets SET labels = ?",
        (f'[{{"name": "{LABEL}", "added_at": null}}, {{"name": "needs-human", "added_at": "{FRESH}"}}]',),
    )
    branches_read(observed, at=FRESH)
    observed.execute(
        "INSERT INTO observed_branches (repository, name, head_sha, observed_at) VALUES ('repo', ?, 'abc', ?)",
        (f"agent/{KEY}-work", FRESH),
    )
    observed.commit()
    assert held_rows(canopy_env) == {(KEY, None): (Phase.NEEDS_HUMAN,), (KEY, "repo"): (Phase.PUSHED_NO_PR,)}
    assert decided(canopy_env) == []


def test_one_row_of_judgment_leaves_the_whole_ticket_to_the_overseer(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
) -> None:
    # Running, and its unit's PR is green with no reviewer: the harness raises `needs_reviewer`, but `green_unreviewed`
    # is not a row it decides, so the ticket's decision is the overseer's (DESIGN §37).
    running_run(context(canopy_env), KEY, private=False)
    db.set_unit(observed, KEY, str(canopy_env.root), "repo", pr_url=PR)
    observe_pr(observed)
    check(observed, "build", "completed", "success")
    observed.commit()
    assert held_rows(canopy_env)[KEY, "repo"] == (Phase.GREEN_UNREVIEWED,)
    assert decided(canopy_env) == []


@pytest.mark.parametrize(
    "statement",
    [
        pytest.param("UPDATE observed_tickets SET labels = '[]'", id="not-a-candidate"),
        pytest.param("UPDATE observed_tickets SET state = 'closed'", id="closed"),
    ],
)
def test_a_running_ticket_not_fresh_open_and_labeled_is_left_to_the_overseer(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
    statement: str,
) -> None:
    running_run(context(canopy_env), KEY, private=False)
    observed.execute(statement)
    observed.commit()
    assert decided(canopy_env) == []


@pytest.mark.parametrize("running", [False, True])
def test_a_ticket_the_tracker_source_left_stale_is_the_harnesss_wait_naming_what_is_old(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
    *,
    running: bool,
) -> None:
    """The overseer reads no tracker where a source does (DESIGN §39): the ticket waits for a whole read."""
    if running:
        running_run(context(canopy_env), KEY, private=False)
    db.change_ticket(observed, KEY, "phase", Phase.CI_RED)
    observed.execute("UPDATE observed_tickets SET observed_at = '2026-10-20T10:00:00.000Z'")
    observed.commit()
    [decision] = decided(canopy_env)
    assert (decision.key, decision.phase, decision.action) == (KEY, None, "wait")
    assert decision.rationale.startswith(f"stale: {KEY} last observed 2026-10-20T10:00:00.000Z")
    assert decision.rationale.endswith("; it waits for the tracker source to read it again")
    # No row was derived, so its phase stays as it was.
    with in_tick(observed, ends_ok=True) as tick_id:
        harness.record(observed, tick_id, str(canopy_env.root), [decision])
    assert observed.execute("SELECT phase FROM tickets WHERE key = ?", (KEY,)).fetchone()[0] == Phase.CI_RED
    assert [d.ticket_key for d in harness.recorded(observed, tick_id)] == [KEY]


def test_a_ticket_marked_done_is_not_waited_on_though_the_query_finds_it_stale(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
) -> None:
    """Owed nothing, as `recently_done` is (DESIGN §7)."""
    db.set_ticket(observed, KEY, str(canopy_env.root), done=True)
    query_read(observed, [KEY])
    observed.execute("UPDATE observed_tickets SET observed_at = '2026-10-20T10:00:00.000Z'")
    observed.commit()
    assert decided(canopy_env) == []


@pytest.mark.parametrize(
    ("stale", "why"),
    [
        pytest.param("old", f"{PR} last observed {OLD}", id="pr-old"),
        pytest.param("missing", f"{PR} never observed", id="pr-missing"),
        pytest.param("branches", "branches of repo not observed since 2026-10-20T11:30:00.000Z", id="branches"),
    ],
)
def test_a_candidate_the_vcs_source_left_stale_is_the_harnesss_wait_naming_what_is_old(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
    stale: str,
    why: str,
) -> None:
    """Where a `tracker` source runs, the overseer reads no GitHub either (DESIGN §39): it waits for a whole read."""
    if stale != "branches":
        db.set_unit(observed, KEY, str(canopy_env.root), "repo", pr_url=PR)
    if stale == "old":
        observe_pr(observed, at=OLD)
    observed.commit()
    expected = harness.Decision(KEY, None, "wait", f"stale: {why}; it waits for the vcs source to read it again")
    assert decided(canopy_env) == [expected]


@pytest.mark.parametrize("running", [False, True])
def test_a_candidate_whose_unit_names_no_pr_is_the_harnesss_wait_saying_no_source_reads_it(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
    *,
    running: bool,
) -> None:
    """No source reads such a URL, nor the overseer GitHub (DESIGN §39): no outage, and the wait says so."""
    if running:
        running_run(context(canopy_env), KEY, private=False)
    db.set_unit(observed, KEY, str(canopy_env.root), "repo", pr_url=WORKER_PR)
    observed.commit()
    assert decided(canopy_env) == [harness.Decision(KEY, None, "wait", UNOBSERVED)]


@pytest.mark.parametrize(
    "held_at",
    [pytest.param("2026-10-20T11:59:30.000Z", id="held-since"), pytest.param(None, id="found-by-the-query")],
)
def test_a_candidate_read_before_canopy_held_it_is_the_harnesss_wait_for_its_comments(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    held_at: str | None,
) -> None:
    """Comments are recorded only of a ticket canopy holds (DESIGN §30): read before that, it waits a read since."""
    canopy_env.configure(canopy_env.user_file, TRACKER)
    observe_ticket(conn)
    if held_at is None:
        query_read(conn, [KEY])
    else:
        held(canopy_env, conn, KEY, at=held_at)
    conn.commit()
    why = (
        f"stale: comments of {KEY} not observed since canopy first held it; it waits for the tracker source to read it"
    )
    assert decided(canopy_env) == [harness.Decision(KEY, None, "wait", f"{why} again")]


@pytest.mark.parametrize("url", [pytest.param(PR, id="stale"), pytest.param(WORKER_PR, id="unobserved")])
def test_a_closed_ticket_whose_pr_is_stale_or_unobserved_is_left_to_the_overseer_to_mark_done(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
    url: str,
) -> None:
    """Marking it done reads nothing of GitHub's, so nothing waits on the `vcs` source (DESIGN §7)."""
    db.set_unit(observed, KEY, str(canopy_env.root), "repo", pr_url=url)
    observed.execute("UPDATE observed_tickets SET state = 'closed'")
    observed.commit()
    assert decided(canopy_env) == []


def test_a_ticket_with_an_item_the_overseer_holds_is_the_harnesss_and_the_item_stands(
    canopy_env: CanopyEnv,
    observed: sqlite3.Connection,
) -> None:
    # A tick that does not give the overseer the ticket does not end its item (DESIGN §37).
    running_run(context(canopy_env), KEY, private=False)
    with in_tick(observed, ends_ok=True) as tick_id:
        db.record_decision(observed, tick_id, KEY, "attention:needs_author", "its blocker's PR closed")
    assert decided(canopy_env) == [RUNNING]
    with in_tick(observed, ends_ok=True) as tick_id:
        harness.record(observed, tick_id, str(canopy_env.root), [RUNNING])
    assert [(i.ticket_key, i.reason) for i in attention.current(observed)] == [(KEY, "needs_author")]


def test_its_decision_is_recorded_as_its_own_with_the_phase(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    with in_tick(conn, dry_run=True) as tick_id:
        harness.record(conn, tick_id, str(canopy_env.root), [RUNNING])
    [decision] = db.decisions_for_tick(conn, tick_id)
    assert (decision.ticket_key, decision.action, decision.decider) == (KEY, "wait", Decider.HARNESS)
    assert harness.recorded(conn, tick_id) == [decision]
    assert conn.execute("SELECT phase FROM tickets WHERE key = ?", (KEY,)).fetchone()[0] == Phase.RUNNING


def test_its_attention_items_are_marked_its_own_and_are_not_its_decisions(scenario: Scenario) -> None:
    scenario.configures(connect={"sources": {"jira": {"kind": "tracker", "cmd": "false"}}})
    ticked = scenario.tick()
    [failed] = [d for d in ticked.decisions if d.action == "attention:connector_failed"]
    assert failed.decider is Decider.HARNESS
    assert harness.recorded(scenario.conn, ticked.tick.id) == []


#: What the overseer records about a ticket, through each verb's command and its tool.
VERBS = {
    "decide": (
        ["decide", KEY, "wait", "--rationale", "r"],
        {"decisions": [{"key": KEY, "action": "wait", "rationale": "r"}]},
    ),
    "dispatch": (
        ["dispatch", KEY, "--repo", "repo", "--kind", "implement", "--label", LABEL],
        {"key": KEY, "kind": "implement", "repos": ["repo"], "label": LABEL},
    ),
    "attention": (
        ["attention", KEY, "needs_author", "--detail", "d"],
        {"key": KEY, "reason": "needs_author", "detail": "d"},
    ),
    "ticket-set": (["ticket", "set", KEY, "--phase", "ready"], {"tickets": [{"key": KEY, "phase": "ready"}]}),
}


@pytest.mark.parametrize("verb", VERBS, ids=list(VERBS))
def test_what_the_overseer_records_about_a_ticket_the_harness_decided_is_refused(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    verb: str,
) -> None:
    command, arguments = VERBS[verb]
    for through in ("command", "tool"):
        with in_tick(conn) as tick_id:
            harness.record(conn, tick_id, str(canopy_env.root), [RUNNING])
            if through == "command":
                assert main(command) == 1
            else:
                said = mcp_session(tool_call(verb, **arguments)).said()
                assert said.error
                assert "refused (decided)" in said.text
            [_, (action, reason)] = decisions(conn, tick_id)
            assert action == "refused:decided"
            assert reason.startswith(f"the harness decided {KEY} this tick")
    assert conn.execute("SELECT phase FROM tickets WHERE key = ?", (KEY,)).fetchone()[0] == Phase.RUNNING
    assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_another_ticket_and_the_operators_ticket_set_are_not_refused(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
) -> None:
    with in_tick(conn) as tick_id:
        harness.record(conn, tick_id, str(canopy_env.root), [RUNNING])
        assert main(["decide", "PROJ-2", "wait", "--rationale", "r"]) == 0
        assert operator("ticket", "set", KEY, "--title", "Retry uploads") == 0
    assert [a for a, _ in decisions(conn, tick_id)] == ["wait", "wait"]


def test_decisions_in_one_call_are_refused_together_when_the_harness_decided_one(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
) -> None:
    batch = ["decide", "PROJ-2", "wait", "--rationale", "r", KEY, "wait", "--rationale", "r"]
    arguments = [
        {"key": "PROJ-2", "action": "wait", "rationale": "r"},
        {"key": KEY, "action": "wait", "rationale": "r"},
    ]
    for through in ("command", "tool"):
        with in_tick(conn) as tick_id:
            harness.record(conn, tick_id, str(canopy_env.root), [RUNNING])
            if through == "command":
                assert main(batch) == 1
            else:
                said = mcp_session(tool_call("decide", decisions=arguments)).said()
                assert said.error
                assert said.text.endswith(
                    "the refusal was recorded, and nothing else in the call: decide the rest again",
                )
            # Only the refusal is recorded: PROJ-2's wait is not, and is the overseer's to decide again.
            [_, (action, reason)] = decisions(conn, tick_id)
            assert action == "refused:decided"
            assert reason.startswith(f"the harness decided {KEY} this tick")
    assert conn.execute("SELECT count(*) FROM tickets WHERE key = 'PROJ-2'").fetchone()[0] == 0


def test_a_ticket_set_of_several_is_refused_whole_when_the_harness_decided_one(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
) -> None:
    batch = ["ticket", "set", "PROJ-2", KEY, "--phase", "ready"]
    arguments = [{"key": "PROJ-2", "phase": "ready"}, {"key": KEY, "phase": "ready"}]
    for through in ("command", "tool"):
        with in_tick(conn) as tick_id:
            harness.record(conn, tick_id, str(canopy_env.root), [RUNNING])
            if through == "command":
                assert main(batch) == 1
            else:
                said = mcp_session(tool_call("ticket-set", tickets=arguments)).said()
                assert said.error
                assert said.text.startswith(f"{KEY}: ticket set refused (decided)")
                assert said.text.endswith("nothing else in the call was recorded: set the rest again")
            # Only the refusal is recorded: PROJ-2's phase is not, and is the overseer's to set again.
            [_, (action, reason)] = decisions(conn, tick_id)
            assert action == "refused:decided"
            assert reason.startswith(f"the harness decided {KEY} this tick")
    assert conn.execute("SELECT count(*) FROM tickets WHERE key = 'PROJ-2'").fetchone()[0] == 0
    assert conn.execute("SELECT phase FROM tickets WHERE key = ?", (KEY,)).fetchone()[0] == Phase.RUNNING


def test_a_tick_leaves_a_running_ticket_to_the_harness_and_the_overseer_only_the_rest(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    # A private ticket at work, with its repository's branches read whole and none of its own pushed yet: every row
    # the derivation finds is `running`, which the harness reads from its runs.
    scenario.operator("start", KEY)
    working = scenario.starts(dispatches(label=None))
    scenario.seen("PROJ-2")
    branches_read(scenario.conn, at=db.now())
    scenario.conn.commit()
    ticked = scenario.tick(*waits("PROJ-2"))
    assert ticked.tick.status == TickStatus.OK
    [mine] = [d for d in ticked.decisions if d.ticket_key == KEY]
    assert (mine.action, mine.decider) == ("wait", Decider.HARNESS)
    state = scenario.state()
    assert state["harness"] == [{"ticket": KEY, "action": "wait", "why": RUNNING.rationale}]
    assert [t["key"] for t in state["tickets"]] == ["PROJ-2"]
    assert [t["key"] for t in state["observations"]["tickets"]] == ["PROJ-2"]
    # The query found it too: the harness decided it, so the overseer owes it nothing (DESIGN §6).
    query_read(scenario.conn, [KEY, "PROJ-2"], at=db.now())
    scenario.conn.commit()
    assert scenario.tick(*waits("PROJ-2")).tick.status == TickStatus.OK
    # One that records something about it anyway is refused, and the tick goes on.
    refused = scenario.tick(*waits(KEY, "PROJ-2"), raises(KEY, "needs_author"))
    assert refused.tick.status == TickStatus.OK
    assert [d.action for d in refused.decisions if d.ticket_key == KEY] == [
        "wait",
        "refused:decided",
        "refused:decided",
    ]
    working.finishes()
    # Its run ended: the ticket is the overseer's again.
    after = scenario.tick(*waits(KEY, "PROJ-2"))
    assert [d.decider for d in after.decisions if d.ticket_key == KEY] == [Decider.OVERSEER]


def test_a_ticket_whose_pr_no_source_reads_waits_unlisted_raising_its_item_until_the_operator_forgets_its_work(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    """No source reads its PR, nor the overseer GitHub (DESIGN §39): the harness waits, saying so, and raises it."""
    scenario.configures(tracker={"query_every_minutes": 60})
    scenario.run(worker=pushes())
    ticked = scenario.tick()
    assert (ticked.tick.status, ticked.tick.overseer_ran) == (TickStatus.OK, False)
    waited = [(d.ticket_key, d.action, d.rationale) for d in harness.recorded(scenario.conn, ticked.tick.id)]
    assert waited == [(KEY, "wait", UNOBSERVED)]
    assert scenario.attention() == [(KEY, "unobserved_pr")]
    # Its work forgotten, its unit goes with the PR, and the ticket is the overseer's again, its item gone.
    scenario.operator("forget", KEY)
    again = scenario.tick(*waits(KEY))
    assert again.tick.overseer_ran is True
    assert harness.recorded(scenario.conn, again.tick.id) == []
    assert scenario.attention() == []
    assert [t["key"] for t in scenario.state()["observations"]["tickets"]] == [KEY]


def test_an_item_the_overseer_raised_stands_while_the_harness_decides_its_ticket(
    scenario: Scenario,
    git_pool: GitPool,
    notified: Path,
) -> None:
    scenario.operator("start", KEY)
    # An item it records every tick its cause holds, not one it keeps (DESIGN §37).
    [working] = scenario.tick(dispatches(label=None), raises(KEY, "flaky_rerun"), hold=True).working
    branches_read(scenario.conn, at=db.now())
    scenario.conn.commit()
    # The overseer is not given the ticket, so it cannot record the item again; the item stands, and is not news.
    ticked = scenario.tick()
    assert [(d.action, d.decider) for d in ticked.decisions if d.ticket_key == KEY] == [("wait", Decider.HARNESS)]
    assert scenario.attention() == [(KEY, "flaky_rerun")]
    assert scenario.state()["attention"] == []
    assert len(messages(notified)) == 1
    working.finishes()
    # Given the ticket again, the overseer leaves the item out: its cause is gone.
    scenario.tick(*waits(KEY))
    assert scenario.attention() == []
    assert messages(notified)[1].startswith("canopy attention: 0 new, 1 resolved")


def test_a_dry_run_records_the_harnesss_decisions_and_starts_nothing(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.operator("start", KEY)
    working = scenario.starts(dispatches(label=None))
    branches_read(scenario.conn, at=db.now())
    scenario.conn.commit()
    ticked = scenario.tick(dry_run=True)
    assert ticked.tick.status == TickStatus.OK
    assert [(d.ticket_key, d.action, d.decider) for d in harness.recorded(scenario.conn, ticked.tick.id)] == [
        (KEY, "wait", Decider.HARNESS),
    ]
    assert scenario.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 1
    working.finishes()


def test_a_ticket_the_harness_decided_is_not_compared_with_the_overseer(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
) -> None:
    with in_tick(conn) as tick_id:
        phases.record(
            conn,
            tick_id,
            [phases.Derived(KEY, None, (Phase.RUNNING,), candidate=True, closed=False)],
        )
        harness.record(conn, tick_id, str(canopy_env.root), [RUNNING])
    assert phases.compare(conn, tick_id) == []


def decided(env: CanopyEnv) -> list[harness.Decision]:
    """What the harness decides of `env`'s journal, derived at NOW."""
    ctx = context(env)
    return harness.decide(ctx, phases.derive(ctx, NOW))


def held_rows(env: CanopyEnv) -> dict[tuple[str, str | None], tuple[Phase, ...]]:
    """The rows the derivation finds holding for each subject of `env`'s journal at NOW, by ticket and unit."""
    return {(d.ticket_key, d.repo): tuple(d.phases) for d in phases.derive(context(env), NOW)}
