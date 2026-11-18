"""Which MCP servers and tools the agent runs of a window were offered, which they called, and what came back.

For the web UI's Tools report (DESIGN §13). An agent's run is offered the runtime's own tools and the tools of each
MCP server its config turns on, and every one's definition rides in each of the run's model calls, called or not. Both
sides are in the journal, by run: what the runtime said it offered each run it was asked about
(`canopy.core.run_offers`), an MCP server by its name and the runtime's own tools each by theirs, and each run's calls
by tool, with the calls that failed and the characters they returned (`run_tools`). This reads them over the runs that
started in a window and have ended, by the agent each ran.

A server's tools are not in an offer by name, so one is known only once a run calls it: a tool whose name opens with
an offered server's, as the runtime names a server's tools, is that server's, and a server is called in a run that
called any of them. What a definition costs a model call is not in the journal at all, so nothing here counts it.

What the journal cannot say is counted apart, never as nothing: a run the runtime was not asked about (a task's, an
epic's plan, or one from before canopy asked), and one it could not answer for. Their calls are counted all the same.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import starmap
from typing import TYPE_CHECKING, Final, Literal

from canopy.core import agent_runs, db, records, spend, sql
from canopy.runtime import servers as runtime_servers
from canopy.runtime.report import SKILL_PREFIX

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Collection, Iterable, Mapping, Sequence
    from datetime import datetime


#: What a row is: an MCP server, or one tool, the runtime's own or a server's.
type Kind = Literal["server", "tool"]


@dataclass(frozen=True)
class Use:
    """One agent's use of one server or tool over a window: the runs offered it, those that called it, the calls."""

    agent: str
    #: The agent's runs the runtime said it offered it. Always 0 for a server's tool, which no offer names.
    offered: int = 0
    #: Of those, the runs offered only some of a server's tools, by the agent's rules. Always 0 for a tool.
    partial: int = 0
    #: Of the runs offered it, those that called it, whether or not the call failed.
    called: int = 0
    #: The agent's runs that called it, offered it on record or not.
    runs: int = 0
    #: Its calls in every run of the agent's; a server's are its tools' together.
    calls: int = 0
    #: Of those, the calls that failed.
    errors: int = 0
    #: The characters its calls returned into the runs' context.
    result_chars: int = 0

    @property
    def unoffered(self) -> int:
        """The agent's runs that called it with no offer of it on record."""
        return self.runs - self.called


@dataclass(frozen=True)
class Row:
    """One MCP server or one tool over a window: each agent's use of it."""

    kind: Kind
    #: A server's name as config has it, or a tool's as the runtime names it: a server's tool with the server's first.
    name: str
    #: Each agent that was offered it or called it, in `agent_runs.AGENTS` order, then any other by name.
    uses: Sequence[Use]
    #: The server a tool is of: None for the runtime's own, for a server itself, and for a tool no offer of the window
    #: places.
    server: str | None = None
    #: Whether an offer names it, so a run offered it and never calling it can be told: a server, or one of the
    #: runtime's own tools. A server's tool, and one no offer of the window names, is known by its calls alone.
    listed: bool = True

    @property
    def offered(self) -> int:
        """The runs offered it, of every agent."""
        return sum(u.offered for u in self.uses)

    @property
    def partial(self) -> int:
        """Of those, the runs offered only some of a server's tools."""
        return sum(u.partial for u in self.uses)

    @property
    def called(self) -> int:
        """Of the runs offered it, those that called it."""
        return sum(u.called for u in self.uses)

    @property
    def runs(self) -> int:
        """The runs that called it, offered it on record or not."""
        return sum(u.runs for u in self.uses)

    @property
    def calls(self) -> int:
        """Its calls, in every run."""
        return sum(u.calls for u in self.uses)

    @property
    def errors(self) -> int:
        """Of those, the calls that failed."""
        return sum(u.errors for u in self.uses)

    @property
    def result_chars(self) -> int:
        """The characters its calls returned."""
        return sum(u.result_chars for u in self.uses)

    @property
    def unused(self) -> bool:
        """Whether it was offered and never called, in any run of any agent's."""
        return self.offered > 0 and self.calls == 0


