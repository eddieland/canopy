"""The tick starts every run (DESIGN §8, ROADMAP M40 stage 1).

A dispatch, review, revision, or chore run the overseer asks for, through a tool or its command, is checked and recorded
at the ask, and the tick starts it once the overseer's run ends, with the harness's own in §7's order, under every guard
again: never from the overseer's process tree. A recorded run counts as running until then, and one its tick did not
start is closed unstarted, counting toward no limit. A dry run records none.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import chore_runs, db, notice, recorded_runs, review_runs
from canopy.core.vocab import Phase, RecordedKind, RecordedStatus, RunKind, TickStatus
from canopy.infra import procs
from canopy.loop import claims, phases
from canopy.runs import policy
from tests.canopy.helpers import (
    KEY,
    LABEL,
    agent_runs,
    ancestors,
    calls,
    chore_reports,
    chore_toml,
    decisions,
    derived,
    enabled,
    in_tick,
    present,
    tick_starts,
    unit_at,
)
from tests.canopy.observation_helpers import observe_ticket
from tests.canopy.review_helpers import feature_commit, reviewer_reports
from tests.canopy.scenario_helpers import dispatches, pushes, reviews

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping

    from tests.canopy.scenario_helpers import Scenario
    from tests.conftest import CanopyEnv, GitPool

#: What the overseer runs after its asks: its own pid, then how many runs of each kind are started, and how many are
#: recorded, as the journal holds them at that moment.
PROBE = (
    "import os, sqlite3, sys; c = sqlite3.connect(sys.argv[1]); "
    "print(os.getppid(), *(c.execute('SELECT count(*) FROM ' + t).fetchone()[0] "
    "for t in ('runs', 'review_runs', 'chore_runs', 'recorded_runs')))"
)
#: A chore with a `when`, the overseer's to run, and one without, the harness's.
THEIRS, MINE = "build-health", "deps"
#: What a chore reports.
CHORE_OK: Mapping[str, object] = {"status": "ok", "summary": "nothing found", "findings": []}
#: What a reviewer reports.
REVIEW_OK: Mapping[str, object] = {"verdict": "approve", "impact": "low", "summary": "Fine.", "findings": []}


@pytest.fixture
def chores(canopy_env: CanopyEnv) -> None:
    """THEIRS, with a `when`, and MINE, with none, both due: neither has run."""
    for name in (THEIRS, MINE):
        prompt = canopy_env.home / "chores" / f"{name}.md"
        prompt.parent.mkdir(exist_ok=True)
        prompt.write_text(f"# {name}\n")
    canopy_env.append_user(chore_toml(THEIRS, extra='when = "Weekdays only."\n') + chore_toml(MINE))


# Started after the overseer, outside its process tree


@pytest.mark.usefixtures("git_pool")
@pytest.mark.parametrize("door", ["tool", "command"])
def test_a_dispatch_starts_after_the_overseer_exits_and_outlives_it_outside_its_tree(
    scenario: Scenario,
    door: str,
) -> None:
    asked = (
        calls("canopy_dispatch", key=KEY, kind="implement", label=LABEL, repos=["repo"])
        if door == "tool"
        else dispatches()
    )
    ticked = scenario.tick(asked, probe(scenario.env), hold=True)
    overseer, runs, _, _, recorded = probed(scenario.agent_log)
    # While the overseer ran, its dispatch was recorded, and nothing had started.
    assert (runs, recorded) == (0, 1)
    [working] = ticked.working
    pid = int(working.row["pid"])
    # Its `_run` is none of the overseer's descendants, and goes on with the overseer gone.
    assert overseer not in ancestors(pid)
    assert not procs.alive(overseer)
    assert procs.running(Path(working.row["log_path"]), pid)
    [row] = scenario.conn.execute("SELECT * FROM recorded_runs").fetchall()
    assert (row["kind"], row["status"], row["run_id"]) == (RecordedKind.DISPATCH, RecordedStatus.STARTED, working.id)
    assert [(d.ticket_key, d.action) for d in ticked.decisions if d.action != "queried"] == [
        (KEY, "dispatch:implement"),
    ]
    assert working.finishes().status == "done"


@pytest.mark.usefixtures("chores", "reviewing")
def test_a_review_and_a_chore_run_start_after_the_overseer_exits_outside_its_tree(
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    sha = feature_commit(git_pool, tmp_path)
    with reviewer_reports(REVIEW_OK, sleep=60), chore_reports(CHORE_OK, sleep=60):
        ticked = scenario.tick(
            reviews(sha, ticket=KEY),
            ["canopy", "chore", "run", THEIRS],
            probe(scenario.env),
            *waits_for(KEY),
        )
    overseer, _, review_count, chore_count, recorded = probed(scenario.agent_log)
    assert (review_count, chore_count, recorded) == (0, 0, 2)
    assert ticked.tick.status == TickStatus.OK
    review = present(review_runs.get_review_run(scenario.conn, 1))
    chore = present(chore_runs.get_chore_run(scenario.conn, 1))
    try:
        for pid in (present(review.pid), present(chore.pid)):
            assert overseer not in ancestors(pid)
        assert not procs.alive(overseer)
    finally:
        for pid in (review.pid, review.agent_pid, chore.pid, chore.agent_pid):
            if pid is not None:
                procs.kill_group(pid)
    statuses = scenario.conn.execute("SELECT kind, status FROM recorded_runs ORDER BY id").fetchall()
    assert [tuple(r) for r in statuses] == [
        (RecordedKind.REVIEW, RecordedStatus.STARTED),
        (RecordedKind.CHORE, RecordedStatus.STARTED),
    ]


@pytest.mark.usefixtures("chores")
def test_the_tick_starts_the_overseers_runs_with_the_harnesss_in_rank_order_chores_last(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    del git_pool
    scenario.configures(capacity={"max_workers": 3, "max_chores": 2})
    scenario.run(dispatches("PROJ-2"), worker=pushes())
    for key in ("PROJ-2", "PROJ-3"):
        observe_ticket(scenario.conn, key, at=db.now())
    scenario.seen("PROJ-3")
    # The overseer asks for PROJ-3's implement, new work, and its chore, before the harness makes anything; the
    # harness's conflict on PROJ-2 ranks above the implement, and its own chore comes after the overseer's.
    with enabled(), derived(*unit_at("PROJ-2", Phase.CONFLICTED)), chore_reports(CHORE_OK):
        ticked = scenario.tick(["canopy", "chore", "run", THEIRS], dispatches("PROJ-3"), worker=pushes())
    assert ticked.tick.status == TickStatus.OK, ticked
    started = [(d.ticket_key or d.chore, d.action) for d in ticked.decisions if d.action.startswith("dispatch:")]
    assert started == [
        ("PROJ-2", "dispatch:resume"),
        ("PROJ-3", "dispatch:implement"),
        (THEIRS, "dispatch:chore"),
        (MINE, "dispatch:chore"),
    ]
    assert [(r.key, r.kind) for r in ticked.runs] == [("PROJ-2", RunKind.RESUME), ("PROJ-3", RunKind.IMPLEMENT)]


# A recorded run counts as running


def test_a_recorded_dispatch_holds_its_ticket_and_its_worker(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    canopy_env.configure(canopy_env.user_file, {"capacity": {"max_workers": 1}})
    with in_tick(conn) as tick_id:
        assert main(dispatch_args(KEY)) == 0
        # A second run for the ticket, and one past `max_workers`, are refused before anything has started.
        assert main(dispatch_args(KEY)) == 1
        assert main(dispatch_args("PROJ-2")) == 1
        made = decisions(conn, tick_id)
    assert made == [
        ("refused:running", "recorded run 1 works PROJ-1 once the overseer's run ends"),
        ("refused:capacity", "1 of 1 workers are running, counting 1 recorded to start once the overseer's run ends"),
    ]
    assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_reserved_counts_a_recorded_run(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    # Two workers, one the harness's conflict to come holds: the first new work takes the other, recorded, and the
    # second would take the harness's.
    canopy_env.configure(canopy_env.user_file, {"capacity": {"max_workers": 2}})
    observe_ticket(conn, "PROJ-3", at=db.now())
    with enabled(), in_tick(conn) as tick_id:
        phases_record(conn, tick_id)
        assert main(dispatch_args(KEY)) == 0
        assert main(dispatch_args("PROJ-2")) == 1
        [(action, reason)] = decisions(conn, tick_id)
    assert action == "refused:reserved"
    assert reason.startswith("1 of 2 workers are free, and the harness's dispatches to come this tick that rank")


@pytest.mark.usefixtures("chores")
def test_a_recorded_chore_run_holds_its_chore(conn: sqlite3.Connection) -> None:
    with in_tick(conn) as tick_id:
        assert main(["chore", "run", THEIRS]) == 0
        assert main(["chore", "run", THEIRS]) == 1
        [(action, reason)] = decisions(conn, tick_id)
    assert (action, reason) == ("refused:running", f"recorded run 1 of {THEIRS} starts once the overseer's run ends")


@pytest.mark.usefixtures("reviewing")
def test_a_recorded_dispatch_holds_off_a_review_of_its_ticket(conn: sqlite3.Connection) -> None:
    with in_tick(conn) as tick_id:
        assert main(dispatch_args(KEY)) == 0
        assert main(["review", "run", "--pr", PR_OF_KEY, "--sha", "a" * 40, "--repo", "repo", "--ticket", KEY]) == 1
        [(action, reason)] = decisions(conn, tick_id)
    assert (action, reason) == ("refused:running", f"a worker run for {KEY} is running; review its PR once it ends")


# Checked again at the spawn


def test_a_recorded_run_whose_ticket_the_operator_stops_is_refused_at_the_spawn(scenario: Scenario) -> None:
    scenario.operator("start", KEY)
    with scenario.ticking() as tick_id:
        scenario.overseer(*dispatches(label=None)[1:])
        scenario.operator("stop", KEY)
        tick_starts(tick_id)
        made = decisions(scenario.conn, tick_id)
    assert [action for action, _ in made] == ["refused:stopped"]
    assert scenario.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
    assert present(recorded_runs.get(scenario.conn, 1)).status is RecordedStatus.REFUSED


@pytest.mark.usefixtures("git_pool")
def test_a_recorded_resume_for_ci_whose_notice_changes_is_refused_at_the_spawn(scenario: Scenario) -> None:
    scenario.run(dispatches(), worker=pushes())
    conn = scenario.conn
    # The claims are the observations', checked at the ask: what is under test is the notice, checked again.
    with mock.patch.object(claims, "check", autospec=True, return_value=None), in_tick(conn) as tick_id:
        conn.execute("UPDATE ticks SET read_at = ? WHERE id = ?", (db.format_time(datetime.now(UTC)), tick_id))
        assert main(dispatch_args(KEY, "--kind", "resume", "--reason", "ci")) == 0
        notice.set_notice(conn, "CI is down.", minutes=60, channel="cli")
        tick_starts(tick_id)
        made = decisions(conn, tick_id)
    assert [action for action, _ in made] == ["refused:notice_changed"]
    assert conn.execute("SELECT count(*) FROM runs WHERE tick_id = ?", (tick_id,)).fetchone()[0] == 0


# Closed with its tick


def test_a_run_a_dead_tick_recorded_is_closed_unstarted_by_the_next_and_counts_toward_no_limit(
    scenario: Scenario,
) -> None:
    scenario.configures(policy={"max_implement_attempts": 1})
    conn = scenario.conn
    # The tick's process dies after the ask: its tick is left running, its run recorded.
    dead = db.start_tick(conn, dry_run=False)
    with mock.patch.dict("os.environ", {"CANOPY_TICK_ID": str(dead)}):
        assert main(dispatch_args(KEY)) == 0
    assert recorded_runs.held(conn) != []
    scenario.seen(KEY)
    later = scenario.tick(dispatches(), worker=pushes())
    assert present(db.get_tick(conn, dead)).status == TickStatus.ABANDONED
    first, second = (present(recorded_runs.get(conn, i)) for i in (1, 2))
    assert (first.status, first.run_id) == (RecordedStatus.UNSTARTED, None)
    # No later tick started it, and it spent none of the ticket's one implement: the next tick's dispatch started.
    assert (second.tick_id, second.status) == (later.tick.id, RecordedStatus.STARTED)
    assert [r.key for r in later.runs] == [KEY]
    assert policy.attempts(conn)[policy.unit(KEY, "repo")][RunKind.IMPLEMENT] == 1


def test_a_run_the_tick_did_not_start_is_closed_unstarted_as_it_closes(scenario: Scenario) -> None:
    # The tick's starts raise, as a bug would: the record is closed with the tick, and its duty left undone.
    scenario.seen(KEY)
    with mock.patch.object(recorded_runs, "of_tick", autospec=True, side_effect=RuntimeError("broken")):
        ticked = scenario.tick(dispatches(), code=1)
    assert ticked.tick.status == TickStatus.OVERSEER_FAILED
    assert present(recorded_runs.get(scenario.conn, 1)).status is RecordedStatus.UNSTARTED
    assert ticked.runs == []


def test_a_dry_run_records_none(scenario: Scenario) -> None:
    scenario.seen(KEY)
    dry = scenario.tick(dispatches(), dry_run=True)
    assert [(d.action, d.rationale.split(";")[0]) for d in dry.decisions if d.action != "queried"] == [
        ("dispatch:implement", "dry run: not dispatched"),
    ]
    assert scenario.conn.execute("SELECT count(*) FROM recorded_runs").fetchone()[0] == 0
    assert dry.runs == []


# Helpers


#: PROJ-1's PR in `repo`, as the `reviewing` fixture records it.
PR_OF_KEY = "https://github.com/acme/api/pull/7"


def dispatch_args(key: str, *more: str) -> list[str]:
    """`canopy dispatch` of `key`'s implement in `repo` under the queue label, or of what `more` says instead."""
    kind = [] if "--kind" in more else ["--kind", "implement"]
    return ["dispatch", key, "--repo", "repo", "--label", LABEL, *kind, *more]


