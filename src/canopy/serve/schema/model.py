"""The API's types for each agent's model (DESIGN §13): the model each of a ticket's agents runs on, and its override.

Also the models the runtime lists, which the operator chooses from. Built on `schema.Model`, as every API type is
(schema/__init__.py).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from canopy.serve.schema import Model

type ModelAgent = Annotated[
    Literal["worker", "planner", "reviewer"],
    Field(description="One of a ticket's agents (DESIGN §13): `worker` for its implement and resume runs."),
]


class AgentModel(Model):
    """The model one of a ticket's agents runs on at its next run, and where that choice comes from (DESIGN §13)."""

    agent: ModelAgent
    """The agent: `worker` for its implement and resume runs, `planner`, or `reviewer`."""
    model: str | None = None
    """The model, as `provider/model`; None for the runtime's default, when neither the ticket nor config sets one."""
    source: Literal["ticket", "config", "default"]
    """Where it comes from: the ticket's override, `[runtime.models]` in config, or neither, the runtime's default."""
    variant: str | None = None
    """The variant `model` runs at, after its last `@`, as `high` in config's `provider/model@high`; None for none.

    The runtime's list names the model without it, and a ticket's override names none, so a model with one is not a
    choice the page can make: it chooses the model alone.
    """
    last_served: str | None = None
    """The model that served the agent's latest run for the ticket whose session canopy has read, as `provider/model`,
    the most costly when it called several; None when none of its runs has been read.

    What served may differ from `model`: a run before the choice changed, or the runtime's default, which `model` cannot
    name.
    """


class ModelRequest(Model):
    """A choice of model for one of a ticket's agents, as `canopy model KEY MODEL [--agent AGENT]` makes it."""

    agent: ModelAgent = "worker"
    """The agent to choose for."""
    model: Annotated[str | None, Field(max_length=200)] = None
    """The model, as `provider/model`, one `GET /models` lists; None clears the override, as `--clear` does."""


class ModelList(Model):
    """The models the runtime lists to run an agent on, as `canopy models` prints them: what the operator may choose."""

    models: list[str] = []
    """Each model, as `provider/model`, in order; none when the list could not be read."""
    error: str | None = None
    """Why the list could not be read, in canopy's words; None when it was."""