@dataclass(frozen=True)
class Agent:
    """One agent's runs over a window: how many the runtime answered for, what they were offered, and their calls."""

    agent: str
    #: Its runs that started in the window and have ended.
    runs: int
    #: Of those, the runs the runtime said what it offered.
    said: int
    #: The runs the runtime was asked about and could not answer for.
    unanswered: int
    #: How many MCP servers its runs were offered, by name.
    servers: int = 0
    #: How many of the runtime's own tools its runs were offered, by name.
    tools: int = 0
    #: Of those servers and tools, the ones none of its runs called.
    unused: int = 0
    #: Its tool calls, of every tool, in every run.
    calls: int = 0
    #: Of those, the calls that failed.
    errors: int = 0
    #: The characters its calls returned into its runs' context.
    result_chars: int = 0

    @property
    def unasked(self) -> int:
        """Its runs the runtime was never asked about: a task's, an epic's plan, or one from before canopy asked."""
        return self.runs - self.said - self.unanswered


@dataclass(frozen=True)
class Tools:
    """The servers and tools the runs that started in a window, `[since, until)`, were offered and called."""

    since: str
    until: str
    days: int
    #: A row per server a run was offered, then one per tool a run was offered or called, each by name.
    rows: Sequence[Row] = ()
    #: A row per agent that ran, in `agent_runs.AGENTS` order, then any other by name.
    agents: Sequence[Agent] = ()

    @property
    def servers(self) -> int:
        """How many MCP servers a run was offered."""
        return sum(1 for r in self.rows if r.kind == "server" and r.offered)

    @property
    def tools(self) -> int:
        """How many of the runtime's own tools a run was offered."""
        return sum(1 for r in self.rows if r.kind == "tool" and r.offered)

    @property
    def unused(self) -> int:
        """How many of those servers and tools no run called."""
        return sum(1 for r in self.rows if r.unused)

    @property
    def calls(self) -> int:
        """The tool calls, of every tool, in every run."""
        return sum(a.calls for a in self.agents)

    @property
    def errors(self) -> int:
        """Of those, the calls that failed."""
        return sum(a.errors for a in self.agents)

    @property
    def runs(self) -> int:
        """The window's runs, of every agent."""
        return sum(a.runs for a in self.agents)

    @property
    def unanswered(self) -> int:
        """Of those, the runs the runtime was asked about and could not answer for."""
        return sum(a.unanswered for a in self.agents)

    @property
    def unasked(self) -> int:
        """Of those, the runs the runtime was never asked about."""
        return sum(a.unasked for a in self.agents)


def report(conn: sqlite3.Connection, now: datetime, days: int) -> Tools:
    """The servers and tools the runs of the last `days` local days, today's so far included, were offered and called.

    Returns:
        The report; a window with no run in it has no row and no agent.
    """
    return between(conn, *spend.window(now, days))


def between(conn: sqlite3.Connection, start: datetime, end: datetime) -> Tools:
    """The servers and tools the runs that started from one local midnight, `start`, to another, `end`, were offered.

    Returns:
        The report, as `report` gives it for any such window: the one before a page's among them.
    """
    since = db.format_time(start)
    until = db.format_time(end)
    with db.read_snapshot(conn):
        ran = records.fetch_all(conn, _Ran, _ran(since, until))
        offers = records.fetch_all(conn, _Offered, _offered(since, until))
        calls = records.fetch_all(conn, _Called, _called(since, until))
        names = list(starmap(str, sql.execute(conn, _servers(since, until))))
        prefixes = {name: runtime_servers.tool_name(name, "") for name in names}
        own = {o.tool for o in offers}
        reached = {
            name: records.fetch_all(conn, _Reached, _reached(name, prefixes, own, since, until)) for name in names
        }
    placed = {c.tool: _server_of(c.tool, prefixes) for c in calls if c.tool not in own}
    rows = [
        *(_server_row(name, reached[name], [c for c in calls if placed.get(c.tool) == name]) for name in sorted(names)),
        *_tool_rows(offers, calls, placed),
    ]
    return Tools(
        since=since,
        until=until,
        days=spend.days_between(start, end),
        rows=rows,
        agents=_agents(ran, rows, calls),
    )


