"""`canopy models`, the models the runtime lists, and `canopy model`, a ticket's choice of one for an agent (§13)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from canopy.cli.common import CliError, open_context
from canopy.core import agent_models, conversation, ticket_models
from canopy.infra import logs
from canopy.runtime import invocation
from canopy.runtime import models as runtime_models

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from canopy.runtime.report import ModelList

CLI = "cli"
#: How `canopy model KEY` names where each agent's model comes from.
SOURCES: dict[ticket_models.Source, str] = {
    "ticket": "this ticket's override",
    "config": "[runtime.models]",
    "default": "nothing sets one",
}


@click.command("model")
@click.argument("key", metavar="KEY")
@click.argument("model", metavar="[MODEL]", required=False)
@click.option(
    "--agent",
    type=click.Choice(ticket_models.AGENTS),
    help="The agent to choose for: its planner or its reviewer. The ticket's workers without it.",
)
@click.option("--clear", is_flag=True, help="Clear the override: the agent's runs take [runtime.models]' again.")
@click.pass_context
def cmd_model(
    click_ctx: click.Context,
    key: str,
    model: str | None,
    agent: ticket_models.Agent | None,
    *,
    clear: bool,
) -> int:
    """Choose the model MODEL for the ticket KEY's workers, or with --agent its planner or reviewer.

    It covers every run of that agent for the ticket, from its next, until you clear it with --clear, and may be set
    before canopy has seen the ticket; `canopy forget` keeps it. MODEL is `provider/model`, one `canopy models` lists;
    a run whose model is no longer listed by then is refused, never run on another. Without MODEL or --clear, prints
    each agent's next model and where it comes from. Only from your shell or the web UI: never inside one of canopy's
    runs. The overseer and chores take only their model in [runtime.models].
    """
    try:
        ref = conversation.parse_ref(key)
        conversation.check_verb(ref, "model")
    except conversation.Refused as r:
        raise CliError(f"model refused ({r.guard}): {r.reason}") from None
    if model is not None and clear:
        raise click.UsageError("give MODEL or --clear, not both")
    ctx = open_context(click_ctx)
    if model is None and not clear:
        found = ticket_models.next_for(ctx.conn, ctx.config, ref.id)
        for line in show(ref.id, [n for n in found if agent is None or n.agent == agent]):
            click.echo(line)
        return 0
    chosen_for: ticket_models.Agent = agent or "worker"
    try:
        now = ticket_models.choose(
            ctx.conn,
            ctx.config,
            ref.id,
            chosen_for,
            model,
            listing=lambda: runtime_models.listed(
                ctx.runner,
                version=ctx.config.runtime.version,
                cwd=ctx.workspace.root,
            ),
            channel=CLI,
        )
    except conversation.Refused as r:
        raise CliError(f"model refused ({r.guard}): {r.reason}") from None
    logs.for_tick(None).info(
        "model chosen" if model is not None else "model cleared",
        extra={"ticket": ref.id, "agent": chosen_for, "model": model, "channel": CLI},
    )
    click.echo(f"{ref.id}'s {chosen_for} runs use {named(now.model)} from their next run: {SOURCES[now.source]}.")
    return 0


@click.command("models")
@click.pass_context
def cmd_models(click_ctx: click.Context) -> int:
    """List the models the runtime can run an agent on, read from it now in the workspace root.

    Each line names the agents [runtime.models] chooses it for. The list is the runtime's own, from its cache or the
    catalog built into it: a model on it can still fail when called. Exits 1 when the list cannot be read, or an agent's
    model in [runtime.models] is not on it, since that agent's runs are refused until it is.
    """
    ctx = open_context(click_ctx)
    lines, refused = render(
        runtime_models.listed(ctx.runner, version=ctx.config.runtime.version, cwd=ctx.workspace.root),
        ctx.config.runtime.models,
    )
    for line in lines:
        click.echo(line)
    return int(refused)


def named(model: str | None) -> str:
    """A model as `canopy model` names it: its id, or for None the runtime's default.

    Returns:
        The words.
    """
    return model if model is not None else f"{invocation.NAME}'s default"


def show(key: str, found: Sequence[ticket_models.Next]) -> list[str]:
    """Each agent's next model for ticket `key`, as `canopy model KEY` prints it.

    Returns:
        The lines, without line ends: a heading, then a line per agent.
    """
    lines = [f"{key}'s models, from each agent's next run:"]
    lines.extend(f"  {n.agent:<8}  {named(n.model)}  ({SOURCES[n.source]})" for n in found)
    return lines


def render(listed: ModelList, models: Mapping[str, str]) -> tuple[list[str], bool]:
    """The models as `canopy models` prints them, and whether an agent's runs would be refused their model.

    Returns:
        The lines, without line ends: a line per model, then one per model `models`, `runtime.models`, names that is
        not listed; and True when the list could not be read or such a model is named.
    """
    if listed.error is not None:
        return [f"could not read the models {invocation.NAME} lists ({agent_models.LIST_FAILED}): {listed.error}"], True
    count = len(listed.models)
    lines = [f"{invocation.NAME} lists {count} model{'' if count == 1 else 's'}:"]
    for model in sorted(listed.models):
        roles = [role for role, chosen in models.items() if chosen == model]
        lines.append(f"  {model}  (runtime.models: {', '.join(roles)})" if roles else f"  {model}")
    gone = [(role, chosen) for role, chosen in models.items() if chosen not in listed.models]
    lines.extend(
        f"runtime.models.{role} names {chosen}, which {invocation.NAME} does not list: its runs refuse "
        f"({agent_models.MISSING})."
        for role, chosen in gone
    )
    return lines, bool(gone)
