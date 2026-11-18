"""The agent runs of a window, as the reports of what they were offered read them (DESIGN §13).

Six tables hold agent runs, and the Skills and Tools reports read each the same way: the runs that started in a window
and have ended, each under the agent its offer names or, with no offer on record, the one canopy ships for its kind of
run. This holds what a query of them is built from, and the order a row per agent is listed in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, LiteralString

from canopy.core import sql
from canopy.core.vocab import RunKind
from canopy.runtime import agents as names

if TYPE_CHECKING:
    from collections.abc import Mapping

    from canopy.core.run_models import RunTable

#: The agents canopy ships, in the order a row per agent lists them; any other follows, by name.
AGENTS: Final = (
    names.OVERSEER,
    names.WORKER,
    names.PRIVATE_WORKER,
    names.PLANNER,
    names.REVIEWER,
    names.CHORE,
)
#: The run tables whose runs the runtime is asked about as they start (`run_offers.probing`): the rest record no offer.
ASKED: Final[tuple[RunTable, ...]] = ("ticks", "runs", "chore_runs", "review_runs")
#: Every table of agent runs, whose tool calls are all recorded.
TABLES: Final[tuple[RunTable, ...]] = (*ASKED, "task_runs", "epic_runs")
#: A run `r` of the window: one that started in it and has ended, so what it called is recorded. Its two `?` are the
#: window's start and its end.
WINDOW: Final[LiteralString] = "r.started_at >= ? AND r.started_at < ? AND r.ended_at IS NOT NULL"
#: The agent a run `r` of each table ran, where its offer does not name one: the one canopy ships for its kind of run
#: (DESIGN §13). A plan's is the planner, as a feedback plan's is; a private repository's worker is its own.
SHIPPED: Final[Mapping[RunTable, sql.Fragment]] = {
    "ticks": sql.frag("?", names.OVERSEER),
    "runs": sql.frag(
        "CASE WHEN {} THEN ? WHEN r.private THEN ? ELSE ? END",
        sql.in_("r.kind", (RunKind.PLAN, RunKind.FEEDBACK_PLAN)),
        names.PLANNER,
        names.PRIVATE_WORKER,
        names.WORKER,
    ),
    "chore_runs": sql.frag("?", names.CHORE),
    "review_runs": sql.frag("?", names.REVIEWER),
    "task_runs": sql.frag("?", names.PRIVATE_WORKER),
    "epic_runs": sql.frag("?", names.PLANNER),
}
#: Which of a table's rows are an agent's runs: every one, but a tick that ran no overseer.
_EVERY: Final = sql.frag("1")
_RUNS: Final[Mapping[RunTable, sql.Fragment]] = {"ticks": sql.frag("r.overseer_ran IS NOT 0")}


def ran(table: RunTable) -> sql.Fragment:
    """Which rows `r` of `table` are an agent's runs: every one, but a tick that ran no overseer.

    Returns:
        The condition, for a query's `where`.
    """
    return _RUNS.get(table, _EVERY)


def order(agent: str) -> tuple[int, str]:
    """Where an agent sits among a report's rows.

    Returns:
        A key to sort by: canopy's own first, in `AGENTS` order, a chore's copy after the chores', then any other by
        name.
    """
    if agent in AGENTS:
        return AGENTS.index(agent), ""
    if agent.startswith(names.CHORE_COPY_PREFIX):
        return AGENTS.index(names.CHORE), agent
    return len(AGENTS), agent
