"""Which skills the agent runs of a window were offered, which they loaded, and what each one's front matter cost.

For the web UI's Skills report (DESIGN §13). A skill an agent is offered rides in every model call of its runs, by its
name and its description, loaded or not; one it loads puts its text into the run's context besides. Both are in the
journal, by run: what the runtime said it offered each run it was asked about (`canopy.core.run_offers`), and each
run's calls of the skill tool, by the skill they loaded (`run_tools`). This reads them over the runs that started in a
window and have ended, by the agent each ran and the skill.

What the journal cannot say is counted apart, never as nothing: a run the runtime was not asked about (a task's, an
epic's plan, or one from before canopy asked), one it could not answer for, an offer from before canopy kept a
description's length, and a run whose session, which says how many model calls it made, is not read. A front matter
cost is counted only over the runs where the length and the model calls are both known.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final, LiteralString

from canopy.core import db, records, spend, sql
from canopy.core.vocab import RunKind
from canopy.runtime import agents as names
from canopy.runtime.definitions import MAX_SKILL_NAME, SKILL_NAME_RE
from canopy.runtime.report import SKILL_PREFIX

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import datetime

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


@dataclass(frozen=True)
class Use:
    """One agent's use of one skill over a window: the runs offered it, those that loaded it, and what it cost."""

    agent: str
    skill: str
    #: The agent's runs the runtime said it offered the skill.
    offered: int = 0
    #: Of those, the runs that loaded it: a call of the skill tool for it that did not fail.
    loaded: int = 0
    #: The agent's runs that loaded it with no offer of it on record: a run the runtime was not asked about, or could
    #: not answer for.
    unoffered: int = 0
    #: Its loads in every run of the agent's, offered it on record or not: the calls for it that did not fail.
    loads: int = 0
    #: The calls for it that failed, such as one for a skill the agent is denied.
    failed: int = 0
    #: The characters its loads returned into the runs' context: its text, as the skill tool gave it.
    result_chars: int = 0
    #: Its front matter at the newest offer that recorded it, in characters: its name and its description. None when
    #: no offer of the window did.
    front_matter_chars: int | None = None
    #: The offered runs its front matter's cost is counted over: those whose offer recorded its description's length
    #: and whose session, read, says how many model calls the run made.
    counted: int = 0
    #: The model calls those runs made, each of which carried its front matter.
    calls: int = 0
    #: What its front matter added to those calls, in characters: its length at each run, times the run's calls.
    sent_chars: int = 0

    @property
    def sent_tokens(self) -> int:
        """About how many tokens its front matter added to the counted runs' model calls: an estimate."""
        return self.sent_chars // spend.CHARS_PER_TOKEN

    @property
    def result_tokens(self) -> int:
        """About how many tokens its loads returned: an estimate."""
        return self.result_chars // spend.CHARS_PER_TOKEN


@dataclass(frozen=True)
class Skill:
    """One skill over a window: each agent's use of it, and whether its loads can be counted under its name."""

    name: str
    #: Each agent that was offered it or loaded it, in `AGENTS` order, then any other by name.
    uses: Sequence[Use]
    #: Whether a load of it is counted under its name: the runtime counts one under a name of its own rule alone, so a
    #: skill named otherwise reads as never loaded however often it is. Its loads are then among `Skills.unnamed`.
    countable: bool = True
    #: Its front matter at the newest offer of any agent's that recorded it, in characters; None when none did.
    front_matter_chars: int | None = None

    @property
    def offered(self) -> int:
        """The runs offered it, of every agent."""
        return sum(u.offered for u in self.uses)

    @property
    def loaded(self) -> int:
        """Of the runs offered it, those that loaded it."""
        return sum(u.loaded for u in self.uses)

    @property
    def unoffered(self) -> int:
        """The runs that loaded it with no offer of it on record."""
        return sum(u.unoffered for u in self.uses)

    @property
    def loads(self) -> int:
        """Its loads, in every run."""
        return sum(u.loads for u in self.uses)

    @property
    def failed(self) -> int:
        """The calls for it that failed."""
        return sum(u.failed for u in self.uses)

    @property
    def result_chars(self) -> int:
        """The characters its loads returned."""
        return sum(u.result_chars for u in self.uses)

    @property
    def counted(self) -> int:
        """The offered runs its front matter's cost is counted over."""
        return sum(u.counted for u in self.uses)

    @property
    def calls(self) -> int:
        """The model calls of the counted runs."""
        return sum(u.calls for u in self.uses)

    @property
    def sent_chars(self) -> int:
        """What its front matter added to the counted runs' model calls, in characters."""
        return sum(u.sent_chars for u in self.uses)

    @property
    def unused(self) -> bool:
        """Whether it was offered and never loaded, by any agent, where a load of it would have been counted."""
        return self.countable and self.offered > 0 and self.loads == 0


