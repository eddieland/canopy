"""Each agent's model, as the operator chooses it in `[runtime.models]` (DESIGN §13, Each agent's model).

The operator alone chooses: the key is private (TRUST_MODEL T7), and no agent, dispatch, or ticket text sets one.
canopy writes each agent's model into its definition (`canopy.core.definitions`), so a template that passes one of its
own is a config error, and what a run records is what it runs on. An agent with none set runs on the runtime's
default, as before.

Before a worker run on a chosen model starts, the model is looked up in the list the runtime would look it up in,
read in the workspace root, since a repository's own runtime config could change the list. A model the list lacks
refuses the run as `model_missing`, and a list that cannot be read as `model_list_failed`: never the runtime's default
instead, since a canary's run on a model nobody chose would read as the canary's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.runtime import agents, invocation
from canopy.runtime import models as runtime_models
from canopy.runtime.definitions import MODEL_RE

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from canopy.infra import procs

#: Each key of `[runtime.models]`, the role it chooses a model for, and the agents that role is, by the names the
#: runtime runs them by: a worker is the public or the private one, and a task's run is the private one.
AGENTS: Mapping[str, tuple[str, ...]] = {
    "worker": (agents.WORKER, agents.PRIVATE_WORKER),
    "planner": (agents.PLANNER,),
    "reviewer": (agents.REVIEWER,),
    "overseer": (agents.OVERSEER,),
    "chore": (agents.CHORE,),
}
#: The guard and attention reason of a run whose model the runtime does not list.
MISSING = "model_missing"
#: The guard and attention reason of a run whose model could not be looked up, the list not read.
LIST_FAILED = "model_list_failed"


class ModelError(Exception):
    """A run's model cannot be used: `guard` is `MISSING` or `LIST_FAILED`, and the message says why, naming it."""

    def __init__(self, guard: str, reason: str) -> None:
        """Name the guard and say why."""
        super().__init__(reason)
        self.guard = guard
        self.reason = reason


def by_agent(models: Mapping[str, str]) -> dict[str, str]:
    """Return `runtime.models` by the name of each agent it chooses for, for the runtime to write into its definitions.

    Returns:
        Each agent with a model, by its name: both workers for `worker`.
    """
    return {agent: model for role, model in models.items() for agent in AGENTS.get(role, ())}


def of_template(models: Mapping[str, str], template: str) -> str | None:
    """Return the model a run of `template` asks for: the one config chooses for the agent the template runs.

    Returns:
        The model, or None when config chooses none for it, or the template runs no agent of canopy's, whose model is
        the runtime's choice.
    """
    agent = invocation.agent_of(template)
    return by_agent(models).get(agent) if agent is not None else None


def check(runner: procs.Runner, root: Path, model: str) -> None:
    """Refuse `model` unless the runtime, started in the workspace root `root`, lists it.

    Raises:
        ModelError: (`MISSING`) the runtime does not list it, or (`LIST_FAILED`) its list could not be read.
    """
    found = runtime_models.listed(runner, cwd=root)
    if found.error is not None:
        raise ModelError(
            LIST_FAILED,
            f"could not look up the model {model} chosen in runtime.models: {found.error}. Nothing ran on another "
            "model; the work resumes once the list can be read",
        )
    if model not in found.models:
        raise ModelError(
            MISSING,
            f"{invocation.NAME} does not list the model {model} chosen in runtime.models, so a run on it would fail "
            "before its first call; nothing ran on another model. Choose a model it lists, or set up its provider",
        )


def check_role(role: str) -> str:
    """Return `role` if `runtime.models` may name it.

    Raises:
        ValueError: it names no agent of canopy's.
    """
    if role in AGENTS:
        return role
    raise ValueError(f"{role!r} is not an agent runtime.models chooses for; name {', '.join(AGENTS)}")


def check_model(model: str) -> str:
    """Return `model` if canopy renders it into a definition: `provider/model`, as the runtime names one.

    Raises:
        ValueError: it is not a model as the runtime names one.
    """
    if not MODEL_RE.fullmatch(model):
        raise ValueError(f"{model!r} must be a model as {invocation.NAME} names it, provider/model")
    return model
