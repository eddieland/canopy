"""Which skills a window's runs were offered and loaded, and what each one's front matter cost (DESIGN §13).

Over a hand-written journal: runs of each kind, what the runtime said it offered them, the calls of the skill tool
they recorded, and the model calls their sessions name.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from canopy.core import db, records, run_offers, skill_report, spend, sql
from canopy.core.vocab import ChoreRunStatus, PoolKind, ReviewRunStatus, RunKind, RunStatus
from canopy.runtime.agents import AgentOffer
from canopy.runtime.report import ToolUse
from tests.canopy.helpers import earlier, present

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping
    from pathlib import Path

    from canopy.core.run_models import RunTable
    from tests.conftest import Journals

NOW = datetime(2026, 11, 8, 12, tzinfo=UTC)
#: The descriptions' lengths the tests offer each skill with: its front matter is its name's and this.
SIZES = {"tracker-jira": 80, "release-notes": 60, "terse": 0}


def tick(conn: sqlite3.Connection, started: str, *, overseer_ran: int = 1) -> int:
    """A tick that started at `started` and ended, whose overseer ran unless `overseer_ran` is 0."""
    made = records.insert(
        records.Tick,
        started_at=started,
        ended_at=started,
        dry_run=0,
        overseer_ran=overseer_ran,
    ).run(conn)
    return present(made.lastrowid)


def worker(
    conn: sqlite3.Connection,
    started: str,
    *,
    kind: RunKind = RunKind.IMPLEMENT,
    private: bool = False,
    ended: bool = True,
) -> int:
    """A worker's or a planner's run that started at `started`, ended unless `ended` is false."""
    db.touch_ticket(conn, "PROJ-1", "/ws")
    run = records.insert(
        records.Run,
        tick_id=tick(conn, started, overseer_ran=0),
        ticket_key="PROJ-1",
        kind=kind,
        branch="agent/PROJ-1",
        started_at=started,
        ended_at=started if ended else None,
        status=RunStatus.DONE if ended else RunStatus.RUNNING,
        log_path="l",
        private=int(private),
    ).run(conn)
    return present(run.lastrowid)


def review(conn: sqlite3.Connection, started: str) -> int:
    """A review run that started at `started` and ended."""
    run = records.insert(
        records.ReviewRun,
        tick_id=tick(conn, started, overseer_ran=0),
        pr_url="https://example.test/acme/web/pull/9",
        sha="a" * 40,
        started_at=started,
        ended_at=started,
        status=ReviewRunStatus.DONE,
        log_path="l",
    ).run(conn)
    return present(run.lastrowid)


def chore(conn: sqlite3.Connection, started: str) -> int:
    """A chore's run that started at `started` and ended."""
    run = records.insert(
        records.ChoreRun,
        tick_id=tick(conn, started, overseer_ran=0),
        chore="deps",
        started_at=started,
        ended_at=started,
        status=ChoreRunStatus.OK,
        log_path="l",
    ).run(conn)
    return present(run.lastrowid)


def task(conn: sqlite3.Connection, started: str) -> int:
    """A task's run that started at `started` and ended: one the runtime is never asked about."""
    made = records.insert(records.Task, text="Do it.", repo="web", channel="cli", submitted_at=started).run(conn)
    run = records.insert(
        records.TaskRun,
        task_id=present(made.lastrowid),
        tick_id=tick(conn, started, overseer_ran=0),
        branch="agent/task/1",
        repo="web",
        slot_path="/pool/web/1",
        lease_id="lease",
        lease_holder="canopy",
        base_branch="main",
        pool=PoolKind.CANOPY,
        started_at=started,
        ended_at=started,
        status=RunStatus.DONE,
        log_path="l",
    ).run(conn)
    return present(run.lastrowid)


def offered(
    conn: sqlite3.Connection,
    table: RunTable,
    run_id: int,
    agent: str,
    sizes: Mapping[str, int] = SIZES,
    *,
    sized: bool = True,
) -> None:
    """What the runtime said it offered a run: the skills of `sizes`, each with its description's length if `sized`."""
    offer = AgentOffer(agent, skills=tuple(sizes), description_chars=sizes if sized else {})
    run_offers.record(conn, table, run_id, offer)


