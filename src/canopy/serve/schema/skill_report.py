"""The API's types for the Skills report (DESIGN §13): which skills the agents were offered, loaded, and paid for.

Read from what the runtime said it offered each agent run and from each run's calls of the skill tool: each skill over
the window, by the agent that was offered it or loaded it, with what its front matter added to the runs' model calls,
then each agent's runs and what their lists of skills cost a call. Every count of tokens is an estimate, characters
over four, and a cost is counted only over the runs the journal can say it for: where it can say it for none, the
figure is null, which is not known, never 0. Built on `schema.Model`, as every API type is (schema/__init__.py).
"""

from __future__ import annotations

from datetime import datetime

from canopy.serve.schema import Model


class SkillsUse(Model):
    """One agent's use of one skill over the window: the runs offered it, those that loaded it, and what it cost."""

    agent: str
    """The agent, as the run's command names it, or as canopy ships it for a run with no offer on record."""
    offered: int
    """The agent's runs the runtime said it offered the skill."""
    loaded: int
    """Of those, the runs that loaded it: a call of the skill tool for it that did not fail."""
    unoffered: int
    """The agent's runs that loaded it with no offer of it on record: a run the runtime was not asked about, or could
    not answer for."""
    loads: int
    """Its loads in every run of the agent's, offered it on record or not: the calls for it that did not fail."""
    failed: int
    """The calls for it that failed, such as one for a skill the agent is denied."""
    est_body_tokens: int
    """About how many tokens its loads returned into the runs' context, its text: an estimate, characters over 4."""
    front_matter_chars: int | None
    """Its front matter at the agent's newest offer that recorded it, in characters: its entry in the runtime's list of
    skills. None when no offer of the window did."""
    est_call_tokens: int | None
    """About how many tokens that adds to each model call of a run of the agent's offered it: an estimate, characters
    over 4. None where `front_matter_chars` is."""
    counted: int
    """The offered runs its front matter's cost is counted over: those whose offer recorded its entry's length
    and whose session, read, says how many model calls the run made."""
    calls: int
    """The model calls those runs made, each of which carried its front matter."""
    est_front_matter_tokens: int | None
    """About how many tokens its front matter added to those calls, its length at each run times the run's calls: an
    estimate, characters over 4. None when no run is counted."""


class SkillsSkill(Model):
    """One skill over the window: its figures over every agent, then each agent's own."""

    name: str
    """The skill's name, as the runtime lists it: untrusted text."""
    countable: bool
    """Whether a load of it is counted under its name: the runtime counts one under a name of its own rule alone, so
    a skill named otherwise reads as never loaded however often it is, its loads among the agents' `unnamed`."""
    unused: bool
    """Whether it was offered and no run of any agent loaded it, where a load of it would have been counted."""
    offered: int
    """The runs the runtime said it offered the skill, of every agent."""
    loaded: int
    """Of those, the runs that loaded it."""
    unoffered: int
    """The runs that loaded it with no offer of it on record."""
    loads: int
    """Its loads, in every run."""
    failed: int
    """The calls for it that failed."""
    est_body_tokens: int
    """About how many tokens its loads returned into the runs' context: an estimate, characters over 4."""
    front_matter_chars: int | None
    """Its front matter at the newest offer that recorded it, in characters: its entry in the runtime's list. None when
    no offer of the window did."""
    est_call_tokens: int | None
    """About how many tokens that adds to each model call of a run offered it: an estimate, characters over 4. None
    where `front_matter_chars` is."""
    counted: int
    """The offered runs its front matter's cost is counted over."""
    calls: int
    """The model calls those runs made."""
    est_front_matter_tokens: int | None
    """About how many tokens its front matter added to those calls: an estimate, characters over 4. None when no run
    is counted."""
    uses: list[SkillsUse]
    """Each agent that was offered it or loaded it, canopy's own first, in the order `agents` lists them."""