@dataclass(frozen=True)
class Agent:
    """One agent's runs over a window: how many the runtime answered for, and what their lists of skills cost."""

    agent: str
    #: Its runs that started in the window and have ended.
    runs: int
    #: Of those, the runs the runtime said what it offered.
    said: int
    #: The runs the runtime was asked about and could not answer for.
    unanswered: int
    #: Of the runs it answered for, those whose offer recorded every offered skill's description length.
    sized: int
    #: Of those, the runs whose session, read, says how many model calls they made: what a cost is counted over.
    counted: int
    #: The model calls the counted runs made.
    calls: int
    #: What the front matter of every skill offered added to those calls, in characters.
    sent_chars: int
    #: How many skills its runs were offered, by name.
    skills: int = 0
    #: Of those, the ones none of its runs loaded, where a load would have been counted.
    unused: int = 0

    @property
    def unasked(self) -> int:
        """Its runs the runtime was never asked about: a task's, an epic's plan, or one from before canopy asked."""
        return self.runs - self.said - self.unanswered

    @property
    def call_chars(self) -> int | None:
        """What the skills' front matter added to one of its model calls, the counted runs' mean, in characters.

        Returns:
            The characters; None when no model call is counted.
        """
        return round(self.sent_chars / self.calls) if self.calls else None


@dataclass(frozen=True)
class Skills:
    """The skills the runs that started in a window, `[since, until)`, were offered and loaded: by skill, by agent."""

    since: str
    until: str
    days: int
    #: A row per skill a run was offered or loaded, by name.
    skills: Sequence[Skill] = ()
    #: A row per agent that ran, in `AGENTS` order, then any other by name.
    agents: Sequence[Agent] = ()
    #: The loads canopy could not read the skill of, which count under no skill.
    unnamed: int = 0

    @property
    def offered(self) -> int:
        """How many skills a run was offered."""
        return sum(1 for s in self.skills if s.offered)

    @property
    def unused(self) -> int:
        """How many of those no run loaded."""
        return sum(1 for s in self.skills if s.unused)

    @property
    def loads(self) -> int:
        """The loads, of every skill canopy could name."""
        return sum(s.loads for s in self.skills)

    @property
    def runs(self) -> int:
        """The window's runs, of every agent."""
        return sum(a.runs for a in self.agents)

    @property
    def said(self) -> int:
        """Of those, the runs the runtime said what it offered."""
        return sum(a.said for a in self.agents)

    @property
    def counted(self) -> int:
        """Of those, the runs a front matter cost is counted over."""
        return sum(a.counted for a in self.agents)

    @property
    def sent_chars(self) -> int:
        """What the skills' front matter added to the counted runs' model calls, in characters."""
        return sum(a.sent_chars for a in self.agents)

    @property
    def sent_tokens(self) -> int:
        """About how many tokens that is: an estimate."""
        return self.sent_chars // spend.CHARS_PER_TOKEN


def report(conn: sqlite3.Connection, now: datetime, days: int) -> Skills:
    """The skills the runs of the last `days` local days, today's so far included, were offered and loaded.

    Returns:
        The report; a window with no run in it has no skill and no agent.
    """
    return between(conn, *spend.window(now, days))


