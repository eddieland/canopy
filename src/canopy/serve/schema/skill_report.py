"""The API's types for the Skills report (DESIGN §13): which skills the agents were offered, loaded, and paid for.

Read from what the runtime said it offered each agent run and from each run's calls of the skill tool: each skill over
the window, by the agent that was offered it or loaded it, with what its front matter added to the runs' model calls,
then each agent's runs and what their lists of skills cost a call. Every count of tokens is an estimate, characters
over four, and a cost is counted only over the runs the journal can say it for. Built on `schema.Model`, as every API
type is (schema/__init__.py).
"""

from __future__ import annotations

from datetime import datetime

from canopy.serve.schema import Model


class SkillsUse(Model):
    """One agent's use of one skill over the window: the runs offered it, those that loaded it, and what it cost."""

    agent: str
    """The agent, as the run's command names it, or as canopy ships it for a run the runtime was not asked about."""
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
    est_result_tokens: int
    """About how many tokens its loads returned into the runs' context, its text: an estimate, characters over 4."""
    front_matter_chars: int | None
    """Its front matter at the agent's newest offer that recorded it, in characters: its name and its description.
    None when no offer of the window did."""
    counted: int
    """The offered runs its front matter's cost is counted over: those whose offer recorded its description's length
    and whose session, read, says how many model calls the run made."""
    calls: int
    """The model calls those runs made, each of which carried its front matter."""
    est_sent_tokens: int
    """About how many tokens its front matter added to those calls, its length at each run times the run's calls: an
    estimate, characters over 4."""


class SkillsSkill(Model):
    """One skill over the window: its figures over every agent, then each agent's own."""

    name: str
    """The skill's name, as the runtime lists it: untrusted text."""
    countable: bool
    """Whether a load of it is counted under its name: the runtime counts one under a name of its own rule alone, so
    a skill named otherwise reads as never loaded however often it is, its loads among the report's `unnamed`."""
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
    est_result_tokens: int
    """About how many tokens its loads returned into the runs' context: an estimate, characters over 4."""
    front_matter_chars: int | None
    """Its front matter at the newest offer that recorded it, in characters: its name and its description. None when
    no offer of the window did."""
    est_front_matter_tokens: int | None
    """About how many tokens that adds to each model call of a run offered it: an estimate, characters over 4. None
    where `front_matter_chars` is."""
    counted: int
    """The offered runs its front matter's cost is counted over."""
    calls: int
    """The model calls those runs made."""
    est_sent_tokens: int
    """About how many tokens its front matter added to those calls: an estimate, characters over 4."""
    uses: list[SkillsUse]
    """Each agent that was offered it or loaded it, canopy's own first, in the order `agents` lists them."""


class SkillsAgent(Model):
    """One agent's runs over the window: how many the runtime answered for, and what their lists of skills cost."""

    agent: str
    """The agent, as the run's command names it, or as canopy ships it for a run the runtime was not asked about."""
    runs: int
    """Its runs that started in the window and have ended."""
    said: int
    """Of those, the runs the runtime said what it offered."""
    unanswered: int
    """The runs the runtime was asked about and could not answer for."""
    unasked: int
    """The runs the runtime was never asked about: a task's, an epic's plan, or one from before canopy asked."""
    counted: int
    """The runs a front matter cost is counted over: answered for, every offered skill's description length recorded,
    and their session read."""
    calls: int
    """The model calls those runs made."""
    skills: int
    """How many skills its runs were offered, by name."""
    unused: int
    """Of those, the ones none of its runs loaded, where a load would have been counted."""
    est_call_tokens: int | None
    """About how many tokens the front matter of every skill offered added to one of its model calls, the counted
    runs' mean: an estimate, characters over 4. None when no model call is counted."""
    est_sent_tokens: int
    """About how many tokens that added to the counted runs' model calls, all told: an estimate, characters over 4."""


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
    loads: int
    """The loads, of every skill canopy could name."""
    counted: int
    """The runs a front matter cost is counted over."""
    est_sent_tokens: int
    """About how many tokens the skills' front matter added to those runs' model calls: an estimate."""


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
    said: int
    """Of those, the runs the runtime said what it offered: what an offer is counted over."""
    counted: int
    """Of those, the runs a front matter cost is counted over."""
    est_sent_tokens: int
    """About how many tokens the skills' front matter added to the counted runs' model calls: an estimate, characters
    over 4."""
    skills: list[SkillsSkill]
    """Each skill a run was offered or loaded, by name."""
    agents: list[SkillsAgent]
    """Each agent that ran, canopy's own first, then any other by name."""
    previous: SkillsPrevious
    """The window before this one, as many days, for a page to say how this one compares."""
