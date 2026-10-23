"""The API's types for each agent's model (DESIGN §13): the model each of a ticket's agents runs on, and its override.

Also the models the runtime lists, which the operator chooses from. Built on `schema.Model`, as every API type is
(schema.py).
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
