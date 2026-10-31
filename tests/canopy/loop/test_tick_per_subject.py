"""A tick runs the overseer once for each subject left to it, each run given that subject alone (DESIGN §40, M40).

With `loop.overseer_per_subject` on, each ticket owed a decision, each PR whose review is the overseer's to start, and
the due chores together get a run of their own, one at a time in §7's order. A run's message is the state block's
shared part, the same in every run, then its subject's; whatever it records about another subject is refused
`decided`. A subject of new work waits for capacity in code, with no run, once none is left. A run that fails, or leaves
its duty undone, holds up no other, and the tick closes `overseer_failed` naming each such subject.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest import mock

import pytest

from canopy.core import records
from canopy.core.vocab import Decider, OverseerRunStatus, TickStatus
from canopy.loop import attention, tick
from tests.canopy.helpers import (
    KEY,
    agent_runs,
    chore_waits,
    decides,
    overseer_script,
    overseer_titles,
    titled_overseer,
)
from tests.canopy.scenario_helpers import dispatches, due_chore, review_waits

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from tests.canopy.scenario_helpers import Scenario
    from tests.conftest import GitPool

#: Three tickets a tick leaves to the overseer, each `ready` alike, so §7's order runs them by key.
TICKETS = ("PROJ-1", "PROJ-2", "PROJ-3")
#: A PR the operator asked to have reviewed, which no ticket holds.
REQUESTED = "https://github.com/acme/other/pull/12"
#: A reviewer's command, so a review request turns reviews on.
REVIEW_CMD = "env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-reviewer {prompt}"


@pytest.fixture
def per_subject(scenario: Scenario) -> Scenario:
    """The scenario, its loop running the overseer once per subject, each run titled by its subject first."""
    scenario.configures(loop={"overseer_per_subject": True})
    titled_overseer(scenario.env)
    return scenario


def test_three_tickets_get_three_runs_in_order_each_given_its_ticket_alone(per_subject: Scenario) -> None:
    per_subject.seen(*TICKETS)
    ticked = per_subject.tick(overseers={key: overseer_script(decides(key)) for key in TICKETS})
    assert (ticked.tick.status, ticked.tick.overseer_ran) == (TickStatus.OK, 3)
    assert [(r.subject, r.status) for r in runs_of(per_subject.conn, ticked.tick.id)] == [
        (key, OverseerRunStatus.OK) for key in TICKETS
    ]
    assert [title.split(" · ")[0] for title in overseer_titles(per_subject.agent_log)] == list(TICKETS)
    shared, parts = split(messages(per_subject.agent_log))
    assert "PROJ-" not in shared
    for key, part in zip(TICKETS, parts, strict=True):
        assert part["subject"] == key
        assert [t["key"] for t in part["tickets"]] == [key]
        assert [o["key"] for o in part["observations"]["tickets"]] == [key]
        assert not any(other in json.dumps(part) for other in TICKETS if other != key)


def test_a_run_is_refused_anything_about_another_ticket(per_subject: Scenario) -> None:
    per_subject.seen("PROJ-1", "PROJ-2")
    # PROJ-1's run decides PROJ-2 too, refused; PROJ-2's run records nothing, so the refusal decides nothing for it.
    ticked = per_subject.tick(
        overseers={"PROJ-1": overseer_script(decides("PROJ-2"), decides("PROJ-1"))},
        code=1,
    )
    [said] = [t for t in agent_runs(per_subject.agent_log)[0]["tools"] if t["error"]]
    assert said["text"] == (
        "decide refused (decided): this run is given PROJ-1 alone; record nothing about PROJ-2; the refusal was "
        "recorded"
    )
    assert [(d.ticket_key, d.action) for d in ticked.decisions if d.action != "queried"] == [
        ("PROJ-2", attention.REFUSED_DECIDED),
        ("PROJ-1", "wait"),
    ]
    assert [(r.subject, r.status) for r in runs_of(per_subject.conn, ticked.tick.id)] == [
        ("PROJ-1", OverseerRunStatus.OK),
        ("PROJ-2", OverseerRunStatus.UNDONE),
    ]
    assert ticked.tick.summary == (
        "overseer failed on 1 of 2 subjects: PROJ-2: overseer left duties undone: no decision for PROJ-2"
    )


def test_new_work_waits_for_capacity_in_code_with_no_run(per_subject: Scenario, git_pool: GitPool) -> None:
    del git_pool
    per_subject.configures(capacity={"max_workers": 1})
    per_subject.seen("PROJ-1", "PROJ-2")
    ticked = per_subject.tick(overseers={"PROJ-1": overseer_script(dispatches("PROJ-1"))})
    assert ticked.tick.status == TickStatus.OK
    # PROJ-1's run holds the one worker, so PROJ-2, `ready`, is the harness's to wait, naming capacity.
    assert [r.subject for r in runs_of(per_subject.conn, ticked.tick.id)] == ["PROJ-1"]
    [waited] = [d for d in ticked.decisions if d.ticket_key == "PROJ-2"]
    assert (waited.action, waited.decider) == ("wait", Decider.HARNESS)
    assert waited.rationale.startswith("capacity: no worker is free for new work (1 of 1 running or recorded)")
    assert [r.key for r in ticked.runs] == ["PROJ-1"]
    assert ticked.tick.overseer_ran == 1


def test_the_due_chores_run_last_in_a_run_of_their_own(per_subject: Scenario) -> None:
    due_chore(per_subject, "build-health", when="Weekdays only.")
    per_subject.seen(KEY)
    ticked = per_subject.tick(
        overseers={KEY: overseer_script(decides(KEY)), "chores": overseer_script(chore_waits("build-health"))},
    )
    assert ticked.tick.status == TickStatus.OK
    assert [r.subject for r in runs_of(per_subject.conn, ticked.tick.id)] == [KEY, "chore:*"]
    _, [ticket, chores] = split(messages(per_subject.agent_log))
    assert ("chores" in ticket, [c["name"] for c in chores["chores"]]) == (False, ["build-health"])


def test_a_review_request_runs_first_and_a_ticket_s_run_may_not_review_its_pr(per_subject: Scenario) -> None:
    per_subject.configures(runtime={"review_cmd": REVIEW_CMD})
    per_subject.operator("start", REQUESTED, "--review")
    per_subject.seen(KEY)
    ticked = per_subject.tick(
        overseers={
            REQUESTED: overseer_script(review_waits(REQUESTED)),
            KEY: overseer_script(review_waits(REQUESTED), decides(KEY)),
        },
    )
    assert ticked.tick.status == TickStatus.OK
    assert [r.subject for r in runs_of(per_subject.conn, ticked.tick.id)] == [f"pr:{REQUESTED}", KEY]
    assert [(d.pr, d.action) for d in ticked.decisions if d.pr is not None] == [
        (REQUESTED, "wait"),
        (REQUESTED, attention.REFUSED_DECIDED),
    ]
    _, [pr, ticket] = split(messages(per_subject.agent_log))
    assert [r["url"] for r in pr["reviews"]["requests"]] == [REQUESTED]
    assert "requests" not in ticket["reviews"]


def test_runs_that_fail_or_leave_their_duty_undone_hold_up_no_other(per_subject: Scenario, git_pool: GitPool) -> None:
    del git_pool
    per_subject.seen(*TICKETS)
    ticked = per_subject.tick(
        overseers={
            "PROJ-1": overseer_script(dispatches("PROJ-1")),
            "PROJ-2": overseer_script(decides("PROJ-2"), exit_code=1),
        },
        code=1,
    )
    assert ticked.tick.status == TickStatus.OVERSEER_FAILED
    assert [(r.subject, r.status) for r in runs_of(per_subject.conn, ticked.tick.id)] == [
        ("PROJ-1", OverseerRunStatus.OK),
        ("PROJ-2", OverseerRunStatus.FAILED),
        ("PROJ-3", OverseerRunStatus.UNDONE),
    ]
    assert ticked.tick.summary == (
        "overseer failed on 2 of 3 subjects: PROJ-2: overseer exited 1; "
        "PROJ-3: overseer left duties undone: no decision for PROJ-3"
    )
    # What the failing run recorded stands, and PROJ-1's dispatch starts after the last run.
    assert ("PROJ-2", "wait") in [(d.ticket_key, d.action) for d in ticked.decisions]
    assert [r.key for r in ticked.runs] == ["PROJ-1"]


def test_the_checks_are_made_once_for_the_tick(per_subject: Scenario) -> None:
    per_subject.seen(*TICKETS)
    with mock.patch.object(tick, "_check_server", autospec=True, return_value=None) as checked:
        per_subject.tick(overseers={key: overseer_script(decides(key)) for key in TICKETS})
    assert checked.call_count == 1


def runs_of(conn: sqlite3.Connection, tick_id: int) -> list[records.OverseerRun]:
    """The overseer runs tick `tick_id` recorded, in the order it started them."""
    return records.select(records.OverseerRun).where("tick_id = ?", tick_id).order_by("id").all(conn)


def messages(agent_log: Path) -> list[str]:
    """Each fake overseer run's message, its last argument, in order."""
    return [str(r["argv"][-1]) for r in agent_runs(agent_log) if r["argv"][:3] == ["run", "--agent", "canopy-overseer"]]


def split(said: list[str]) -> tuple[str, list[dict[str, Any]]]:
    """The shared part every message in `said` starts with, the same in each, and each one's subject part, parsed."""
    shared = {message.split("## Subject\n", 1)[0] for message in said}
    assert len(shared) == 1, "the shared part differs between runs"
    parts = [json.loads(m.split("## Subject\n", 1)[1].split("```json\n", 1)[1].split("\n```", 1)[0]) for m in said]
    return shared.pop(), parts
