"""The harness's dispatches (DESIGN §37, ROADMAP M38).

Planned before the overseer, made after it in §7's order, none in a dry run or a tick halted before the overseer, and
`reserved` for the overseer's that would take their workers. A run moves the cursors of its reasons once its worker
starts, as the overseer's `resume` does, each move its own decision; a dry run or a refused run moves none.

The one row enabled is a chore's: due, with no `when`. No ticket's row is, since each rests on an observation, so the
cases about a ticket's run enable rows here, as a measurement would, and write the tick's derivation by hand.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import conversation, db
from canopy.core.vocab import Decider, NumberedItem, Phase, ResumeReason, RunKind, TickStatus
from canopy.loop import attention, harness, harness_cursors, harness_dispatches, phases
from tests.canopy.helpers import (
    KEY,
    InlineRunner,
    agent_runs,
    chore_runs,
    chore_toml,
    chore_waits,
    context,
    decides,
    decisions,
    in_tick,
    json_block,
    last_tick,
    operator,
    overseer_calls,
    overseer_does,
    tracker_holds,
    waits,
)
from tests.canopy.observation_helpers import PR, TRUST, number_of, observe_ticket, review_number
from tests.canopy.scenario_helpers import dispatches, pushes

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator, Mapping

    from tests.canopy.scenario_helpers import Scenario
    from tests.conftest import CanopyEnv, GitPool

#: Two rows a measurement might enable, each with its fixed context.
ENABLED = {
    Phase.CONFLICTED: harness_dispatches.Row(ResumeReason.CONFLICT, "The PR conflicts with its base: bring it in."),
    Phase.PUSHED_NO_PR: harness_dispatches.Row(ResumeReason.NO_PR, "The branch has no PR: open one."),
}
#: Two rows whose reasons have cursors: `ci`'s and `review`'s.
WITH_CURSORS = {
    Phase.CI_RED: harness_dispatches.Row(ResumeReason.CI, "A check failed at the head: fix it."),
    Phase.CHANGES_REQUESTED: harness_dispatches.Row(ResumeReason.REVIEW, "A reviewer asked for changes: make them."),
}
#: A check run of PR that failed at its head, as the fake GitHub holds it.
FAILED = {"name": "build", "status": "completed", "conclusion": "failure", "run_id": 11}
#: A chore with no `when`, which the harness runs, and one with a `when`, which the overseer decides.
MINE, THEIRS = "deps", "build-health"


def test_no_ticket_row_is_enabled() -> None:
    # Each rests on an observation, and waits on the measurement that shows the derivation right on it.
    assert harness_dispatches.ROWS == {}


def test_the_order_ranks_a_human_waiting_above_a_repair_and_new_work_last() -> None:
    rank = harness_dispatches.rank_of
    assert rank(RunKind.RESUME, [ResumeReason.REPLY]) < rank(RunKind.RESUME, [ResumeReason.CONFLICT])
    assert rank(RunKind.RESUME, [ResumeReason.CI, ResumeReason.REVIEW]) == harness_dispatches.Rank.HUMAN
    assert rank(RunKind.RESUME, [ResumeReason.NO_PR]) < rank(RunKind.IMPLEMENT, [])
    assert rank(RunKind.PLAN, []) == rank(RunKind.IMPLEMENT, []) == harness_dispatches.Rank.READY


# A chore with no `when`


@pytest.fixture
def two_chores(canopy_env: CanopyEnv, treehouse_state: Path) -> None:
    """MINE, with no `when`, and THEIRS, with one, both due: neither has run. The pool is the fake's."""
    for name in (MINE, THEIRS):
        prompt = canopy_env.home / "chores" / f"{name}.md"
        prompt.parent.mkdir(exist_ok=True)
        prompt.write_text(f"# {name}\n")
    canopy_env.append_user(chore_toml(MINE) + chore_toml(THEIRS, extra='when = "Weekdays only."\n'))


@pytest.mark.usefixtures("two_chores")
def test_a_due_chore_with_no_when_is_run_by_the_harness_after_the_overseer(
    canopy_env: CanopyEnv,
    agent_log: Path,
) -> None:
    conn = canopy_env.journal()
    with overseer_does(chore_waits(THEIRS, "not a weekday")):
        assert main(["tick"], runner=InlineRunner()) == 0
    tick = last_tick(conn)
    assert tick.status == TickStatus.OK
    assert [(d.chore, d.action, d.decider) for d in db.decisions_for_tick(conn, tick.id) if d.chore] == [
        (THEIRS, "wait", Decider.OVERSEER),
        (MINE, "dispatch:chore", Decider.HARNESS),
    ]
    assert started(conn) == [(MINE, tick.id)]
    # The overseer is shown only the chore it decides, and the harness's to come.
    state = overseer_state(agent_log)
    assert [c["name"] for c in state["chores"]] == [THEIRS]
    assert state["dispatches_to_come"] == {"holds_workers": 0, "runs": [], "chores": [MINE]}