def between(conn: sqlite3.Connection, start: datetime, end: datetime) -> Skills:
    """The skills the runs that started from one local midnight, `start`, to another, `end`, were offered and loaded.

    Returns:
        The report, as `report` gives it for any such window: the one before a page's among them.
    """
    since = db.format_time(start)
    until = db.format_time(end)
    with db.read_snapshot(conn):
        offers = records.fetch_all(conn, _Offered, _offered(since, until))
        loads = records.fetch_all(conn, _Loaded, _loaded(since, until))
        ran = records.fetch_all(conn, _Ran, _ran(since, until))
    uses = _uses(offers, [load for load in loads if load.skill])
    skills = [
        Skill(
            name=name,
            uses=by_agent,
            countable=_countable(name),
            front_matter_chars=_newest(o for o in offers if o.skill == name),
        )
        for name, by_agent in sorted(uses.items())
    ]
    return Skills(
        since=since,
        until=until,
        days=spend.days_between(start, end),
        skills=skills,
        agents=_agents(ran, skills),
        unnamed=sum(load.loads for load in loads if not load.skill),
    )


@dataclass(frozen=True)
class _Offered(records.View):
    """One agent's runs that were offered one skill: how many, how many loaded it, and what its front matter cost."""

    agent: str
    skill: str
    offered: int
    loaded: int
    counted: int
    calls: int
    sent_chars: int
    #: The newest offer that recorded its description's length: when the run started, a space, and the front matter's
    #: characters; None when none did.
    newest: str | None


@dataclass(frozen=True)
class _Loaded(records.View):
    """One agent's calls of the skill tool for one skill: `skill` is empty for those canopy could not read it of."""

    agent: str
    skill: str
    loads: int
    failed: int
    result_chars: int
    #: The runs that loaded it with no offer of it on record.
    unoffered: int


@dataclass(frozen=True)
class _Ran(records.View):
    """One agent's runs: how many, and how far the journal says what they were offered and how often they called."""

    agent: str
    runs: int
    said: int
    unanswered: int
    sized: int
    counted: int
    calls: int
    sent_chars: int