def called(conn: sqlite3.Connection, table: RunTable, run_id: int, replies: int, *tools: ToolUse) -> None:
    """What a run's session and events say: the model calls it made, and its calls of the skill tool."""
    if table == "ticks":
        db.set_tick_report(conn, run_id, "s", None, tools=tools)
    else:
        db.set_run_report(conn, table, run_id, "s", None, tools=tools)
    if replies:
        records.insert(
            records.RunModel,
            run_table=table,
            run_id=run_id,
            model="anthropic/claude-sonnet-4-5",
            replies=replies,
            cost_usd=0.0,
        ).run(conn)


def uses(found: skill_report.Skills, skill: str) -> dict[str, skill_report.Use]:
    """A skill's uses in a report, by agent."""
    [row] = [s for s in found.skills if s.name == skill]
    return {u.agent: u for u in row.uses}


def test_a_skill_is_counted_by_the_runs_offered_it_and_those_that_loaded_it(conn: sqlite3.Connection) -> None:
    """Offered is a run whose list held it; loaded, a call for it that did not fail; cost, its length by the calls."""
    day = earlier(NOW, 1)
    first, second, reviewer = worker(conn, day), worker(conn, day), review(conn, day)
    offered(conn, "runs", first, "canopy-worker")
    offered(conn, "runs", second, "canopy-worker")
    offered(conn, "review_runs", reviewer, "canopy-reviewer", {"tracker-jira": 80, "terse": 0})
    called(conn, "runs", first, 20, ToolUse("skill:tracker-jira", 1, 0, 4000), ToolUse("bash", 9, 0, 700))
    # Two loads and a call that failed; and a call for another skill that only failed, which loaded nothing.
    called(
        conn,
        "runs",
        second,
        10,
        ToolUse("skill:tracker-jira", 3, 1, 8100),
        ToolUse("skill:release-notes", 1, 1, 40),
    )
    # The reviewer's session is not read, so nothing says how many model calls carried its list.
    found = skill_report.report(conn, NOW, 7)
    assert [s.name for s in found.skills] == ["release-notes", "terse", "tracker-jira"]
    tracker = uses(found, "tracker-jira")
    assert list(tracker) == ["canopy-worker", "canopy-reviewer"]
    assert tracker["canopy-worker"] == skill_report.Use(
        agent="canopy-worker",
        skill="tracker-jira",
        offered=2,
        loaded=2,
        loads=3,
        failed=1,
        result_chars=12_100,
        front_matter_chars=len("tracker-jira") + 80,
        counted=2,
        calls=30,
        sent_chars=92 * 30,
    )
    assert tracker["canopy-reviewer"] == skill_report.Use(
        agent="canopy-reviewer",
        skill="tracker-jira",
        offered=1,
        front_matter_chars=92,
    )
    notes = uses(found, "release-notes")["canopy-worker"]
    assert (notes.offered, notes.loaded, notes.loads, notes.failed, notes.result_chars) == (2, 0, 0, 1, 0)
    assert (notes.front_matter_chars, notes.sent_chars) == (73, 73 * 30)
    # A skill that says nothing of itself still rides by its name.
    assert uses(found, "terse")["canopy-worker"].front_matter_chars == len("terse")
    assert (found.offered, found.unused, found.loads) == (3, 2, 3)
    assert [s.name for s in found.skills if s.unused] == ["release-notes", "terse"]
    assert found.agents == [
        skill_report.Agent(
            agent="canopy-worker",
            runs=2,
            said=2,
            unanswered=0,
            sized=2,
            counted=2,
            calls=30,
            sent_chars=(92 + 73 + 5) * 30,
            skills=3,
            unused=2,
        ),
        skill_report.Agent(
            agent="canopy-reviewer",
            runs=1,
            said=1,
            unanswered=0,
            sized=1,
            counted=0,
            calls=0,
            sent_chars=0,
            skills=2,
            unused=2,
        ),
    ]
    worker_agent, review_agent = found.agents
    assert (worker_agent.call_chars, review_agent.call_chars) == (170, None)
    assert (found.runs, found.said, found.counted) == (3, 3, 2)
    assert (found.sent_chars, found.sent_tokens) == (5100, 5100 // spend.CHARS_PER_TOKEN)
    assert tracker["canopy-worker"].sent_tokens == 92 * 30 // spend.CHARS_PER_TOKEN
    assert tracker["canopy-worker"].result_tokens == 12_100 // spend.CHARS_PER_TOKEN


def test_what_the_journal_cannot_say_is_counted_apart(conn: sqlite3.Connection) -> None:
    """A run not asked about, one not answered for, an offer with no length, and a session not read: none is a zero."""
    day = earlier(NOW, 1)
    old, failed, unasked = worker(conn, day), worker(conn, day), worker(conn, day)
    # An offer from before canopy kept a description's length: offered, and its cost unknown.
    offered(conn, "runs", old, "canopy-worker", sized=False)
    called(conn, "runs", old, 5)
    run_offers.record(conn, "runs", failed, AgentOffer("canopy-worker", error="the runtime had not answered"))
    # A run the runtime was never asked about loads skills all the same: no offer of them is on record.
    called(conn, "runs", unasked, 3, ToolUse("skill:terse", 1, 0, 300), ToolUse("skill", 2, 1, 50))
    called(conn, "task_runs", task(conn, day), 2, ToolUse("skill:tracker-jira", 1, 0, 4000))
    worker(conn, day, kind=RunKind.PLAN)
    worker(conn, day, private=True)
    found = skill_report.report(conn, NOW, 7)
    by_agent = {a.agent: a for a in found.agents}
    # In canopy's order: the worker, the private worker a task's run is, then the planner a plan's is.
    assert list(by_agent) == ["canopy-worker", "canopy-worker-private", "canopy-planner"]
    shared = by_agent["canopy-worker"]
    assert (shared.runs, shared.said, shared.unanswered, shared.unasked) == (3, 1, 1, 1)
    assert (shared.sized, shared.counted, shared.calls, shared.sent_chars, shared.call_chars) == (0, 0, 0, 0, None)
    assert (by_agent["canopy-worker-private"].runs, by_agent["canopy-worker-private"].unasked) == (2, 2)
    assert (by_agent["canopy-planner"].runs, by_agent["canopy-planner"].unasked) == (1, 1)
    tracker = uses(found, "tracker-jira")
    assert (tracker["canopy-worker"].offered, tracker["canopy-worker"].front_matter_chars) == (1, None)
    assert (tracker["canopy-worker"].counted, tracker["canopy-worker"].sent_chars) == (0, 0)
    loaded_by_task = tracker["canopy-worker-private"]
    assert (loaded_by_task.offered, loaded_by_task.unoffered, loaded_by_task.loads) == (0, 1, 1)
    terse = uses(found, "terse")["canopy-worker"]
    # Offered to one run, and loaded by another that has no offer on record.
    assert (terse.offered, terse.loaded, terse.unoffered, terse.loads, terse.result_chars) == (1, 0, 1, 1, 300)
    [tracker_row] = [s for s in found.skills if s.name == "tracker-jira"]
    # Loaded by a run of another agent's: not unused, though no run offered it loaded it.
    assert (tracker_row.offered, tracker_row.loaded, tracker_row.unoffered, tracker_row.unused) == (1, 0, 1, False)
    assert tracker_row.front_matter_chars is None
    # A call canopy could not read the skill of counts under no skill; the one that failed loaded nothing.
    assert found.unnamed == 1
    assert (found.runs, found.said, found.counted, found.sent_chars) == (6, 1, 0, 0)


def test_the_overseer_offered_no_skill_is_an_agent_that_carries_none(conn: sqlite3.Connection) -> None:
    """Its skill tool denied, it is sent no list: answered for, sized, and counted at nothing a call."""
    day = earlier(NOW, 1)
    ran = tick(conn, day)
    offered(conn, "ticks", ran, "canopy-overseer", {})
    called(conn, "ticks", ran, 4)
    # A tick that ran no overseer is no agent's run.
    tick(conn, day, overseer_ran=0)
    found = skill_report.report(conn, NOW, 7)
    [overseer] = found.agents
    assert overseer == skill_report.Agent(
        agent="canopy-overseer",
        runs=1,
        said=1,
        unanswered=0,
        sized=1,
        counted=1,
        calls=4,
        sent_chars=0,
    )
    assert overseer.call_chars == 0
    assert found.skills == []


def test_a_skill_s_front_matter_is_its_newest_offer_s(conn: sqlite3.Connection) -> None:
    """A description shortened since: the row says what it costs now, and the sum what each run was sent."""
    before, after = worker(conn, earlier(NOW, 3)), worker(conn, earlier(NOW, 1))
    offered(conn, "runs", before, "canopy-worker", {"audit": 400})
    offered(conn, "runs", after, "canopy-worker", {"audit": 95})
    called(conn, "runs", before, 10)
    called(conn, "runs", after, 10)
    # A chore's copy of the agent, on a model of its own, sits after the chores' own agent, and has its own offers.
    copy = chore(conn, earlier(NOW, 2))
    offered(conn, "chore_runs", copy, "canopy-chore-deps", {"audit": 250})
    found = skill_report.report(conn, NOW, 7)
    [audit] = found.skills
    assert [u.agent for u in audit.uses] == ["canopy-worker", "canopy-chore-deps"]
    assert [u.front_matter_chars for u in audit.uses] == [100, 255]
    # The skill's own is the newest of any agent's.
    assert audit.front_matter_chars == 100
    assert audit.sent_chars == 405 * 10 + 100 * 10
    assert (audit.offered, audit.counted, audit.calls) == (3, 2, 20)


def test_a_skill_the_runtime_names_outside_its_rule_is_not_called_unused(conn: sqlite3.Connection) -> None:
    """A load is counted under a name of the runtime's rule alone, so one named otherwise only looks never loaded."""
    ran = worker(conn, earlier(NOW, 1))
    offered(conn, "runs", ran, "canopy-worker", {"My_Skill": 10, "terse": 0})
    called(conn, "runs", ran, 2, ToolUse("skill", 1, 0, 900))
    found = skill_report.report(conn, NOW, 7)
    rows = [(s.name, s.countable, s.unused) for s in found.skills]
    assert rows == [("My_Skill", False, False), ("terse", True, True)]
    assert (found.offered, found.unused, found.unnamed) == (2, 1, 1)
    [agent] = found.agents
    assert (agent.skills, agent.unused) == (2, 1)


def test_only_the_window_s_ended_runs_are_read(conn: sqlite3.Connection) -> None:
    """By when a run started, in whole local days; a run still running has recorded nothing to read."""
    for started in (earlier(NOW, 9), earlier(NOW, 1)):
        ran = worker(conn, started)
        offered(conn, "runs", ran, "canopy-worker", {"terse": 0})
    running = worker(conn, earlier(NOW, 0), ended=False)
    offered(conn, "runs", running, "canopy-worker", {"terse": 0})
    found = skill_report.report(conn, NOW, 7)
    assert (found.since, found.until, found.days) == ("2026-11-02T00:00:00.000Z", "2026-11-09T00:00:00.000Z", 7)
    assert [(s.name, s.offered) for s in found.skills] == [("terse", 1)]
    before = skill_report.between(conn, *spend.window_before(found.since, 7))
    assert (before.until, before.days) == (found.since, 7)
    assert [(s.name, s.offered) for s in before.skills] == [("terse", 1)]
    empty = skill_report.between(conn, NOW - timedelta(days=40), NOW - timedelta(days=30))
    assert (empty.skills, empty.agents, empty.unnamed) == ([], [], 0)
    assert (empty.offered, empty.unused, empty.loads, empty.runs, empty.sent_tokens) == (0, 0, 0, 0, 0)


def test_each_read_starts_from_the_window_s_runs(tmp_path: Path, journals: Journals) -> None:
    """The run table leads, by its `started_at` index, so a window's cost is its own runs', not the whole history's.

    A journal in a test is too small for a slow plan to show in its time, so the plan is what is held.
    """
    conn = journals.open(tmp_path / "canopy.db")
    since, until = earlier(NOW, 7), earlier(NOW, 0)
    for query in (
        skill_report._offered(since, until),  # noqa: SLF001
        skill_report._loaded(since, until),  # noqa: SLF001
        skill_report._ran(since, until),  # noqa: SLF001
    ):
        plan = [str(row[3]) for row in sql.execute(conn, sql.frag("EXPLAIN QUERY PLAN {}", query))]
        runs = [step for step in plan if re.match(r"(SEARCH|SCAN) r\b", step)]
        assert runs, plan
        for step in runs:
            assert re.match(r"SEARCH r USING (COVERING )?INDEX \w+ \(started_at>\? AND started_at<\?\)", step), plan
        keyed = [step for step in plan if re.match(r"(SEARCH|SCAN) [ost]\b", step)]
        assert keyed, plan
        for step in keyed:
            assert re.match(r"SEARCH [ost] USING PRIMARY KEY \(run_table=\? AND run_id=\?", step), plan
