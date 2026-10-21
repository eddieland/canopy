"""`canopy personas`, each persona a run could get, and `canopy persona`, a ticket's or a PR's choice of one (§31)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from canopy.cli.common import CliError, open_context
from canopy.core import conversation, personas, review_requests
from canopy.infra import logs

if TYPE_CHECKING:
    from collections.abc import Sequence

    from canopy.core.config import Config
    from canopy.core.context import Context

CLI = "cli"
#: How `canopy persona KEY` names where each agent's persona comes from.
SOURCES: dict[personas.Source, str] = {
    "ticket": "this ticket's override",
    "config": "[personas]",
    "default": "canopy's default",
}


@click.command("personas")
@click.pass_context
def cmd_personas(click_ctx: click.Context) -> int:
    """List each persona: canopy's own, and yours in paths.personas, which shadow canopy's of the same name.

    Each line says where the persona comes from and which agents [personas] names it for. A run whose persona has no
    file, or one canopy will not put in a prompt, is refused, never run in another voice. Exits 1 when an agent's
    persona is such a one.
    """
    ctx = open_context(click_ctx)
    lines, refused = render(ctx.config)
    for line in lines:
        click.echo(line)
    return int(refused)


@click.command("persona")
@click.argument("key", metavar="KEY|URL")
@click.argument("name", metavar="[NAME]", required=False)
@click.option(
    "--agent",
    type=click.Choice(personas.AGENTS),
    help="The agent to choose for: its planner or its reviewer. The ticket's workers without it; a PR's reviewer.",
)
@click.option("--clear", is_flag=True, help="Clear the override: the agent's runs take [personas]' choice again.")
@click.option(
    "--next",
    "next_only",
    is_flag=True,
    help="For the agent's next run alone, its workers' or planner's; with --clear, clear that choice.",
)
@click.pass_context
def cmd_persona(
    click_ctx: click.Context,
    key: str,
    name: str | None,
    agent: personas.Agent | None,
    *,
    clear: bool,
    next_only: bool,
) -> int:
    """Choose the persona NAME for the ticket KEY's workers, or with --agent its planner or reviewer.

    It covers every run of that agent for the ticket, from its next, until you clear it with --clear, and may be set
    before canopy has seen the ticket. NAME is one `canopy personas` lists; a run whose persona's file has gone by then
    is refused, never run in another voice. Without NAME or --clear, prints each agent's next persona and where it
    comes from. Only from your shell or the web UI: never inside one of canopy's runs.

    With --next, NAME is for the agent's next run alone, whatever kind it is, in place of the override and
    [personas]; the runs after it go back to those. `canopy start KEY --persona` and `canopy plan KEY --persona` choose
    it too.

    URL, a PR's, chooses the persona of the review you requested of it with `canopy start URL --review`, as that
    command's --persona does.
    """
    try:
        ref = conversation.parse_ref(key)
        conversation.check_verb(ref, "persona")
    except conversation.Refused as r:
        raise CliError(f"persona refused ({r.guard}): {r.reason}") from None
    if name is not None and clear:
        raise click.UsageError("give NAME or --clear, not both")
    ctx = open_context(click_ctx)
    if ref.kind == conversation.PR:
        if agent not in (None, "reviewer") or next_only:
            raise click.UsageError(
                "a PR's review request has only its review's persona: no --agent but reviewer, or --next",
            )
        return _pr_persona(ctx, ref, name, clear=clear)
    if next_only:
        return _next_persona(ctx, ref.id, agent, name, clear=clear)
    if name is None and not clear:
        found = personas.next_for(ctx.conn, ctx.config, ref.id)
        for line in show(ref.id, [n for n in found if agent is None or n.agent == agent]):
            click.echo(line)
        return 0
    chosen_for: personas.Agent = agent or "worker"
    try:
        now = personas.choose(ctx.conn, ctx.config, ref.id, chosen_for, name, channel=CLI)
    except conversation.Refused as r:
        raise CliError(f"persona refused ({r.guard}): {r.reason}") from None
    logs.for_tick(None).info(
        "persona chosen" if name is not None else "persona cleared",
        extra={"ticket": ref.id, "agent": chosen_for, "persona": name, "channel": CLI},
    )
    click.echo(f"{ref.id}'s {chosen_for} runs write in {now.name} from their next run: {SOURCES[now.source]}.")
    if now.error is not None:
        click.echo(f"  its runs refuse: {now.error}")
    return 0


def _next_persona(ctx: Context, key: str, agent: personas.Agent | None, name: str | None, *, clear: bool) -> int:
    # The persona of the agent's next run alone, chosen or cleared.
    if agent == "reviewer":
        raise click.UsageError("--next is for a ticket's workers or planner; its reviews take its override")
    if name is None and not clear:
        raise click.UsageError("--next takes NAME, or --clear")
    chosen_for: personas.NextAgent = agent or "worker"
    try:
        now = personas.choose_next(ctx.conn, ctx.config, key, chosen_for, name, channel=CLI)
    except conversation.Refused as r:
        raise CliError(f"persona refused ({r.guard}): {r.reason}") from None
    logs.for_tick(None).info(
        "next run's persona chosen" if name is not None else "next run's persona cleared",
        extra={"ticket": key, "agent": chosen_for, "persona": name, "channel": CLI},
    )
    standing = f"{now.name}: {SOURCES[now.source]}"
    if now.once is None:
        click.echo(f"{key}'s next {chosen_for} run writes in {standing}.")
    else:
        click.echo(f"{key}'s next {chosen_for} run alone writes in {now.once}; the runs after it, in {standing}.")
    if now.error is not None:
        click.echo(f"  that run refuses: {now.error}")
    return 0


def _pr_persona(ctx: Context, ref: conversation.Ref, name: str | None, *, clear: bool) -> int:
    # A review request's persona: shown, chosen, or cleared, as a ticket's reviewer override is.
    if name is not None or clear:
        try:
            review_requests.choose_persona(ctx.conn, ctx.config, ref, name)
        except conversation.Refused as r:
            raise CliError(f"persona refused ({r.guard}): {r.reason}") from None
        logs.for_tick(None).info(
            "persona chosen" if name is not None else "persona cleared",
            extra={"pr": ref.id, "agent": "reviewer", "persona": name, "channel": CLI},
        )
    found = review_requests.open_request(ctx.conn, ref.id)
    if found is None:
        raise CliError(f"{ref} has no open review request; ask for one with `canopy start {ref} --review`")
    chosen = review_requests.persona_of(ctx.conn, found.id)
    configured = ctx.config.personas.reviewer
    source = (
        "this request's" if chosen is not None else SOURCES["config" if configured != personas.DEFAULT else "default"]
    )
    click.echo(f"{ref}'s review is written in {chosen or configured}, from its next: {source}.")
    return 0


def show(key: str, found: Sequence[personas.Next]) -> list[str]:
    """Each agent's next persona for ticket `key`, as `canopy persona KEY` prints it.

    Returns:
        The lines, without line ends: a heading, then a line per agent, and under one whose run would refuse its
        persona, why.
    """
    lines = [f"{key}'s personas, from each agent's next run:"]
    for n in found:
        lines.append(f"  {n.agent:<8}  {n.name}  ({SOURCES[n.source]})")
        if n.once is not None:
            lines.append(f"    its next run alone: {n.once}")
        if n.error is not None:
            lines.append(f"    its runs refuse: {n.error}")
    return lines


def render(config: Config) -> tuple[list[str], bool]:
    """The personas as `canopy personas` prints them, and whether an agent's runs would refuse their persona.

    Returns:
        The lines, without line ends: a line per persona, then one per agent whose persona has no file; and True when
        an agent's persona has no file or a file canopy will not use.
    """
    found = personas.listed(config)
    lines = [f"Personas ({len(found)}):"]
    for p in found:
        where = f"yours, {p.path}" if p.yours else "canopy's"
        where += ", in place of canopy's" if p.shadows else ""
        default = f"; the default for {', '.join(p.defaults)}" if p.defaults else ""
        lines.append(f"  {p.name}  {where}{default}")
        if p.error is not None:
            lines.append(f"    refused ({personas.BAD}): {p.error}")
    listed = {p.name for p in found}
    missing = [a for a in personas.AGENTS if getattr(config.personas, a) not in listed]
    lines.extend(
        f"[personas] {agent} names {getattr(config.personas, agent)}, which has no file: its runs refuse "
        f"({personas.MISSING})."
        for agent in missing
    )
    refused = bool(missing) or any(p.error is not None and p.defaults for p in found)
    return lines, refused