@dataclass(frozen=True)
class _Ran(records.View):
    """One agent's runs: how many, and how many the runtime answered for."""

    agent: str
    runs: int
    said: int
    unanswered: int


@dataclass(frozen=True)
class _Offered(records.View):
    """One agent's runs that were offered one of the runtime's own tools: how many, and how many called it."""

    agent: str
    tool: str
    offered: int
    called: int


@dataclass(frozen=True)
class _Called(records.View):
    """One agent's calls of one tool, in every kind of run: a load of any skill is a call of the skill tool."""

    agent: str
    tool: str
    runs: int
    calls: int
    errors: int
    result_chars: int
    #: Of the runs, those the runtime said it offered the tool, by name.
    offered: int


@dataclass(frozen=True)
class _Reached(records.View):
    """One agent's runs that were offered one MCP server or called a tool of it."""

    agent: str
    offered: int
    partial: int
    called: int
    runs: int


#: The runtime's tool that loads a skill, as an offer names it; its calls are recorded by the skill each loaded.
_SKILL: Final = SKILL_PREFIX.removesuffix(":")
#: A recorded call `t`'s tool as an offer would name it: a load of any skill is a call of the skill tool.
_NAMED: Final = sql.frag(
    "CASE WHEN substr(t.tool, 1, ?) = ? THEN ? ELSE t.tool END",
    len(SKILL_PREFIX),
    SKILL_PREFIX,
    _SKILL,
)


# Each agent's runs, and how many the runtime answered for.
def _ran(since: str, until: str) -> sql.Select:
    each = [
        sql.select(
            "coalesce(o.agent, {}) AS agent, o.run_id IS NOT NULL AND o.error IS NULL AS said, "
            "o.error IS NOT NULL AS unanswered",
            agent_runs.SHIPPED[table],
        )
        .from_("{} r LEFT JOIN run_offers o ON o.run_table = ? AND o.run_id = r.id", sql.name(table), table)
        .where(agent_runs.WINDOW, since, until)
        .where("{}", agent_runs.ran(table))
        for table in agent_runs.TABLES
    ]
    return (
        sql.select("agent, count(*) AS runs, SUM(said) AS said, SUM(unanswered) AS unanswered")
        .from_("({}) AS u", sql.union(*each, every=True))
        .group_by("agent")
    )


# Each agent's runs that were offered each of the runtime's own tools, and those of them that called it. The run table
# leads, through its `_spent` index on `started_at`, and the offer's tables are read by their keys' prefix: `CROSS
# JOIN` keeps SQLite from reordering them (`spend._tools_of`).
def _offered(since: str, until: str) -> sql.Select:
    each = [
        sql.select(
            "coalesce(o.agent, {}) AS agent, s.tool AS tool, "
            "EXISTS (SELECT 1 FROM run_tools t WHERE t.run_table = ? AND t.run_id = r.id AND {} = s.tool) AS called",
            agent_runs.SHIPPED[table],
            table,
            _NAMED,
        )
        .from_(
            "{} r CROSS JOIN run_offers o ON o.run_table = ? AND o.run_id = r.id "
            "CROSS JOIN run_offered_tools s ON s.run_table = ? AND s.run_id = r.id",
            sql.name(table),
            table,
            table,
        )
        .where(agent_runs.WINDOW, since, until)
        .where("{}", agent_runs.ran(table))
        .where("o.error IS NULL")
        for table in agent_runs.ASKED
    ]
    return (
        sql.select("agent, tool, count(*) AS offered, SUM(called) AS called")
        .from_("({}) AS u", sql.union(*each, every=True))
        .group_by("agent, tool")
    )


