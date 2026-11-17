"""Which skills a window's runs were offered and loaded, and what each one's front matter cost (DESIGN §13).

Over a hand-written journal: runs of each kind, what the runtime said it offered them, the calls of the skill tool
they recorded, and the model calls their sessions name.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from canopy.core import run_offers, skill_report, spend, sql
from canopy.core.vocab import RunKind
from canopy.runtime.agents import AgentOffer
from canopy.runtime.report import ToolUse
from tests.canopy.helpers import earlier
from tests.canopy.report_helpers import called, chore, review, task, tick, worker

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping
    from pathlib import Path

    from canopy.core.run_models import RunTable
    from tests.conftest import Journals

NOW: Final = datetime(2026, 11, 8, 12, tzinfo=UTC)
#: How long the tests' offers say each skill's entry in the runtime's list is: its front matter, as a call carries it.
SIZES: Final = {"tracker-jira": 92, "release-notes": 73, "terse": 5}


def offered(
    conn: sqlite3.Connection,
    table: RunTable,
    run_id: int,
    agent: str,
    sizes: Mapping[str, int] = SIZES,
    *,
    sized: bool = True,
) -> None:
    """What the runtime said it offered a run: the skills of `sizes`, each with its entry's length if `sized`."""
    offer = AgentOffer(agent, skills=tuple(sizes), listing_chars=sizes if sized else {})
    run_offers.record(conn, table, run_id, offer)


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
    offered(conn, "review_runs", reviewer, "canopy-reviewer", {"tracker-jira": 92, "terse": 5})
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
        front_matter_chars=92,
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
    assert uses(found, "terse")["canopy-worker"].front_matter_chars == 5
    assert (found.offered, found.unused, found.loads) == (3, 2, 3)
    assert [s.name for s in found.skills if s.unused] == ["release-notes", "terse"]
    assert found.agents == [
        skill_report.Agent(
            agent="canopy-worker",
            runs=2,
            said=2,
            unanswered=0,
            listed=2,
            unsized=0,
            unread=0,
            counted=2,
            calls=30,
            sent_chars=(92 + 73 + 5) * 30,
            skills=3,
            unused=2,
            loads=3,
        ),
        skill_report.Agent(
            agent="canopy-reviewer",
            runs=1,
            said=1,
            unanswered=0,
            listed=1,
            unsized=0,
            # Its lengths are on record; its session, which says its model calls, is not read.
            unread=1,
            counted=0,
            calls=0,
            sent_chars=0,
            skills=2,
            unused=2,
        ),
    ]
    worker_agent, review_agent = found.agents
    tokens = spend.CHARS_PER_TOKEN
    assert (worker_agent.call_tokens, worker_agent.sent_tokens) == (170 // tokens, 5100 // tokens)
    # Offered skills, and no run counted: what its list costs is not known, which is not nothing.
    assert (review_agent.call_tokens, review_agent.sent_tokens) == (None, None)
    assert (found.runs, found.listed, found.unread, found.counted) == (3, 3, 1, 2)
    assert found.sent_tokens == 5100 // tokens
    # Over the calls counted, the worker's thirty: a mean, so the reviewer's run, not counted, moves it no way.
    assert found.call_tokens == 170 // tokens
    assert tracker["canopy-worker"].sent_tokens == 92 * 30 // tokens
    assert tracker["canopy-reviewer"].sent_tokens is None
    assert tracker["canopy-worker"].result_tokens == 12_100 // tokens


def test_what_the_journal_cannot_say_is_counted_apart(conn: sqlite3.Connection) -> None:
    """A run not asked about, one not answered for, an offer with no length, and a session not read: none is a zero."""
    day = earlier(NOW, 1)
    old, failed, unasked = worker(conn, day), worker(conn, day), worker(conn, day)
    # An offer from before canopy kept an entry's length: offered, and its cost unknown.
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
    # The one run answered for was offered skills with no length on record: nothing to count a cost over.
    assert (shared.listed, shared.unsized, shared.unread, shared.counted) == (1, 1, 0, 0)
    assert (shared.calls, shared.call_tokens, shared.sent_tokens) == (0, None, None)
    # Its loads canopy could name, and the one it could not, which may be of any skill of its.
    assert (shared.loads, shared.unnamed) == (1, 1)
    private = by_agent["canopy-worker-private"]
    assert (private.runs, private.unasked, private.said, private.loads) == (2, 2, 0, 1)
    # Never asked about, so not known to be offered none: no cost of nothing.
    assert (private.carries_none, private.call_tokens, private.sent_tokens) == (False, None, None)
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
    assert (found.runs, found.unanswered, found.unasked) == (6, 1, 4)
    assert (found.listed, found.unsized, found.unread, found.counted) == (1, 1, 0, 0)
    assert (found.sent_tokens, found.call_tokens) == (None, None)


def test_the_overseer_offered_no_skill_is_an_agent_that_carries_none(conn: sqlite3.Connection) -> None:
    """Its skill tool denied, it is sent no list: a known nothing a call, and no part of what a cost is counted over."""
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
        listed=0,
        unsized=0,
        unread=0,
        counted=0,
        calls=0,
        sent_chars=0,
    )
    assert (overseer.carries_none, overseer.call_tokens, overseer.sent_tokens) == (True, 0, 0)
    assert found.skills == []
    # No run offered a skill, so none is counted: the window has no cost to say, not a cost of nothing.
    assert (found.listed, found.counted, found.sent_tokens, found.call_tokens) == (0, 0, None, None)
    # Beside a worker's run, its calls thin no mean: the mean of a call is over the runs offered a skill.
    run = worker(conn, day)
    offered(conn, "runs", run, "canopy-worker", {"audit": 400})
    called(conn, "runs", run, 6)
    found = skill_report.report(conn, NOW, 7)
    assert (found.listed, found.counted) == (1, 1)
    assert found.call_tokens == 400 // spend.CHARS_PER_TOKEN
    assert found.sent_tokens == 400 * 6 // spend.CHARS_PER_TOKEN


