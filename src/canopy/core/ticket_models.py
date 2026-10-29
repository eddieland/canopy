"""The model each of a ticket's agents runs on (DESIGN §13, Each agent's model), and the operator's override of it.

An agent's next run for a ticket runs on the ticket's override for that agent, else the agent's model in
`[runtime.models]`, else the runtime's default. The override is the operator's alone (TRUST_MODEL T1): `choose`, which
`canopy model` and the ticket's page both call, refuses inside one of canopy's ticks or runs, and refuses a model the
runtime does not list, or a variant the model does not. It is a `ticket_overrides` row of kind `model`, spelled as
config spells a model, `provider/model` or `provider/model@variant`, which may be set before canopy has seen the
ticket and outlasts `canopy forget`, and covers every run of its agent for the ticket until it is cleared, so a canary
ticket stays on one model. It takes the place of config's whole model, its variant too: one naming none runs at the
model's default. The overseer and chores work on no one ticket, so only their default reaches them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, LiteralString

from canopy.core import agent_models, conversation, db, records, sql
from canopy.core.vocab import OverrideKind, RunKind
from canopy.runtime import invocation

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

    from canopy.core.config import Config
    from canopy.runtime.report import ModelList

#: One of a ticket's agents, each a key of `[runtime.models]`: `worker` covers the public and the private worker.
Agent = Literal["worker", "planner", "reviewer"]
#: Every agent of a ticket's, in the order `canopy model KEY` lists them.
AGENTS: tuple[Agent, ...] = ("worker", "planner", "reviewer")
#: The guard of an override naming a model the runtime does not list, or a variant the model does not: it is refused
#: when set, as at a run's start.
UNKNOWN = "unknown_model"
#: Where an agent's next model comes from: the ticket's override, `[runtime.models]`, or neither, the runtime's default.
Source = Literal["ticket", "config", "default"]


@dataclass(frozen=True)
class Next:
    """The model one of a ticket's agents runs on at its next run, and where that choice comes from (DESIGN §13)."""

    agent: Agent
    #: As `provider/model`, or `provider/model@variant`; None for the runtime's default, when neither the ticket nor
    #: config chooses one.
    model: str | None
    source: Source
    #: Config's variant for the agent, which the ticket's override sets aside by naming none of its own, so the agent
    #: runs at the model's default; None otherwise.
    dropped_variant: str | None = None


def agent_of(kind: str) -> Agent:
    """Return the agent a worker run of `kind` is, for its model: `planner` for a plan or feedback plan, else `worker`.

    Returns:
        The agent.
    """
    return "planner" if kind in (RunKind.PLAN, RunKind.FEEDBACK_PLAN) else "worker"


def override(conn: sqlite3.Connection, ticket: str, agent: Agent) -> str | None:
    """Return the model the operator chose for `ticket`'s `agent`, or None when they chose none."""
    found = (
        records.select(records.TicketOverride)
        .where("ticket_key = ? AND agent = ? AND kind = ?", ticket, agent, OverrideKind.MODEL)
        .one(conn)
    )
    return found.value if found is not None else None


def models_for(conn: sqlite3.Connection, config: Config, ticket: str, agent: Agent) -> dict[str, str]:
    """Return `[runtime.models]` with `ticket`'s override for `agent`, if it has one, in the place of config's whole.

    Returns:
        Each agent's model by its key of `[runtime.models]`, as a run of `agent` for `ticket` takes them.
    """
    models = dict(config.runtime.models)
    chosen = override(conn, ticket, agent)
    if chosen is not None:
        models[agent] = chosen
    return models


def next_for(conn: sqlite3.Connection, config: Config, ticket: str) -> list[Next]:
    """Return the model each of `ticket`'s agents runs on at its next run, in `AGENTS`' order.

    Returns:
        A `Next` per agent: its model, and whether the ticket's override, `[runtime.models]`, or neither chose it.
    """
    found: list[Next] = []
    for agent in AGENTS:
        mine = override(conn, ticket, agent)
        configured = config.runtime.models.get(agent)
        if mine is not None:
            dropped = _variant(configured) if _variant(mine) is None else None
            found.append(Next(agent, mine, "ticket", dropped))
        elif configured is not None:
            found.append(Next(agent, configured, "config"))
        else:
            found.append(Next(agent, None, "default"))
    return found