# Each agent's calls by tool, in every kind of run: a run the runtime was not asked about calls tools too. A run's
# loads of skills are summed into one row first, so a run that loaded two is one run that called the skill tool.
def _called(since: str, until: str) -> sql.Select:
    each = [
        sql.select(
            "coalesce(o.agent, {}) AS agent, {} AS named, SUM(t.calls) AS calls, SUM(t.errors) AS errors, "
            "SUM(t.result_chars) AS chars, "
            "EXISTS (SELECT 1 FROM run_offered_tools s "
            "WHERE s.run_table = ? AND s.run_id = r.id AND s.tool = {}) AS offered",
            agent_runs.SHIPPED[table],
            _NAMED,
            table,
            _NAMED,
        )
        .from_(
            "{} r CROSS JOIN run_tools t ON t.run_table = ? AND t.run_id = r.id "
            "LEFT JOIN run_offers o ON o.run_table = ? AND o.run_id = r.id",
            sql.name(table),
            table,
            table,
        )
        .where(agent_runs.WINDOW, since, until)
        .where("{}", agent_runs.ran(table))
        .group_by("r.id, named")
        for table in agent_runs.TABLES
    ]
    return (
        sql.select(
            "agent, named AS tool, count(*) AS runs, SUM(calls) AS calls, SUM(errors) AS errors, "
            "SUM(chars) AS result_chars, SUM(offered) AS offered",
        )
        .from_("({}) AS u", sql.union(*each, every=True))
        .group_by("agent, named")
    )


# Each MCP server a run of the window was offered, by name.
def _servers(since: str, until: str) -> sql.Fragment:
    each = [
        sql.select("s.server AS server")
        .from_(
            "{} r CROSS JOIN run_offered_servers s ON s.run_table = ? AND s.run_id = r.id",
            sql.name(table),
            table,
        )
        .where(agent_runs.WINDOW, since, until)
        .where("{}", agent_runs.ran(table))
        for table in agent_runs.ASKED
    ]
    return sql.union(*each)


# Each agent's runs that were offered the server `name` or called a tool of it, in every kind of run. A server's tools
# are not in an offer by name, so a run called the server when it called a tool named as the runtime names its tools.
def _reached(name: str, prefixes: Mapping[str, str], own: Collection[str], since: str, until: str) -> sql.Select:
    each = [
        sql.select(
            "coalesce(o.agent, {}) AS agent, s.reach AS reach, "
            "EXISTS (SELECT 1 FROM run_tools t WHERE t.run_table = ? AND t.run_id = r.id AND {}) AS called",
            agent_runs.SHIPPED[table],
            table,
            _of_server(name, prefixes, own),
        )
        .from_(
            "{} r LEFT JOIN run_offers o ON o.run_table = ? AND o.run_id = r.id "
            "LEFT JOIN run_offered_servers s ON s.run_table = ? AND s.run_id = r.id AND s.server = ?",
            sql.name(table),
            table,
            table,
            name,
        )
        .where(agent_runs.WINDOW, since, until)
        .where("{}", agent_runs.ran(table))
        for table in agent_runs.TABLES
    ]
    return (
        sql.select(
            "agent, count(reach) AS offered, coalesce(SUM(reach = 'some'), 0) AS partial, "
            "coalesce(SUM(reach IS NOT NULL AND called), 0) AS called, SUM(called) AS runs",
        )
        .from_("({}) AS u", sql.union(*each, every=True))
        .group_by("agent")
        .having("count(reach) > 0 OR SUM(called) > 0")
    )