def test_a_skill_s_front_matter_is_its_newest_offer_s(conn: sqlite3.Connection) -> None:
    """A description shortened since: the row says what it costs now, and the sum what each run was sent."""
    before, after = worker(conn, earlier(NOW, 3)), worker(conn, earlier(NOW, 1))
    offered(conn, "runs", before, "canopy-worker", {"audit": 405})
    offered(conn, "runs", after, "canopy-worker", {"audit": 100})
    called(conn, "runs", before, 10)
    called(conn, "runs", after, 10)
    # A chore's copy of the agent, on a model of its own, sits after the chores' own agent, and has its own offers.
    copy = chore(conn, earlier(NOW, 2))
    offered(conn, "chore_runs", copy, "canopy-chore-deps", {"audit": 255})
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
    offered(conn, "runs", ran, "canopy-worker", {"My_Skill": 18, "terse": 5})
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
        offered(conn, "runs", ran, "canopy-worker", {"terse": 5})
    running = worker(conn, earlier(NOW, 0), ended=False)
    offered(conn, "runs", running, "canopy-worker", {"terse": 5})
    found = skill_report.report(conn, NOW, 7)
    assert (found.since, found.until, found.days) == ("2026-11-02T00:00:00.000Z", "2026-11-09T00:00:00.000Z", 7)
    assert [(s.name, s.offered) for s in found.skills] == [("terse", 1)]
    before = skill_report.between(conn, *spend.window_before(found.since, 7))
    assert (before.until, before.days) == (found.since, 7)
    assert [(s.name, s.offered) for s in before.skills] == [("terse", 1)]
    empty = skill_report.between(conn, NOW - timedelta(days=40), NOW - timedelta(days=30))
    assert (empty.skills, empty.agents, empty.unnamed) == ([], [], 0)
    assert (empty.offered, empty.unused, empty.loads, empty.runs) == (0, 0, 0, 0)
    assert (empty.sent_tokens, empty.call_tokens) == (None, None)


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
