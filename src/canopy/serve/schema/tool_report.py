"""The API's types for the Tools report (DESIGN §13): which MCP servers and tools the agents were offered and called.

Read from what the runtime said it offered each agent run, an MCP server by its name and the runtime's own tools each
by theirs, and from each run's calls by tool: each server and tool over the window, by the agent that was offered it
or called it, then each agent's runs. A server's tools are in no offer by name, so one is listed once a run calls it,
with no count of the runs offered it. Every count of tokens is an estimate, characters over four. What a definition
adds to a model call is not recorded, so no figure here is a cost of being offered. Built on `schema.Model`, as every
API type is (schema/__init__.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from canopy.serve.schema import Model


class ToolsUse(Model):
    """One agent's use of one server or tool over the window: the runs offered it, those that called it, the calls."""

    agent: str
    """The agent, as the run's command names it, or as canopy ships it for a run with no offer on record."""
    offered: int
    """The agent's runs the runtime said it offered it. Always 0 where the row's `listed` is false."""
    partial: int
    """Of those, the runs offered only some of a server's tools, by the agent's rules. Always 0 for a tool."""
    called: int
    """Of the runs offered it, those that called it, whether or not the call failed."""
    unoffered: int
    """The agent's runs that called it with no offer of it on record: a run the runtime was not asked about or could
    not answer for, or, for a server's tool, any run."""
    calls: int
    """Its calls in every run of the agent's, offered it on record or not; a server's are its tools' together."""
    errors: int
    """Of those, the calls that failed."""
    est_result_tokens: int
    """About how many tokens its calls returned into the runs' context: an estimate, characters over 4."""


class ToolsRow(Model):
    """One MCP server or one tool over the window: its figures over every agent, then each agent's own."""

    kind: Literal["server", "tool"]
    """An MCP server, or one tool: the runtime's own or a server's."""
    name: str
    """A server's name as config has it, or a tool's as the runtime names it, a server's tool with the server's name
    first: untrusted text."""
    server: str | None
    """The server a tool is of, by its name; None for the runtime's own, for a server itself, and for a tool no offer
    of the window places."""
    listed: bool
    """Whether an offer names it, so a run offered it and never calling it can be told: a server, or one of the
    runtime's own tools. A server's tool, and one no offer of the window names, is known by its calls alone."""
    unused: bool
    """Whether it was offered and no run of any agent called it."""
    offered: int
    """The runs the runtime said it offered it, of every agent."""
    partial: int
    """Of those, the runs offered only some of a server's tools."""
    called: int
    """Of the runs offered it, those that called it."""
    unoffered: int
    """The runs that called it with no offer of it on record."""
    calls: int
    """Its calls, in every run."""
    errors: int
    """Of those, the calls that failed."""
    est_result_tokens: int
    """About how many tokens its calls returned into the runs' context: an estimate, characters over 4."""
    uses: list[ToolsUse]
    """Each agent that was offered it or called it, canopy's own first, in the order `agents` lists them."""


class ToolsAgent(Model):
    """One agent's runs over the window: how many the runtime answered for, what they were offered, and their calls."""

    agent: str
    """The agent, as the run's command names it, or as canopy ships it for a run with no offer on record."""
    runs: int
    """Its runs that started in the window and have ended."""
    unanswered: int
    """Of those, the runs the runtime was asked about and could not answer for."""
    unasked: int
    """Of those, the runs the runtime was never asked about: a task's, an epic's plan, or one from before canopy
    asked. With `unanswered`, the runs with no offer on record."""
    servers: int | None
    """How many MCP servers its runs were offered, by name; None when the runtime answered for none of them."""
    tools: int | None
    """How many of the runtime's own tools its runs were offered, by name; None where `servers` is."""
    unused: int | None
    """Of those servers and tools, the ones none of its runs called; None where `servers` is."""
    calls: int
    """Its tool calls, of every tool, in every run."""
    errors: int
    """Of those, the calls that failed."""
    est_result_tokens: int
    """About how many tokens its calls returned into its runs' context: an estimate, characters over 4."""


class ToolsPrevious(Model):
    """The window before a report's, as many days and ending where it starts: its headline figures alone."""

    since: datetime
    """When it starts: local midnight on its first day."""
    until: datetime
    """When it ends: where the report's window starts."""
    servers: int
    """How many MCP servers a run was offered."""
    tools: int
    """How many of the runtime's own tools a run was offered."""
    unused: int
    """How many of those servers and tools no run called."""
    calls: int
    """The tool calls, of every tool, in every run."""
    errors: int
    """Of those, the calls that failed."""


class ToolsReport(Model):
    """Which MCP servers and tools the window's agent runs were offered and called, and what the calls returned."""

    days: int
    """How many local days the window holds, today's so far included."""
    since: datetime
    """When the window starts: local midnight on its first day."""
    until: datetime
    """When it ends: local midnight after today."""
    servers: int
    """How many MCP servers a run was offered."""
    tools: int
    """How many of the runtime's own tools a run was offered."""
    unused: int
    """How many of those servers and tools no run called."""
    calls: int
    """The tool calls, of every tool, in every run."""
    errors: int
    """Of those, the calls that failed."""
    runs: int
    """The agent runs that started in the window and have ended, of every agent."""
    unanswered: int
    """Of those, the runs the runtime was asked about and could not answer for."""
    unasked: int
    """Of those, the runs the runtime was never asked about. With `unanswered`, the runs with no offer on record."""
    rows: list[ToolsRow]
    """Each server a run was offered, by name, then each tool a run was offered or called, by name."""
    agents: list[ToolsAgent]
    """Each agent that ran, canopy's own first, then any other by name."""
    previous: ToolsPrevious
    """The window before this one, as many days, for a page to say how this one compares."""