#: The run tables whose runs the runtime is asked about as they start (`run_offers.probing`): the rest record no offer.
_ASKED: Final[tuple[RunTable, ...]] = ("ticks", "runs", "chore_runs", "review_runs")
#: Every table of agent runs, whose calls of the skill tool are all recorded.
_TABLES: Final[tuple[RunTable, ...]] = (*_ASKED, "task_runs", "epic_runs")
#: A run `r` of the window: one that started in it and has ended, so what it called is recorded.
_WINDOW: LiteralString = "r.started_at >= ? AND r.started_at < ? AND r.ended_at IS NOT NULL"
#: Which of a table's rows are an agent's runs: every one, but a tick that ran no overseer.
_EVERY = sql.frag("1")
_RUNS: Mapping[RunTable, sql.Fragment] = {"ticks": sql.frag("r.overseer_ran IS NOT 0")}
#: The agent a run `r` of each table ran, where its offer does not name one: the one canopy ships for its kind of run
#: (DESIGN §13). A plan's is the planner, as a feedback plan's is; a private repository's worker is its own.
_SHIPPED: Mapping[RunTable, sql.Fragment] = {
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
#: How many model calls a run `r` made, as its session's record says once read: NULL until it is, or when it names no
#: model. The `?` is the run's table.
_CALLS: LiteralString = "(SELECT SUM(m.replies) FROM run_models m WHERE m.run_table = ? AND m.run_id = r.id)"
#: A figure, the `{}`, over the skills a run `r` was offered. The `?` is the run's table.
_LIST: LiteralString = "(SELECT {} FROM run_offered_skills s WHERE s.run_table = ? AND s.run_id = r.id)"
#: What a call of the skill tool is counted under when canopy cannot read which skill it loaded: the tool's own name.
_UNNAMED: Final = SKILL_PREFIX.removesuffix(":")


# Each agent's runs that were offered each skill. The run table leads, through its `_spent` index on `started_at`, and
# the offer's tables are read by their keys' prefix: `CROSS JOIN` keeps SQLite from reordering them (`spend._tools_of`).
def _offered(since: str, until: str) -> sql.Select:
    each = [
        sql.select(
            "coalesce(o.agent, {}) AS agent, s.skill AS skill, r.started_at AS started_at, "
            "length(s.skill) + s.description_chars AS chars, {} AS calls, coalesce(t.calls > t.errors, 0) AS loaded",
            _SHIPPED[table],
            sql.frag(_CALLS, table),
        )
        .from_(
            "{} r CROSS JOIN run_offers o ON o.run_table = ? AND o.run_id = r.id "
            "CROSS JOIN run_offered_skills s ON s.run_table = ? AND s.run_id = r.id "
            "LEFT JOIN run_tools t ON t.run_table = ? AND t.run_id = r.id AND t.tool = ? || s.skill",
            sql.name(table),
            table,
            table,
            table,
            SKILL_PREFIX,
        )
        .where(_WINDOW, since, until)
        .where("{}", _RUNS.get(table, _EVERY))
        .where("o.error IS NULL")
        for table in _ASKED
    ]
    return (
        sql.select(
            "agent, skill, count(*) AS offered, SUM(loaded) AS loaded, count(chars * calls) AS counted, "
            "coalesce(SUM(CASE WHEN chars IS NOT NULL THEN calls END), 0) AS calls, "
            "coalesce(SUM(chars * calls), 0) AS sent_chars, max(started_at || ' ' || chars) AS newest",
        )
        .from_("({}) AS u", sql.union(*each, every=True))
        .group_by("agent, skill")
    )


# Each agent's calls of the skill tool, by the skill they loaded, in every kind of run: a run the runtime was not asked
# about loads skills too. A row of calls that all failed loaded nothing, and what it returned is its errors' text.
def _loaded(since: str, until: str) -> sql.Select:
    after = len(SKILL_PREFIX) + 1
    each = [
        sql.select(
            "coalesce(o.agent, {}) AS agent, substr(t.tool, ?) AS skill, t.calls - t.errors AS loads, "
            "t.errors AS failed, t.result_chars AS chars, s.run_id IS NULL AS unoffered",
            _SHIPPED[table],
            after,
        )
        .from_(
            "{} r CROSS JOIN run_tools t ON t.run_table = ? AND t.run_id = r.id "
            "LEFT JOIN run_offers o ON o.run_table = ? AND o.run_id = r.id "
            "LEFT JOIN run_offered_skills s ON s.run_table = ? AND s.run_id = r.id AND s.skill = substr(t.tool, ?)",
            sql.name(table),
            table,
            table,
            table,
            after,
        )
        .where(_WINDOW, since, until)
        .where("{}", _RUNS.get(table, _EVERY))
        .where("t.tool = ? OR substr(t.tool, 1, ?) = ?", _UNNAMED, len(SKILL_PREFIX), SKILL_PREFIX)
        for table in _TABLES
    ]
    return (
        sql.select(
            "agent, skill, SUM(loads) AS loads, SUM(failed) AS failed, "
            "SUM(CASE WHEN loads > 0 THEN chars ELSE 0 END) AS result_chars, "
            "SUM(loads > 0 AND unoffered) AS unoffered",
        )
        .from_("({}) AS u", sql.union(*each, every=True))
        .group_by("agent, skill")
    )


# Each agent's runs, and how far the journal says what they were offered and how often they called a model. A run is
# `sized` when every skill it was offered has its description's length, as one offered none does. Its skills are
# summed run by run rather than joined and grouped, which would have SQLite walk the run table whole, by its key.
def _ran(since: str, until: str) -> sql.Select:
    each = [
        sql.select(
            "coalesce(o.agent, {}) AS agent, o.run_id IS NOT NULL AND o.error IS NULL AS said, "
            "o.error IS NOT NULL AS unanswered, {} AS sized, {} AS calls, {} AS chars",
            _SHIPPED[table],
            sql.frag(_LIST, sql.frag("count(*) = count(s.description_chars)"), table),
            sql.frag(_CALLS, table),
            sql.frag(_LIST, sql.frag("coalesce(SUM(length(s.skill) + s.description_chars), 0)"), table),
        )
        .from_("{} r LEFT JOIN run_offers o ON o.run_table = ? AND o.run_id = r.id", sql.name(table), table)
        .where(_WINDOW, since, until)
        .where("{}", _RUNS.get(table, _EVERY))
        for table in _TABLES
    ]
    return (
        sql.select(
            "agent, count(*) AS runs, SUM(said) AS said, SUM(unanswered) AS unanswered, "
            "SUM(said AND sized) AS sized, SUM(said AND sized AND calls IS NOT NULL) AS counted, "
            "coalesce(SUM(CASE WHEN said AND sized THEN calls END), 0) AS calls, "
            "coalesce(SUM(CASE WHEN said AND sized THEN chars * calls END), 0) AS sent_chars",
        )
        .from_("({}) AS u", sql.union(*each, every=True))
        .group_by("agent")
    )


def _uses(offers: Iterable[_Offered], loads: Iterable[_Loaded]) -> dict[str, list[Use]]:
    """Each skill's use by each agent, from the runs offered it and the calls that loaded it.

    Returns:
        The uses by skill, each skill's in the agents' order.
    """
    found: dict[tuple[str, str], Use] = {}
    for o in offers:
        found[o.skill, o.agent] = Use(
            agent=o.agent,
            skill=o.skill,
            offered=o.offered,
            loaded=o.loaded,
            front_matter_chars=_newest([o]),
            counted=o.counted,
            calls=o.calls,
            sent_chars=o.sent_chars,
        )
    for load in loads:
        use = found.get((load.skill, load.agent), Use(agent=load.agent, skill=load.skill))
        found[load.skill, load.agent] = replace(
            use,
            unoffered=load.unoffered,
            loads=load.loads,
            failed=load.failed,
            result_chars=load.result_chars,
        )
    by_skill: dict[str, list[Use]] = {}
    for use in sorted(found.values(), key=lambda u: _agent_order(u.agent)):
        by_skill.setdefault(use.skill, []).append(use)
    return by_skill


def _agents(ran: Iterable[_Ran], skills: Sequence[Skill]) -> list[Agent]:
    """Each agent that ran, with how many skills its runs were offered and how many of those none of them loaded.

    Returns:
        The agents, in their order.
    """
    uses = [u for s in skills for u in s.uses if u.offered]
    countable = {s.name for s in skills if s.countable}
    return [
        Agent(
            agent=r.agent,
            runs=r.runs,
            said=r.said,
            unanswered=r.unanswered,
            sized=r.sized,
            counted=r.counted,
            calls=r.calls,
            sent_chars=r.sent_chars,
            skills=sum(1 for u in uses if u.agent == r.agent),
            unused=sum(1 for u in uses if u.agent == r.agent and u.loads == 0 and u.skill in countable),
        )
        for r in sorted(ran, key=lambda r: _agent_order(r.agent))
    ]


# The front matter's characters at the newest of the offers that recorded it, by when each one's run started.
def _newest(offers: Iterable[_Offered]) -> int | None:
    stamped = max((o.newest for o in offers if o.newest is not None), default=None)
    return None if stamped is None else int(stamped.rpartition(" ")[2])


# Where an agent sits among the rows: canopy's own first, in `AGENTS` order, a chore's copy after the chores', then
# any other by name.
def _agent_order(agent: str) -> tuple[int, str]:
    if agent in AGENTS:
        return AGENTS.index(agent), ""
    if agent.startswith(names.CHORE_COPY_PREFIX):
        return AGENTS.index(names.CHORE), agent
    return len(AGENTS), agent


# Whether a load of a skill is counted under its name, by the rule the runtime's events are read with.
def _countable(skill: str) -> bool:
    return len(skill) <= MAX_SKILL_NAME and SKILL_NAME_RE.fullmatch(skill) is not None