def _variant(model: str | None) -> str | None:
    return agent_models.parse(model).variant if model is not None else None


def last_served(conn: sqlite3.Connection, ticket: str) -> dict[Agent, str]:
    """Return the model that served each of `ticket`'s agents at its latest run whose session canopy has read.

    A run's most costly model names it, as its page lists that first (`run_models.of_run`). A run not read yet, or whose
    read found no model call, is passed over for the one before it.

    Returns:
        Each agent's model, as `provider/model`, by the agent; one none of whose runs has been read is not among them.
    """
    served: LiteralString = "run_models m ON m.run_table = ? AND m.run_id = r.id"
    latest_first: LiteralString = "r.started_at DESC, r.id DESC, m.cost_usd DESC, m.model"
    workers = (
        sql.select("r.kind, m.model")
        .from_("runs r")
        .join(served, "runs")
        .where("r.ticket_key = ?", ticket)
        .order_by(latest_first)
    )
    found: dict[Agent, str] = {}
    for row in sql.execute(conn, workers):
        found.setdefault(agent_of(str(row[0])), str(row[1]))
    reviews = (
        sql.select("m.model")
        .from_("review_runs r")
        .join(served, "review_runs")
        .where("r.ticket_key = ?", ticket)
        .order_by(latest_first)
        .limit(1)
    )
    for row in sql.execute(conn, reviews):
        found["reviewer"] = str(row[0])
    return found


def choose(
    conn: sqlite3.Connection,
    config: Config,
    ticket: str,
    agent: Agent,
    model: str | None,
    *,
    listing: Callable[[bool], ModelList],
    channel: str,
) -> Next:
    """Set `ticket`'s override for `agent` to `model`, or clear it with None (DESIGN §13). Operator only.

    It may be set before canopy has seen the ticket, and covers every run of that agent for the ticket until cleared.
    `listing` reads the models the runtime lists, with their variants when it is passed True, only once the operator
    check has passed: the model must be one of them, and its variant, if it names one, one of the model's, as they
    must again when each run starts.

    Returns:
        The model the agent's next run for the ticket runs on now, and where it comes from.

    Raises:
        Refused: `inside_run` inside one of canopy's own ticks or runs, `model_list_failed` when the runtime's list
            cannot be read, or `unknown_model` for a model it does not list, or a variant the model does not.
    """
    conversation.check_operator()
    if model is not None:
        check(model, listing(agent_models.parse(model).variant is not None))
    where = "ticket_key = ? AND agent = ? AND kind = ?"
    with db.transaction(conn):
        records.delete(records.TicketOverride).where(where, ticket, agent, OverrideKind.MODEL).run(conn)
        if model is not None:
            records.insert(
                records.TicketOverride,
                ticket_key=ticket,
                agent=agent,
                kind=OverrideKind.MODEL,
                value=model,
                channel=channel,
                set_at=db.now(),
            ).run(conn)
    return next(n for n in next_for(conn, config, ticket) if n.agent == agent)


def check(model: str, listed: ModelList) -> None:
    """Refuse a model the operator is choosing that the runtime does not list, or a variant of it the model lacks.

    `listed` holds the variants when `model` names one. Refused when set, as again when a run starts.

    Raises:
        Refused: `unknown_model` for a model the runtime does not list, or a variant the model does not, or
            `model_list_failed` when the list could not be read.
    """
    named = agent_models.parse(model)
    if listed.error is not None:
        raise conversation.Refused(
            agent_models.LIST_FAILED,
            f"could not read the models {invocation.NAME} lists, to look {model} up: {listed.error}",
        )
    if named.id not in listed.models:
        raise conversation.Refused(
            UNKNOWN,
            f"{invocation.NAME} does not list the model {named.id}: name one `canopy models` lists, or set up its "
            "provider",
        )
    if named.variant is not None and named.variant not in listed.variants.get(named.id, ()):
        raise conversation.Refused(
            UNKNOWN,
            f"{invocation.NAME} lists the model {named.id} but not its variant {named.variant} "
            f"({agent_models.variants_listed(listed, named.id)}): name one it lists, or the model alone",
        )