@pytest.mark.usefixtures("two_chores")
def test_the_harness_runs_its_chore_after_a_failed_overseer_run_too(canopy_env: CanopyEnv) -> None:
    conn = canopy_env.journal()
    with overseer_does(exit_code=1):
        assert main(["tick"], runner=InlineRunner()) == 1
    tick = last_tick(conn)
    assert tick.status == TickStatus.OVERSEER_FAILED
    assert [(d.chore, d.action) for d in db.decisions_for_tick(conn, tick.id) if d.chore] == [(MINE, "dispatch:chore")]


@pytest.mark.usefixtures("two_chores")
def test_a_dry_run_records_the_harnesss_chore_and_starts_none(canopy_env: CanopyEnv) -> None:
    conn = canopy_env.journal()
    with overseer_does(chore_waits(THEIRS, "not a weekday")):
        assert main(["tick", "--dry-run"], runner=InlineRunner()) == 0
    tick = last_tick(conn)
    assert [(d.chore, d.action, d.rationale) for d in db.decisions_for_tick(conn, tick.id) if d.chore == MINE] == [
        (MINE, "dispatch:chore", f"dry run: not dispatched; {harness_dispatches.CHORE_WHY}"),
    ]
    assert started(conn) == []


@pytest.mark.usefixtures("two_chores")
def test_the_harnesss_chore_on_a_model_it_cannot_look_up_is_refused_with_an_attention_item(
    canopy_env: CanopyEnv,
    opencode_state: Path,
) -> None:
    """The harness's chore is looked up as the overseer's is (DESIGN §13), the refusal and its item the harness's."""
    opencode_state.write_text(json.dumps({"exit": 1, "stderr": "Error: something broke\n"}))
    canopy_env.configure(canopy_env.user_file, {"runtime": {"models": {"chore": "acme/fake-model-1"}}})
    reason = (
        "could not look up the model acme/fake-model-1 chosen in runtime.models: `opencode models` exited 1. Nothing "
        "ran on another model; the work resumes once the list can be read"
    )
    conn = canopy_env.journal()
    with overseer_does(chore_waits(THEIRS, "not a weekday")):
        assert main(["tick"], runner=InlineRunner()) == 0
    tick = last_tick(conn)
    assert [(d.action, d.rationale, d.decider) for d in db.decisions_for_tick(conn, tick.id) if d.chore == MINE] == [
        ("refused:model_list_failed", reason, Decider.HARNESS),
        ("attention:model_list_failed", reason, Decider.HARNESS),
    ]
    assert started(conn) == []
    assert (f"chore:{MINE}", "model_list_failed") in [(i.ticket_key, i.reason) for i in attention.current(conn)]


@pytest.mark.usefixtures("two_chores")
def test_a_tick_halted_before_the_overseer_starts_none(canopy_env: CanopyEnv) -> None:
    canopy_env.configure(canopy_env.user_file, {"loop": {"min_free_disk_mib": 2**40}})
    conn = canopy_env.journal()
    with overseer_does():
        main(["tick"], runner=InlineRunner())
    tick = last_tick(conn)
    assert tick.status == TickStatus.DISK_LOW
    # The `tracker` source's query, which the harness records before the check, and the item the check raises.
    assert [d.action for d in db.decisions_for_tick(conn, tick.id)] == ["queried", "attention:disk_low"]
    assert started(conn) == []


@pytest.mark.usefixtures("two_chores")
def test_the_overseers_verbs_about_the_harnesss_chore_are_refused(conn: sqlite3.Connection) -> None:
    for move in (chore_runs(MINE), chore_waits(MINE, "r")):
        with in_tick(conn) as tick_id:
            said = overseer_calls(move, runner=InlineRunner())
            assert said.error
            assert "refused (decided)" in said.text
        assert [d.action for d in db.decisions_for_tick(conn, tick_id)] == ["refused:decided"]
    # The overseer's own chore is its to decide still.
    with in_tick(conn) as tick_id:
        assert not overseer_calls(chore_waits(THEIRS, "r")).error
    assert started(conn) == []


