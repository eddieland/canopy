"""Each agent's model, as the operator chooses it in `[runtime.models]` and a chore's `model` (DESIGN §13, §19).

The operator alone chooses: the keys are private (TRUST_MODEL T7), and no agent, dispatch, or ticket text sets one.
canopy writes each agent's model into its definition (`canopy.core.definitions`), so a template that passes one of its
own is a config error, and what a run records is what it runs on. An agent with none set runs on the runtime's
default, as before.

A model is spelled `provider/model`, or `provider/model@variant` to run it at one of its variants, such as a reasoning
effort, as canopy names a model a session ran at a variant. A model's own id may hold an `@` (a dated id,
`claude-x@20250101`), so the variant is what follows the last `@` only when it starts with a letter, as every variant
the runtime names does: `vendor/claude-x@20250101@high` is that model at `high`.

A chore with a `model` of its own runs a copy of the chore's agent made for it, `canopy-chore-<name>`, with that
model, since one definition holds one model; every other chore runs the chore's agent, on `runtime.models.chore`.

Before a worker run on a chosen model starts, the model is looked up in the list the runtime would look it up in,
read in the workspace root, since a repository's own runtime config could change the list; with a variant, the
model's variants too, since a runtime may drop a variant the model lacks without a word, or fail the run on it. A
model or variant the list lacks refuses the run as `model_missing`, and a list that cannot be read as
`model_list_failed`: never the runtime's default instead, since a canary's run on a model nobody chose would read as
the canary's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from canopy.runtime import agents, invocation
from canopy.runtime import models as runtime_models
from canopy.runtime.agents import Model
from canopy.runtime.definitions import MODEL_RE, VARIANT_RE

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from canopy.core.config import Chore, Config
    from canopy.infra import procs
    from canopy.runtime.implementation import Version

#: A key of `[runtime.models]`: the role of canopy's it chooses a model for.
type Role = Literal["worker", "planner", "reviewer", "overseer", "chore"]
#: Each key of `[runtime.models]`, the role it chooses a model for, and the agents that role is, by the names the
#: runtime runs them by: a worker is the public or the private one, and a task's run is the private one.
AGENTS: Mapping[Role, tuple[str, ...]] = {
    "worker": (agents.WORKER, agents.PRIVATE_WORKER),
    "planner": (agents.PLANNER,),
    "reviewer": (agents.REVIEWER,),
    "overseer": (agents.OVERSEER,),
    "chore": (agents.CHORE,),
}
#: The guard and attention reason of a run whose model, or the variant of it, the runtime does not list.
MISSING = "model_missing"
#: The guard and attention reason of a run whose model could not be looked up, the list not read.
LIST_FAILED = "model_list_failed"
#: Where config's choice of an agent's model comes from: `[runtime.models]` (`config`), a chore's own `model`
#: (`chore`), the definition of an agent of the operator's own that a chore runs, which canopy does not write
#: (`agent`), or nothing, the runtime's default (`default`).
type Source = Literal["config", "chore", "agent", "default"]
# The most variants a refusal names of those the model lists.
_MAX_NAMED = 8


@dataclass(frozen=True)
class Chosen:
    """The model config chooses for one of canopy's agents, or for one chore, and where that choice comes from."""

    #: The model and its variant; None when config chooses none, for the runtime's default or the agent's own.
    model: Model | None
    source: Source
    #: The agent a chore runs when it is one of the operator's own (`agent`); None otherwise, or when its command
    #: names none.
    agent: str | None = None


class ModelError(Exception):
    """A run's model cannot be used: `guard` is `MISSING` or `LIST_FAILED`, and the message says why, naming it."""

    def __init__(self, guard: str, reason: str) -> None:
        """Name the guard and say why."""
        super().__init__(reason)
        self.guard = guard
        self.reason = reason


def parse(value: str) -> Model:
    """Return `value`, a model as config spells it, as the model and its variant.

    Returns:
        The model, with the variant after its last `@` when that starts with a letter, else with none.
    """
    head, at, tail = value.rpartition("@")
    if at and head and VARIANT_RE.fullmatch(tail):
        return Model(head, tail)
    return Model(value)


def by_agent(models: Mapping[str, str], chores: Mapping[str, str] | None = None) -> dict[str, Model]:
    """Return `runtime.models` by the name of each agent it chooses for, for the runtime to write into its definitions.

    `chores` is each chore's own `model`, by the chore's name, which its own copy of the chore's agent takes.

    Returns:
        Each agent with a model, by its name: both workers for `worker`, and each chore's copy for its chore.
    """
    found = {agent: parse(models[role]) for role, names in AGENTS.items() if role in models for agent in names}
    found.update({agents.chore_agent(chore): parse(model) for chore, model in (chores or {}).items()})
    return found


def of_template(models: Mapping[str, str], template: str) -> Model | None:
    """Return the model a run of `template` asks for: the one config chooses for the agent the template runs.

    Returns:
        The model, or None when config chooses none for it, or the template runs no agent of canopy's, whose model is
        the runtime's choice.
    """
    agent = invocation.agent_of(template)
    return by_agent(models).get(agent) if agent is not None else None