# Whether a recorded call `t` is of a tool of the server `name`: its name opens with the server's as the runtime
# writes it, and with no longer one of another server's, whose tool it would be instead, and it is none of `own`, the
# runtime's own tools an offer names, as `_server_of` places none of those.
def _of_server(name: str, prefixes: Mapping[str, str], own: Collection[str]) -> sql.Fragment:
    own_prefix = prefixes[name]
    found = sql.frag("substr(t.tool, 1, ?) = ?", len(own_prefix), own_prefix)
    for longer in sorted(p for p in prefixes.values() if p != own_prefix and p.startswith(own_prefix)):
        found = sql.frag("{} AND substr(t.tool, 1, ?) <> ?", found, len(longer), longer)
    clashing = sorted(tool for tool in own if tool.startswith(own_prefix))
    return sql.frag("{} AND NOT {}", found, sql.in_("t.tool", clashing)) if clashing else found


# The server a called tool is of, by the longest of the servers' names its own opens with; None when it opens with
# none.
def _server_of(tool: str, prefixes: Mapping[str, str]) -> str | None:
    matching = [name for name, prefix in prefixes.items() if tool.startswith(prefix)]
    return max(matching, key=lambda name: len(prefixes[name]), default=None)


# One server's row: each agent's runs offered it and calling it, with its tools' calls, `calls`, summed.
def _server_row(name: str, reached: Iterable[_Reached], calls: Collection[_Called]) -> Row:
    uses = [
        Use(
            agent=r.agent,
            offered=r.offered,
            partial=r.partial,
            called=r.called,
            runs=r.runs,
            calls=sum(c.calls for c in calls if c.agent == r.agent),
            errors=sum(c.errors for c in calls if c.agent == r.agent),
            result_chars=sum(c.result_chars for c in calls if c.agent == r.agent),
        )
        for r in reached
    ]
    return Row(kind="server", name=name, uses=sorted(uses, key=lambda u: agent_runs.order(u.agent)))


def _tool_rows(offers: Iterable[_Offered], calls: Iterable[_Called], placed: Mapping[str, str | None]) -> list[Row]:
    """A row per tool a run was offered or called: the runtime's own, then each server's, known by its calls.

    `placed` is the server of each called tool no offer names, None for one that opens with no server's name.

    Returns:
        The rows, by name.
    """
    found: dict[tuple[str, str], Use] = {(o.tool, o.agent): Use(o.agent, offered=o.offered) for o in offers}
    for c in calls:
        found[c.tool, c.agent] = Use(
            agent=c.agent,
            offered=found.get((c.tool, c.agent), Use(c.agent)).offered,
            called=c.offered,
            runs=c.runs,
            calls=c.calls,
            errors=c.errors,
            result_chars=c.result_chars,
        )
    by_tool: dict[str, list[Use]] = {}
    for (tool, _), use in sorted(found.items(), key=lambda item: (item[0][0], agent_runs.order(item[0][1]))):
        by_tool.setdefault(tool, []).append(use)
    return [
        Row(kind="tool", name=tool, uses=uses, server=placed.get(tool), listed=tool not in placed)
        for tool, uses in by_tool.items()
    ]


# Each agent that ran, in the agents' order: the servers and tools its runs were offered, those none called, its calls.
def _agents(ran: Iterable[_Ran], rows: Sequence[Row], calls: Collection[_Called]) -> list[Agent]:
    found: list[Agent] = []
    for r in sorted(ran, key=lambda r: agent_runs.order(r.agent)):
        offered = [(row.kind, u) for row in rows for u in row.uses if u.agent == r.agent and u.offered]
        own = [c for c in calls if c.agent == r.agent]
        found.append(
            Agent(
                agent=r.agent,
                runs=r.runs,
                said=r.said,
                unanswered=r.unanswered,
                servers=sum(1 for kind, _ in offered if kind == "server"),
                tools=sum(1 for kind, _ in offered if kind == "tool"),
                unused=sum(1 for _, u in offered if u.calls == 0),
                calls=sum(c.calls for c in own),
                errors=sum(c.errors for c in own),
                result_chars=sum(c.result_chars for c in own),
            ),
        )
    return found
