"""What the mock journal's agent runs were offered and loaded of skills (DESIGN §13), for the Skills report.

The day's runs, each as the runtime answered for it when it started. Every agent but the overseer, whose skill tool is
denied, is offered the four skills found wherever a run starts: the tracker's, which the prompts say to load first, so
most runs do; `release-notes`, which only workers load; and `terse` and `write-a-skill`, which nothing loads. The
shared worker is offered `canopy-artifacts` too, and never loads it. A run in `web`'s worktrees is offered the two
skills that repository keeps for itself, which the skills page does not list: `design-system`, whose long description
rides in every call and which one run loaded, and `e2e-playwright`. One in `mobile`'s is offered `store-listing`, and
none loads it. Each offer records its skills' descriptions' lengths, the five the page lists at what it says of them.

What the journal cannot say is there too: a review run the runtime did not answer for, the tasks' and the epics' plan
runs, which are never asked about and loaded the tracker's skill all the same, a call that named no skill, a call for
the operator's own skill, which every agent is denied, and the workers' runs of the weeks before, whose offers are
from before canopy kept a description's length. A front matter's cost is counted over the runs whose sessions `_models`
read: the planner's are not, so its list has no cost yet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from canopy.core import records
from canopy.core.vocab import RunKind
from canopy.runtime import agents
from canopy.runtime.report import SKILL_PREFIX
from canopy.serve.mock import skills

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable, Mapping

    from canopy.core.run_models import RunTable

#: The chore that runs on a model of its own, so as its own copy of the chores' agent (the mock's `CHORE`).
_DEPS: Final = agents.chore_agent("deps")
#: The skills found wherever a run starts, and those a run in one repository's worktrees is offered besides.
_EVERYWHERE: Final = ("release-notes", "terse", "tracker-jira", "write-a-skill")
_WEB: Final = ("design-system", "e2e-playwright")
_MOBILE: Final = ("store-listing",)
#: How long each skill's description is, in characters: the listed skills' as the skills page says them, then the
#: repositories' own.
_DESCRIBED: Final[Mapping[str, int]] = {
    **{name: len(said or "") for name, said in skills.DESCRIPTIONS.items()},
    "design-system": 913,
    "e2e-playwright": 248,
    "store-listing": 382,
}
#: Each run the runtime answered for: its table and id, the agent its command runs, and the skills it was offered.
_OFFERS: Final[tuple[tuple[RunTable, int, str, tuple[str, ...]], ...]] = (
    ("ticks", 1, agents.OVERSEER, ()),
    ("ticks", 2, agents.OVERSEER, ()),
    ("runs", 37, agents.WORKER, ("canopy-artifacts", *_EVERYWHERE, *_WEB)),
    ("runs", 39, agents.WORKER, ("canopy-artifacts", *_EVERYWHERE, *_WEB)),
    ("runs", 40, agents.WORKER, ("canopy-artifacts", *_EVERYWHERE, *_WEB)),
    ("runs", 45, agents.WORKER, ("canopy-artifacts", *_EVERYWHERE, *_WEB)),
    ("runs", 38, agents.PRIVATE_WORKER, (*_EVERYWHERE, *_WEB)),
    ("runs", 42, agents.PRIVATE_WORKER, (*_EVERYWHERE, *_MOBILE)),
    ("runs", 65, agents.PLANNER, (*_EVERYWHERE, *_WEB)),
    ("runs", 35, agents.PLANNER, (*_EVERYWHERE, *_MOBILE)),
    ("runs", 44, agents.PLANNER, (*_EVERYWHERE, *_MOBILE)),
    ("runs", 47, agents.PLANNER, (*_EVERYWHERE, *_WEB)),
    ("runs", 46, agents.PLANNER, (*_EVERYWHERE, *_WEB)),
    ("review_runs", 1, agents.REVIEWER, (*_EVERYWHERE, *_WEB)),
    ("review_runs", 2, agents.REVIEWER, (*_EVERYWHERE, *_WEB)),
    ("review_runs", 4, agents.REVIEWER, (*_EVERYWHERE, *_WEB)),
    ("review_runs", 5, agents.REVIEWER, _EVERYWHERE),
    ("review_runs", 6, agents.REVIEWER, _EVERYWHERE),
    ("chore_runs", 1, _DEPS, _EVERYWHERE),
    ("chore_runs", 2, _DEPS, _EVERYWHERE),
    ("chore_runs", 3, agents.CHORE, _EVERYWHERE),
)
#: The review run the runtime did not answer for, and canopy's words for why.
_UNANSWERED: Final = ("review_runs", 3, "the runtime had not answered 60 seconds after the run ended")
#: Each run's calls of the skill tool, by the skill: its table and id, the skill, its calls, how many failed, and the
#: characters they returned. A skill's text is the same each load; the worker of run 45 loaded one twice. The tasks'
#: and the epic's runs loaded skills with no offer on record, and run 38 asked for the operator's skill, denied to it.
_LOADS: Final[tuple[tuple[RunTable, int, str, int, int, int], ...]] = (
    ("runs", 37, "tracker-jira", 1, 0, 3_250),
    ("runs", 37, "release-notes", 1, 0, 1_100),
    ("runs", 37, "e2e-playwright", 1, 0, 5_200),
    ("runs", 39, "tracker-jira", 1, 0, 3_250),
    ("runs", 39, "release-notes", 1, 0, 1_100),
    ("runs", 39, "design-system", 1, 0, 9_400),
    ("runs", 40, "tracker-jira", 1, 0, 3_250),
    ("runs", 40, "e2e-playwright", 1, 0, 5_200),
    ("runs", 45, "tracker-jira", 1, 0, 3_250),
    ("runs", 45, "release-notes", 2, 0, 2_200),
    ("runs", 38, "tracker-jira", 1, 0, 3_250),
    ("runs", 38, "e2e-playwright", 1, 0, 5_200),
    ("runs", 38, "canopy", 1, 1, 60),
    ("runs", 42, "tracker-jira", 1, 0, 3_250),
    ("runs", 65, "tracker-jira", 1, 0, 3_250),
    ("runs", 35, "tracker-jira", 1, 0, 3_250),
    ("runs", 44, "tracker-jira", 1, 0, 3_250),
    ("runs", 47, "tracker-jira", 1, 0, 3_250),
    ("review_runs", 1, "tracker-jira", 1, 0, 3_250),
    ("review_runs", 2, "tracker-jira", 1, 0, 3_250),
    ("task_runs", 1, "tracker-jira", 1, 0, 3_250),
    ("task_runs", 5, "tracker-jira", 1, 0, 3_250),
    ("task_runs", 5, "release-notes", 1, 0, 1_100),
    ("epic_runs", 1, "tracker-jira", 1, 0, 3_250),
)
#: A call of the skill tool that named no skill canopy could read, counted under the tool's own name: run 42's.
_UNNAMED: Final[tuple[RunTable, int, str, int, int, int]] = ("runs", 42, SKILL_PREFIX.removesuffix(":"), 1, 0, 900)
#: How far back the day's runs go, in minutes before T0: a worker's run before it is one of the weeks before.
_DAY_BEFORE: Final = -24 * 60


def seed(conn: sqlite3.Connection, at: Callable[[int], str]) -> None:
    """Record the offers and the loads on the runs the other fixtures made, `at` turning minutes after T0 into a time.

    After every other fixture, since it names their runs.
    """
    asked = at(0)
    table, run_id, error = _UNANSWERED
    records.insert(records.RunOffer, run_table=table, run_id=run_id, agent=None, error=error, asked_at=asked).run(conn)
    before = (
        records.select(records.Run).where("kind = ? AND started_at < ?", RunKind.IMPLEMENT, at(_DAY_BEFORE)).all(conn)
    )
    old = [("runs", run.id, agents.WORKER, _EVERYWHERE) for run in before]
    offers = records.insert_rows(records.RunOffer, ("run_table", "run_id", "agent", "error", "asked_at"))
    offers.many(conn, [(table, run_id, agent, None, asked) for table, run_id, agent, _ in (*_OFFERS, *old)])
    offered = records.insert_rows(records.RunOfferedSkill, ("run_table", "run_id", "skill", "description_chars"))
    offered.many(
        conn,
        [(table, run_id, skill, _DESCRIBED[skill]) for table, run_id, _, listed in _OFFERS for skill in listed],
    )
    # The weeks before: offered the same, with no length kept, and each loaded the tracker's skill.
    offered.many(conn, [(table, run_id, skill, None) for table, run_id, _, listed in old for skill in listed])
    loads = [
        (table, run_id, SKILL_PREFIX + skill, calls, errors, chars)
        for table, run_id, skill, calls, errors, chars in _LOADS
    ]
    loads += [(table, run_id, f"{SKILL_PREFIX}tracker-jira", 1, 0, 3_250) for table, run_id, _, _ in old]
    records.insert_rows(records.RunTool, ("run_table", "run_id", "tool", "calls", "errors", "result_chars")).many(
        conn,
        [*loads, _UNNAMED],
    )