# A ticket's run, with rows enabled


@contextmanager
def enabled(rows: Mapping[Phase, harness_dispatches.Row] = ENABLED) -> Iterator[None]:
    """Until the block ends, the harness dispatches for `rows`."""
    with mock.patch.object(harness_dispatches, "ROWS", rows):
        yield


@contextmanager
def derived(*subjects: phases.Derived) -> Iterator[None]:
    """Until the block ends, every tick derives `subjects`, a derivation written by hand."""
    with mock.patch.object(phases, "derive", autospec=True, return_value=list(subjects)):
        yield


def unit_at(key: str, phase: Phase) -> list[phases.Derived]:
    """A fresh, open candidate holding no row of its own, its unit in `repo` holding `phase` alone."""
    return [phases.Derived(key, None, (), candidate=True, closed=False), phases.Derived(key, "repo", (phase,))]


@pytest.fixture
def pushed(scenario: Scenario, git_pool: GitPool) -> Scenario:
    """KEY and PROJ-2 implemented and pushed, and each observed with the queue label. Returns the scenario."""
    scenario.configures(capacity={"max_workers": 3})
    for key in (KEY, "PROJ-2"):
        # The tests' tracker source reads each as its dispatch rests on it, open with the queue label.
        scenario.run(dispatches(key), worker=pushes())
    scenario.seen("PROJ-3")
    scenario.conn.commit()
    return scenario


def test_its_runs_are_made_after_the_overseer_in_rank_order(pushed: Scenario) -> None:
    # KEY's comes first by key, PROJ-2's first by rank: a conflict before a branch with no PR.
    with enabled(), derived(*unit_at(KEY, Phase.PUSHED_NO_PR), *unit_at("PROJ-2", Phase.CONFLICTED)):
        ticked = pushed.tick(*waits("PROJ-3"))
    assert ticked.tick.status == TickStatus.OK
    assert [(d.ticket_key, d.action, d.decider) for d in ticked.decisions if d.action != "queried"] == [
        ("PROJ-3", "wait", Decider.OVERSEER),
        ("PROJ-2", "dispatch:resume", Decider.HARNESS),
        (KEY, "dispatch:resume", Decider.HARNESS),
    ]
    first, second = ticked.runs
    assert (first.key, first.reasons, second.key, second.reasons) == (
        "PROJ-2",
        (ResumeReason.CONFLICT,),
        KEY,
        (ResumeReason.NO_PR,),
    )
    # Its fixed context, never the overseer's words.
    assert ENABLED[Phase.CONFLICTED].context in first.prompt
    # Its workers ran after the overseer, so the overseer's is not the last agent run.
    state = overseer_state(pushed.agent_log)
    assert [t["key"] for t in state["tickets"]] == ["PROJ-3"]
    assert state["dispatches_to_come"] == {
        "holds_workers": 2,
        "runs": [
            {"ticket": "PROJ-2", "repo": "repo", "kind": "resume", "rows": ["conflicted"]},
            {"ticket": KEY, "repo": "repo", "kind": "resume", "rows": ["pushed_no_pr"]},
        ],
        "chores": [],
    }


def test_its_runs_are_made_after_a_failed_overseer_run_too(pushed: Scenario) -> None:
    with enabled(), derived(*unit_at(KEY, Phase.CONFLICTED)):
        failed = pushed.tick(exit_code=1, code=1)
    assert failed.tick.status == TickStatus.OVERSEER_FAILED
    assert [(d.ticket_key, d.action) for d in failed.decisions if d.decider is Decider.HARNESS] == [
        (KEY, "dispatch:resume"),
    ]
    assert [r.key for r in failed.runs] == [KEY]


def test_a_dry_run_starts_none_of_its_runs(pushed: Scenario) -> None:
    with enabled(), derived(*unit_at(KEY, Phase.CONFLICTED)):
        dry = pushed.tick(*waits("PROJ-2", "PROJ-3"), dry_run=True)
    assert [(d.action, d.rationale) for d in dry.decisions if d.decider is Decider.HARNESS] == [
        ("dispatch:resume", f"dry run: not dispatched; resume {KEY} in repo, for conflicted"),
    ]
    assert dry.runs == []