class SkillsAgent(Model):
    """One agent's runs over the window: how many the runtime answered for, and what their lists of skills cost."""

    agent: str
    """The agent, as the run's command names it, or as canopy ships it for a run with no offer on record."""
    runs: int
    """Its runs that started in the window and have ended."""
    unanswered: int
    """Of those, the runs the runtime was asked about and could not answer for."""
    unasked: int
    """Of those, the runs the runtime was never asked about: a task's, an epic's plan, or one from before canopy
    asked. With `unanswered`, the runs with no offer on record."""
    listed: int
    """The runs the runtime answered for that were offered a skill: what a front matter cost could be counted over."""
    unsized: int
    """Of those, the runs whose offer is from before canopy kept an entry's length."""
    unread: int
    """Of those, the runs whose lengths are on record and whose session, which says its model calls, names none:
    not read yet, gone, or never opened."""
    counted: int
    """The rest of them: the runs a front matter cost is counted over."""
    calls: int
    """The model calls those runs made."""
    skills: int | None
    """How many skills its runs were offered, by name; None when the runtime answered for none of them."""
    unused: int | None
    """Of those, the ones none of its runs loaded, where a load would have been counted; None where `skills` is."""
    loads: int
    """Its loads, of every skill canopy could name, in every run."""
    unnamed: int
    """Its loads canopy could not read the skill of: any of its skills may be among them."""
    est_call_tokens: int | None
    """About how many tokens the front matter of every skill offered added to one of its model calls, the counted
    runs' mean: an estimate, characters over 4. 0 for an agent offered no skill; None when it was offered some and no
    model call is counted."""
    est_front_matter_tokens: int | None
    """About how many tokens that added to the counted runs' model calls, all told: an estimate. 0 for an agent
    offered no skill; None when it was offered some and no run is counted."""


class SkillsPrevious(Model):
    """The window before a report's, as many days and ending where it starts: its headline figures alone."""

    since: datetime
    """When it starts: local midnight on its first day."""
    until: datetime
    """When it ends: where the report's window starts."""
    offered: int
    """How many skills a run was offered."""
    unused: int
    """How many of those no run loaded."""
    est_call_tokens: int | None
    """About how many tokens the skills' front matter added to one model call of a run offered a skill, the counted
    runs' mean: an estimate. None when none is counted."""


class SkillsReport(Model):
    """Which skills the window's agent runs were offered and loaded, and what each one's front matter cost."""

    days: int
    """How many local days the window holds, today's so far included."""
    since: datetime
    """When the window starts: local midnight on its first day."""
    until: datetime
    """When it ends: local midnight after today."""
    offered: int
    """How many skills a run was offered."""
    unused: int
    """How many of those no run loaded."""
    loads: int
    """The loads, of every skill canopy could name."""
    unnamed: int
    """The loads canopy could not read the skill of, which count under no skill."""
    runs: int
    """The agent runs that started in the window and have ended, of every agent."""
    unanswered: int
    """Of those, the runs the runtime was asked about and could not answer for."""
    unasked: int
    """Of those, the runs the runtime was never asked about. With `unanswered`, the runs with no offer on record."""
    listed: int
    """The runs the runtime answered for that were offered a skill: what a front matter cost could be counted over.
    A run offered none, as the overseer's are, carries none and is not among them."""
    unsized: int
    """Of those, the runs whose offer is from before canopy kept an entry's length."""
    unread: int
    """Of those, the runs whose lengths are on record and whose session names no model call."""
    counted: int
    """The rest of them: the runs a front matter cost is counted over."""
    est_front_matter_tokens: int | None
    """About how many tokens the skills' front matter added to the counted runs' model calls: an estimate, characters
    over 4. None when no run offered a skill is counted."""
    est_call_tokens: int | None
    """About how many tokens it added to one model call of a run offered a skill, the counted runs' mean, which holds
    while only some runs are counted: an estimate, characters over 4. None when no model call is counted."""
    skills: list[SkillsSkill]
    """Each skill a run was offered or loaded, by name."""
    agents: list[SkillsAgent]
    """Each agent that ran, canopy's own first, then any other by name."""
    previous: SkillsPrevious
    """The window before this one, as many days, for a page to say how this one compares."""
