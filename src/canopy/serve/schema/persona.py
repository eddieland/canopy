"""The API's types for personas (DESIGN §31): the persona each agent of a ticket writes in, and the operator's choice.

Also every persona a run could get, and the one a run wrote in. Built on `schema.Model`, as every API type is
(schema/__init__.py).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from canopy.serve.schema import Model

type PersonaAgent = Annotated[
    Literal["worker", "planner", "reviewer"],
    Field(description="One of a ticket's agents a persona reaches (DESIGN §31): `worker` for implement and resume."),
]


class AgentPersona(Model):
    """The persona one of a ticket's agents writes in at its next run, and where that choice comes from (DESIGN §31)."""

    agent: PersonaAgent
    """The agent: `worker` for its implement and resume runs, `planner`, or `reviewer`."""
    persona: str
    """The persona's name."""
    source: Literal["ticket", "config", "default"]
    """Where it comes from: the ticket's override, `[personas]` in config, or canopy's own default."""
    error: str | None = None
    """Why its next run would be refused rather than run in it, such as a file gone since; None when it would run."""
    once: str | None = None
    """The persona the operator chose for its next run alone, in place of `persona`; None when they chose none."""
    several: list[str] = []
    """For the reviewer: each persona the ticket's PRs are reviewed in, one review each, from `[personas] reviewers`."""


class PersonaRequest(Model):
    """A choice of persona for one of a ticket's agents, as `canopy persona KEY NAME [--agent AGENT]` makes it."""

    agent: PersonaAgent = "worker"
    """The agent to choose for."""
    persona: Annotated[str | None, Field(max_length=40)] = None
    """The persona's name, one `persona_names` holds; None clears the override, as `--clear` does."""


class PersonaChoice(Model):
    """A persona a run could get, as `canopy personas` lists it (DESIGN §31): what the operator may choose from."""

    name: str
    """Its name, which a choice of it names."""
    yours: bool
    """Whether its file is the operator's, from `paths.personas`; False for one canopy ships."""
    defaults: list[PersonaAgent] = []
    """The agents whose `[personas]` names it, `reviewer` among them when `[personas] reviewers` does."""
    error: str | None = None
    """Why a run would refuse it, or None when it would render."""
    description: str | None = None
    """What it is: its front matter's `description`, else its text's opening sentence; None for one a run would
    refuse."""


class PersonaList(Model):
    """Every persona a run could get, and the one a review request that chooses none is reviewed in (DESIGN §31)."""

    personas: list[PersonaChoice] = []
    """Each persona once, by name, the operator's in place of canopy's of the same name."""
    reviewer: str
    """`[personas] reviewer`'s: the persona of a review request's review when the request chooses none."""


class RunPersona(Model):
    """The persona a run wrote in (DESIGN §31), and the instructions it read."""

    name: str
    """The persona's name."""
    digest: str
    """The sha256 of its text as the run's prompt carried it, in hex."""
    text: str | None = None
    """Its instructions as the run read them; none when canopy cannot tell what they were: `problem` says why."""
    problem: str | None = None
    """Why there is no text: the run is from before canopy kept texts, and its file is gone or edited since."""