def test_one_row_of_judgment_leaves_the_ticket_to_the_overseer(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    observe_ticket(conn, KEY, at=db.now())
    judged = [*unit_at(KEY, Phase.CONFLICTED), phases.Derived(KEY, "other", (Phase.CHANGES_REQUESTED,))]
    with enabled(), in_tick(conn) as tick_id:
        phases.record(conn, tick_id, judged)
        assert harness_dispatches.tickets(context(canopy_env), tick_id) == frozenset()


def test_a_ready_dispatch_into_the_harnesss_workers_is_refused_reserved_and_a_reply_is_not(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
) -> None:
    # One worker, which the harness's conflict holds: new work may not take it, and a human waiting goes ahead.
    canopy_env.configure(canopy_env.user_file, {"capacity": {"max_workers": 1}})
    tracker_holds(conn, "PROJ-2", "PROJ-3")
    observe_ticket(conn, KEY, at=db.now())
    db.set_unit(conn, "PROJ-3", str(canopy_env.root), "repo")
    conn.execute("UPDATE tickets SET branch = 'agent/PROJ-3-work' WHERE key = 'PROJ-3'")
    conn.execute("UPDATE ticket_units SET branch = 'agent/PROJ-3-work' WHERE ticket_key = 'PROJ-3'")
    conn.commit()
    # The operator's answer, which authorizes the resume for reply.
    assert operator("reply", "PROJ-3", "Go ahead.") == 0
    [answer] = conversation.operator_messages_after(conn, "PROJ-3", 0)
    ready = dispatches("PROJ-2")
    reply = dispatches(
        "PROJ-3",
        RunKind.RESUME,
        reasons=[ResumeReason.REPLY],
        cursors={"message": str(answer.id)},
    )
    with enabled(), in_tick(conn, dry_run=True) as tick_id:
        phases.record(conn, tick_id, unit_at(KEY, Phase.CONFLICTED))
        for move, refused in ((ready, True), (reply, False)):
            # Served in this process, so a row enabled here holds.
            assert overseer_calls(move).error is refused
        made = decisions(conn, tick_id)
    assert [action for action, _ in made] == ["refused:reserved", "dispatch:resume"]
    assert made[0][1].startswith("1 of 1 workers are free, and the harness's dispatches to come this tick that rank")


def test_what_the_overseer_records_about_a_ticket_the_harness_dispatches_is_refused(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
) -> None:
    observe_ticket(conn, KEY, at=db.now())
    conn.commit()
    with enabled(), in_tick(conn) as tick_id:
        phases.record(conn, tick_id, unit_at(KEY, Phase.CONFLICTED))
        assert overseer_calls(decides(KEY, "wait", "r")).error
        [(action, reason)] = decisions(conn, tick_id)
    assert action == "refused:decided"
    assert reason.startswith(f"the harness dispatches {KEY} this tick (the state block's `dispatches_to_come`)")


# Its cursors


@pytest.fixture
def red(scenario: Scenario, git_pool: GitPool, github_state: Path) -> Scenario:
    """KEY pushed with PR its pull request and observed with the queue label; the fake GitHub holds PR red at its head.

    Returns the scenario.
    """
    scenario.configures(**TRUST)
    # The tests' tracker source reads it as its dispatch rests on it, open with the queue label.
    scenario.run(dispatches(), worker=pushes(prs={"repo": PR}))
    scenario.conn.commit()
    github_state.write_text(json.dumps({"prs": {PR: {"checks": [FAILED]}}}))
    return scenario


def test_its_resume_moves_the_cursor_of_its_reason_once_its_worker_starts(red: Scenario) -> None:
    with enabled(WITH_CURSORS), derived(*unit_at(KEY, Phase.CI_RED)):
        ticked = red.tick()
    [run] = ticked.runs
    assert run.reasons == (ResumeReason.CI,)
    failed = number_of(red.conn, NumberedItem.CHECK_RUN, 11)
    assert unit_cursors(red.conn) == (None, failed)
    # The move is the harness's decision, after its dispatch, and decides nothing more about the ticket.
    assert [(d.action, d.repo, d.decider) for d in ticked.decisions if d.ticket_key == KEY] == [
        ("dispatch:resume", None, Decider.HARNESS),
        (harness.CURSOR_ACTION, "repo", Decider.HARNESS),
    ]
    moved = ticked.decisions[-1]
    assert moved.rationale == f"ci cursor in repo from unset to {failed}, handled by run {run.id}, a resume for ci"
    assert f"[harness] ci cursor in repo from unset to {failed}" in red.operator("decisions").out


def test_its_resume_for_review_stops_short_of_feedback_with_no_go_ahead(red: Scenario, github_state: Path) -> None:
    reviews = [
        {"item": "review", "id": 1, "author": "octocat", "state": "changes_requested", "time": "2026-10-18T10:00:00Z",
         "body": "Rename the helper."},
        {"item": "review", "id": 2, "author": "stranger", "state": "changes_requested", "time": "2026-10-18T11:00:00Z",
         "body": "Why not a map?"},
    ]  # fmt: skip
    github_state.write_text(json.dumps({"prs": {PR: {"reviews": reviews}}}))
    with enabled(WITH_CURSORS), derived(*unit_at(KEY, Phase.CHANGES_REQUESTED)):
        ticked = red.tick()
    assert [r.reasons for r in ticked.runs] == [(ResumeReason.REVIEW,)]
    # The trusted reviewer's is handled; the stranger's waits on the operator's go-ahead, so it stays new.
    trusted = int(review_number(red.conn, 1))
    assert unit_cursors(red.conn) == (trusted, None)
    assert trusted < int(review_number(red.conn, 2))
    assert [d.rationale for d in ticked.decisions if d.action == harness.CURSOR_ACTION] == [
        f"review cursor in repo from unset to {trusted}, handled by run {ticked.runs[0].id}, a resume for review",
    ]


def test_a_cursor_already_past_is_not_moved_back(red: Scenario) -> None:
    failed = number_of(red.conn, NumberedItem.CHECK_RUN, 11)
    with in_tick(red.conn) as tick_id:
        moves = harness_cursors.handled(red.conn, KEY, "repo", {"ci": str(failed)}, "handled by run 9")
        assert [m.rationale() for m in harness_cursors.record(red.conn, tick_id, moves)] == [
            f"ci cursor in repo from unset to {failed}, handled by run 9",
        ]
        # The overseer passed it further meanwhile: the move leaves it, and records nothing.
        red.conn.execute("UPDATE ticket_units SET ci_cursor = ? WHERE ticket_key = ?", (failed + 5, KEY))
        assert harness_cursors.record(red.conn, tick_id, moves) == []
    assert unit_cursors(red.conn) == (None, failed + 5)


def test_a_dry_run_names_the_cursors_it_would_move_and_moves_none(red: Scenario) -> None:
    with enabled(WITH_CURSORS), derived(*unit_at(KEY, Phase.CI_RED)):
        dry = red.tick(dry_run=True)
    failed = number_of(red.conn, NumberedItem.CHECK_RUN, 11)
    assert [(d.action, d.rationale) for d in dry.decisions if d.decider is Decider.HARNESS] == [
        ("dispatch:resume", f"dry run: not dispatched; resume {KEY} in repo, for ci_red; cursor ci={failed}"),
    ]
    assert dry.runs == []
    assert unit_cursors(red.conn) == (None, None)


def test_a_resume_the_claims_refuse_moves_no_cursor(red: Scenario, github_state: Path) -> None:
    # GitHub cannot read the PR, so the run would rest on a stale observation: refused as the overseer's would be.
    github_state.write_text(json.dumps({"prs": {PR: {"checks": [FAILED]}}, "unread": [PR]}))
    with enabled(WITH_CURSORS), derived(*unit_at(KEY, Phase.CI_RED)):
        ticked = red.tick()
    assert [(d.action, d.decider) for d in ticked.decisions if d.ticket_key == KEY] == [
        ("refused:stale", Decider.HARNESS),
    ]
    assert ticked.runs == []
    assert unit_cursors(red.conn) == (None, None)


def unit_cursors(conn: sqlite3.Connection) -> tuple[int | None, int | None]:
    """KEY's unit's `review` and `ci` cursors."""
    [unit] = conn.execute("SELECT review_cursor, ci_cursor FROM ticket_units WHERE ticket_key = ?", (KEY,)).fetchall()
    return unit["review_cursor"], unit["ci_cursor"]


def overseer_state(agent_log: Path) -> dict[str, Any]:
    """The state block the latest overseer was given, whatever agents ran after it."""
    *_, overseer = (r for r in agent_runs(agent_log) if "canopy-overseer" in r["argv"])
    return json_block(overseer["stdin"] or overseer["argv"][-1])


def started(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """Each chore run started, as (chore, tick)."""
    return [(str(r[0]), int(r[1])) for r in conn.execute("SELECT chore, tick_id FROM chore_runs ORDER BY id")]
