"""The API's types for each agent's model (DESIGN §13): the model each of a ticket's agents runs on, and its override.

Also the models the runtime lists, which the operator chooses from, and the model config chooses for each agent and
each chore, which the settings page shows. Built on `schema.Model`, as every API type is
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


type ConfigRole = Annotated[
    # Spelled out rather than `agent_models.Role`, which the schema would name as a type of its own.
    Literal["worker", "planner", "reviewer", "overseer", "chore"],
    Field(
        description="A key of `[runtime.models]` (DESIGN §13): `worker` for both workers and a task's runs, and "
        "`chore` for every chore without a `model` of its own.",
    ),
]


class ConfiguredModel(Model):
    """The model `[runtime.models]` chooses for one of canopy's agents, as its runs take it but a ticket's override."""

    agent: ConfigRole
    """The key of `[runtime.models]`, the agent it chooses for."""
    model: str | None = None
    """The model, as `provider/model`, without its variant; None when nothing sets one: the runtime's default."""
    variant: str | None = None
    """The variant it runs at, such as a reasoning effort; None for the model's default."""
    source: Literal["config", "default"]
    """Where it comes from: `[runtime.models]`, or nothing, the runtime's default."""


class ChoreModel(Model):
    """The model one chore runs on as config chooses it (DESIGN §13, §19), and where that choice comes from."""

    chore: str
    """The chore's name, its `[chores.<name>]` table."""
    model: str | None = None
    """The model, as `provider/model`, without its variant; None when config chooses none."""
    variant: str | None = None
    """The variant it runs at; None for the model's default."""
    source: Literal["chore", "config", "agent", "default"]
    """Where it comes from: the chore's own `model`, `runtime.models.chore`, the definition of an agent of the
    operator's own that its command runs, which canopy does not write and config gives no model, or nothing, the
    runtime's default."""
    agent: str | None = None
    """The agent of the operator's own its command runs, for `agent`; None otherwise, or when the command names none."""


class ConfigModels(Model):
    """The model config chooses for each of canopy's agents and each chore, and the files that set them (DESIGN §13).

    As the loop runs on it now: an edit to a file shows here once the loop reads its config again.
    """

    agents: list[ConfiguredModel]
    """Each key of `[runtime.models]`: `worker`, `planner`, `reviewer`, `overseer`, then `chore`."""
    chores: list[ChoreModel]
    """Each chore the config defines for this workspace, by name."""
    models_file: str | None
    """The file `[runtime.models]` comes from, as the files say now; None when none sets it, or one cannot be read."""
    chores_file: str | None
    """The file the `[chores.*]` tables come from, all from one, as the files say now; None when no file sets one, or
    one cannot be read."""
    user_file: str
    """The user config file, which serves every workspace."""
    private_file: str
    """The workspace's private file (M49), which serves this workspace alone."""