def probe(env: CanopyEnv) -> list[str]:
    """The command the overseer runs to say its pid, and what the journal holds started and recorded (`PROBE`)."""
    return [sys.executable, "-c", PROBE, str(env.state_dir / db.DB_FILE_NAME)]


def probed(agent_log: Path) -> tuple[int, int, int, int, int]:
    """What the overseer's `probe` said: its pid, the runs, review runs, and chore runs started, and those recorded."""
    *_, overseer = (r for r in agent_runs(agent_log) if "canopy-overseer" in r["argv"])
    commands: list[dict[str, Any]] = overseer["commands"]
    [said] = [c["stdout"] for c in commands if c["argv"][:2] == [sys.executable, "-c"]]
    pid, runs, reviews_, chores_, recorded = (int(n) for n in said.split())
    return pid, runs, reviews_, chores_, recorded


def waits_for(key: str) -> list[list[str]]:
    """The overseer's wait on `key`, whose review it asked for: a ticket in the block is owed a decision."""
    return [["canopy", "decide", key, "wait", "--rationale", "its review runs"]]


def phases_record(conn: sqlite3.Connection, tick_id: int) -> None:
    """Record tick `tick_id`'s derivation: PROJ-3's unit conflicted, which the harness dispatches for."""
    phases.record(conn, tick_id, unit_at("PROJ-3", Phase.CONFLICTED))
    db.set_unit(conn, "PROJ-3", str(Path.cwd()), "repo")
    conn.execute("UPDATE tickets SET branch = 'agent/PROJ-3-work' WHERE key = 'PROJ-3'")
    conn.execute("UPDATE ticket_units SET branch = 'agent/PROJ-3-work' WHERE ticket_key = 'PROJ-3'")