def chore_template(template: str, chore: str, model: str | None) -> str:
    """Return the template chore `chore` runs: `template`, on the chore's own copy of its agent when it has a `model`.

    Config holds a chore with a model to a template that runs the chore's agent, so the copy is that agent but for its
    model.

    Returns:
        `template`, running `canopy-chore-<chore>` when `model` is set, else as it is.
    """
    return template if model is None else invocation.with_agent(template, agents.chore_agent(chore))


def chores(config: Config) -> dict[str, str]:
    """Return each chore's own `model`, by the chore's name, for the chores that have one.

    Returns:
        The models, as config spells them.
    """
    return {name: chore.model for name, chore in config.chores.items() if chore.model is not None}


def configured(config: Config) -> dict[Role, Chosen]:
    """Return the model `[runtime.models]` chooses for each role it may name, as a run takes it but a ticket's override.

    Returns:
        Each role in `AGENTS`' order, with its model and `config`, or with none and `default`.
    """
    return {role: _chosen(config.runtime.models.get(role)) for role in AGENTS}


def of_chore(config: Config, chore: Chore) -> Chosen:
    """Return the model `chore` runs on as `config` chooses it.

    Its own `model` on its own copy of the chore's agent, else `runtime.models.chore` on that agent. A chore whose
    command, its `cmd` or `runtime.chore_cmd`, runs an agent of the operator's own takes neither, as config refuses a
    `model` for it: that agent's definition chooses, which canopy does not write.

    Returns:
        The model and where it comes from, naming the operator's agent for `agent`.
    """
    agent = invocation.agent_of(chore.cmd if chore.cmd is not None else config.runtime.chore_cmd)
    if agent != agents.CHORE:
        return Chosen(None, "agent", agent)
    if chore.model is not None:
        return Chosen(parse(chore.model), "chore")
    return _chosen(config.runtime.models.get("chore"))


def _chosen(value: str | None) -> Chosen:
    return Chosen(parse(value), "config") if value is not None else Chosen(None, "default")


def of_run(config: Config, template: str, model: str | None) -> dict[str, Model]:
    """Return each agent's model by its name for a run of `template` recorded as asking for `model`.

    That is `config`'s, but for the agent the template runs, which gets `model`, or none for None: a run renders the
    model it recorded, which a ticket's override may have chosen in place of config's, so what is recorded is what runs
    (DESIGN §13).

    Returns:
        Each agent with a model, by its name, for the runtime to write into the run's definitions.
    """
    found = by_agent(config.runtime.models, chores(config))
    agent = invocation.agent_of(template)
    if agent is None:
        return found
    found.pop(agent, None)
    return found | ({agent: parse(model)} if model is not None else {})


def check(
    runner: procs.Runner,
    root: Path,
    model: Model,
    *,
    version: Version,
    chosen: str = "in runtime.models",
) -> None:
    """Refuse `model` unless the runtime, started in the workspace root `root`, lists it, and its variant if it has one.

    The runtime is the one `version` runs.

    `chosen` says where the model was chosen, to name it in a refusal: in `runtime.models`, or by a ticket's override.

    Raises:
        ModelError: (`MISSING`) the runtime does not list the model or its variant, or (`LIST_FAILED`) its list could
            not be read.
    """
    found = runtime_models.listed(runner, version=version, cwd=root, variants=model.variant is not None)
    if found.error is not None:
        raise ModelError(
            LIST_FAILED,
            f"could not look up the model {model.name} chosen {chosen}: {found.error}. Nothing ran on another "
            "model; the work resumes once the list can be read",
        )
    if model.id not in found.models:
        raise ModelError(
            MISSING,
            f"{invocation.NAME} does not list the model {model.id} chosen {chosen}, so a run on it would fail "
            "before its first call; nothing ran on another model. Choose a model it lists, or set up its provider",
        )
    if model.variant is not None and model.variant not in found.variants.get(model.id, ()):
        listed = sorted(found.variants.get(model.id, ()))
        some = ", ".join(listed[:_MAX_NAMED]) + (", ..." if len(listed) > _MAX_NAMED else "")
        has = f"it lists {some}" if listed else "it lists none for it"
        raise ModelError(
            MISSING,
            f"{invocation.NAME} lists the model {model.id} chosen {chosen} but not its variant "
            f"{model.variant} ({has}); nothing ran. Choose a variant it lists",
        )


def check_role(role: str) -> str:
    """Return `role` if `runtime.models` may name it.

    Raises:
        ValueError: it names no agent of canopy's.
    """
    if role in AGENTS:
        return role
    raise ValueError(f"{role!r} is not an agent runtime.models chooses for; name {', '.join(AGENTS)}")


def check_model(value: str) -> str:
    """Return `value` if canopy renders it into a definition: `provider/model`, then `@variant` if it has one.

    Raises:
        ValueError: it is not a model as the runtime names one.
    """
    if not MODEL_RE.fullmatch(parse(value).id):
        raise ValueError(
            f"{value!r} must be a model as {invocation.NAME} names it, provider/model, or provider/model@variant",
        )
    return value
