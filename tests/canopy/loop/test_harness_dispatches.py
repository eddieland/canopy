"""The harness's dispatches (DESIGN §37, ROADMAP M38).

Planned before the overseer, made after it in §7's order, none in a dry run or a tick halted before the overseer, and
`reserved` for the overseer's that would take their workers.

The one row enabled is a chore's: due, with no `when`. No ticket's row is, since each rests on an observation, so the
cases about a ticket's run enable two rows here, as a measurement would, and write the tick's derivation by hand.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import db
from canopy.core.vocab import Decider, Phase, ResumeReason, RunKind, TickStatus
from canopy.infra import procs
from canopy.loop import attention, harness_dispatches, mcp, phases
from tests.canopy.helpers import (
    KEY,
    LABEL,
    InlineRunner,
    agent_runs,
    canopy,
    chore_toml,
    context,
    decisions,
    in_tick,
    json_block,
    last_tick,
    mcp_session,
    overseer_does,
    tool_call,
    waits,
)
from tests.canopy.observation_helpers import observe_ticket
from tests.canopy.scenario_helpers import dispatches, pushes

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator, Mapping

    from tests.canopy.scenario_helpers import Scenario
    from tests.conftest import CanopyEnv, GitPool

#: Two rows a measurement might enable, each with its fixed context.
ENABLED: Final = {
    Phase.CONFLICTED: harness_dispatches.Row(ResumeReason.CONFLICT, "The PR conflicts with its base: bring it in."),
    Phase.PUSHED_NO_PR: harness_dispatches.Row(ResumeReason.NO_PR, "The branch has no PR: open one."),
}
#: A chore with no `when`, which the harness runs, and one with a `when`, which the overseer decides.
MINE: Final = "deps"
THEIRS: Final = "build-health"


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
    with overseer_does(canopy("chore", "wait", THEIRS, "--rationale", "not a weekday")):
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
    with overseer_does(canopy("chore", "wait", THEIRS, "--rationale", "not a weekday")):
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
    with overseer_does(canopy("chore", "wait", THEIRS, "--rationale", "not a weekday")):
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
    assert [d.action for d in db.decisions_for_tick(conn, tick.id)] == ["attention:disk_low"]
    assert started(conn) == []


@pytest.mark.usefixtures("two_chores")
def test_the_overseers_verbs_about_the_harnesss_chore_are_refused(conn: sqlite3.Connection) -> None:
    verbs = {
        "chore-run": (["chore", "run", MINE], {"name": MINE}),
        "chore-wait": (["chore", "wait", MINE, "--rationale", "r"], {"name": MINE, "rationale": "r"}),
    }
    for tool, (command, arguments) in verbs.items():
        with in_tick(conn) as tick_id:
            assert main(command, runner=InlineRunner()) == 1
            said = mcp_session(tool_call(tool, **arguments)).said()
            assert said.error
            assert "refused (decided)" in said.text
        assert [d.action for d in db.decisions_for_tick(conn, tick_id)] == ["refused:decided"] * 2
    # The overseer's own chore is its to decide still.
    with in_tick(conn) as tick_id:
        assert main(["chore", "wait", THEIRS, "--rationale", "r"]) == 0
    assert started(conn) == []


# A ticket's run, with rows enabled


@contextmanager
def enabled() -> Iterator[None]:
    """Until the block ends, the harness dispatches for ENABLED's rows."""
    with mock.patch.object(harness_dispatches, "ROWS", ENABLED):
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
        scenario.run(dispatches(key), worker=pushes())
        observe_ticket(scenario.conn, key, at=db.now())
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


@pytest.mark.parametrize("through", ["command", "tool"])
def test_a_ready_dispatch_into_the_harnesss_workers_is_refused_reserved_and_a_reply_is_not(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    through: str,
) -> None:
    # One worker, which the harness's conflict holds: new work may not take it, and a human waiting goes ahead.
    canopy_env.configure(canopy_env.user_file, {"capacity": {"max_workers": 1}})
    observe_ticket(conn, KEY, at=db.now())
    db.set_unit(conn, "PROJ-3", str(canopy_env.root), "repo")
    conn.execute("UPDATE tickets SET branch = 'agent/PROJ-3-work' WHERE key = 'PROJ-3'")
    conn.execute("UPDATE ticket_units SET branch = 'agent/PROJ-3-work' WHERE ticket_key = 'PROJ-3'")
    conn.commit()
    ready = (
        ["dispatch", "PROJ-2", "--repo", "repo", "--kind", "implement", "--label", LABEL],
        {"key": "PROJ-2", "kind": "implement", "repos": ["repo"], "label": LABEL},
    )
    reply = (
        ["dispatch", "PROJ-3", "--repo", "repo", "--kind", "resume", "--label", LABEL, "--reason", "reply"],
        {"key": "PROJ-3", "kind": "resume", "repos": ["repo"], "label": LABEL, "reasons": ["reply"]},
    )
    with enabled(), in_tick(conn, dry_run=True) as tick_id:
        phases.record(conn, tick_id, unit_at(KEY, Phase.CONFLICTED))
        for (argv, arguments), refused in ((ready, True), (reply, False)):
            if through == "command":
                assert main(argv) == int(refused)
            else:
                assert refused_as_tool("dispatch", arguments) is refused
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
        assert main(["decide", KEY, "wait", "--rationale", "r"]) == 1
        [(action, reason)] = decisions(conn, tick_id)
    assert action == "refused:decided"
    assert reason.startswith(f"the harness dispatches {KEY} this tick (the state block's `dispatches_to_come`)")


def refused_as_tool(name: str, arguments: Mapping[str, object]) -> bool:
    """Whether tool `name`, called with `arguments`, refused: served in this process, so a row enabled here holds."""
    request = json.dumps({"jsonrpc": "2.0", "id": 1, **tool_call(name, **arguments)}).encode()
    response = mcp.answer(request, lambda: mcp.opened(procs.SubprocessRunner(), Path.cwd()))
    assert response is not None
    result = response["result"]
    assert isinstance(result, dict)
    return result["isError"] is True


def overseer_state(agent_log: Path) -> dict[str, Any]:
    """The state block the latest overseer was given, whatever agents ran after it."""
    *_, overseer = (r for r in agent_runs(agent_log) if "canopy-overseer" in r["argv"])
    return json_block(overseer["stdin"] or overseer["argv"][-1])


def started(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """Each chore run started, as (chore, tick)."""
    return [(str(r[0]), int(r[1])) for r in conn.execute("SELECT chore, tick_id FROM chore_runs ORDER BY id")]
