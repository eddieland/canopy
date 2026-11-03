"""`canopy initiative`: work spanning several tickets (DESIGN §43), and how `show` treats `init:N`.

A submission and each change of membership write through `canopy.core.initiatives`, each refusing inside canopy's own
ticks and runs (`inside_run`): only the operator submits an initiative or says which tickets are its members. A member
is worked only once a label or a start says so, as any ticket is.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

import click

from canopy.cli.common import CliError, open_context
from canopy.cli.params import REPO
from canopy.core import conversation, initiatives, plans
from canopy.core.items import age
from canopy.core.vocab import PlanStatus, RunStatus
from canopy.infra import logs
from canopy.infra.text import one_line, printable
from canopy.runs import initiative_runs

if TYPE_CHECKING:
    from canopy.core.context import Context

CLI = "cli"
#: How much of an initiative's text `canopy initiative list` shows on its line.
LIST_TEXT = 80


@click.group("initiative")
def initiative_group() -> None:
    """Hand canopy work that spans several tickets, and say which tickets are its members (DESIGN §43)."""


@initiative_group.command("submit")
@click.argument("text", metavar="TEXT")
@click.option(
    "--repo",
    "repos",
    type=REPO,
    multiple=True,
    help="A repository its plan reads; repeat for each. Required when the workspace has several.",
)
@click.option("--project", metavar="KEY", help="The tracker project its tickets are filed in. None by default.")
@click.option(
    "--epic",
    metavar="KEY",
    help="A tracker epic whose tickets are put to you as suggestions; none is a member until you add it.",
)
@click.pass_context
def cmd_initiative_submit(
    click_ctx: click.Context,
    text: str,
    repos: tuple[str, ...],
    project: str | None,
    epic: str | None,
) -> int:
    """Submit TEXT, the initiative's goal in your own words, or read it from stdin when TEXT is `-`.

    `canopy initiative add init:N KEY` makes a ticket one of its members, which authorizes no work on it: a member is
    worked once it is labeled or started, as any ticket is. A tracker's epic or parent link never makes a ticket a
    member. `canopy show init:N` shows it and its members.
    """
    try:
        # Before stdin is read: inside a run, it would wait on whatever the agent left open.
        conversation.check_operator()
    except conversation.Refused as r:
        raise CliError(f"initiative submit refused ({r.guard}): {r.reason}") from None
    body = sys.stdin.read() if text == "-" else text
    ctx = open_context(click_ctx)
    try:
        found = initiatives.submit(
            ctx.conn,
            ctx.workspace,
            body,
            repos=repos,
            project=project,
            epic=epic,
            channel=CLI,
        )
    except conversation.Refused as r:
        raise CliError(f"initiative submit refused ({r.guard}): {r.reason}") from None
    names = initiatives.repos_of(ctx.conn, found.id)
    logs.for_tick(None).info("initiative submitted", extra={"initiative": found.id, "channel": CLI})
    click.echo(f"Submitted init:{found.id}, over {', '.join(names)}.")
    click.echo(f"`canopy initiative add init:{found.id} KEY` makes a ticket one of its members.")
    return 0


@initiative_group.command("list")
@click.pass_context
def cmd_initiative_list(click_ctx: click.Context) -> int:
    """List your initiatives, the newest first, each with how many members it has."""
    ctx = open_context(click_ctx)
    found = initiatives.every(ctx.conn)
    for initiative in found:
        text = one_line(initiative.text)
        cut = f"{text[:LIST_TEXT]}..." if len(text) > LIST_TEXT else text
        held = len(initiatives.members_of(ctx.conn, initiative.id))
        click.echo(f"init:{initiative.id}  {held} members  {age(initiative.submitted_at)}  {cut}")
    if not found:
        click.echo("No initiatives yet: `canopy initiative submit TEXT` hands canopy one.")
    return 0


@initiative_group.command("add")
@click.argument("ref", metavar="init:N")
@click.argument("keys", metavar="KEY...", nargs=-1, required=True)
@click.option(
    "--entry",
    "entries",
    metavar="B<n>",
    multiple=True,
    help="An entry of the approved plan's breakdown each KEY fulfils; repeat for each. Replaces their entries.",
)
@click.option("--no-entry", is_flag=True, help="Register each KEY against no entry: a ticket the plan did not foresee.")
@click.pass_context
def cmd_initiative_add(
    click_ctx: click.Context,
    ref: str,
    keys: tuple[str, ...],
    entries: tuple[str, ...],
    *,
    no_entry: bool,
) -> int:
    """Make each ticket KEY a member of initiative init:N: every one, or none if one is refused.

    A ticket is a member of one initiative at most, and an initiative holds at most policy.max_initiative_tickets.
    Membership authorizes no work: a member is worked once it is labeled or started, as any ticket is. With --entry,
    each KEY is registered against those entries of the approved plan's breakdown, in place of any it had: the plan
    is approved first, then its tickets filed and registered as you choose. Without it, a member keeps its entries.
    """
    if entries and no_entry:
        raise click.UsageError("--entry names the entries each KEY fulfils, and --no-entry none; pass one")
    initiative_id = _initiative(ref, "add")
    ctx = open_context(click_ctx)
    try:
        done = initiatives.add(
            ctx.conn,
            initiative_id,
            keys,
            bound=ctx.config.policy.max_initiative_tickets,
            channel=CLI,
            entries=entries if entries or no_entry else None,
            state_dir=ctx.state_dir,
        )
    except conversation.Refused as r:
        raise CliError(f"initiative add refused ({r.guard}): {r.reason}") from None
    logs.for_tick(None).info(
        "initiative members added",
        extra={"initiative": initiative_id, "keys": list(done.added), "channel": CLI},
    )
    if done.added:
        click.echo(f"Added {', '.join(done.added)} to init:{initiative_id}.")
    if done.already:
        click.echo(f"Already members: {', '.join(done.already)}.")
    if done.entries is not None:
        named = ", ".join(sorted(done.entries, key=lambda e: int(e[1:]))) or "no entry"
        click.echo(f"Registered {', '.join(keys)} against {named}.")
    return 0


@initiative_group.command("remove")
@click.argument("ref", metavar="init:N")
@click.argument("keys", metavar="KEY...", nargs=-1, required=True)
@click.pass_context
def cmd_initiative_remove(click_ctx: click.Context, ref: str, keys: tuple[str, ...]) -> int:
    """End each ticket KEY's membership of initiative init:N: every one, or none if one is not a member.

    The ticket and its work are left as they are.
    """
    initiative_id = _initiative(ref, "remove")
    ctx = open_context(click_ctx)
    try:
        removed = initiatives.remove(ctx.conn, initiative_id, keys, channel=CLI)
    except conversation.Refused as r:
        raise CliError(f"initiative remove refused ({r.guard}): {r.reason}") from None
    logs.for_tick(None).info(
        "initiative members removed",
        extra={"initiative": initiative_id, "keys": removed, "channel": CLI},
    )
    click.echo(f"Removed {', '.join(removed)} from init:{initiative_id}.")
    return 0


def show(ctx: Context, initiative_id: int) -> None:
    """Print initiative `initiative_id`: its text, repositories, project, epic, and members.

    Raises:
        CliError: canopy has no such initiative.
    """
    found = initiatives.get(ctx.conn, initiative_id)
    if found is None:
        raise CliError(f"canopy has no init:{initiative_id}")
    click.echo(f"init:{found.id}: submitted {age(found.submitted_at)} ago via {found.channel}")
    click.echo(f"  repositories {', '.join(initiatives.repos_of(ctx.conn, found.id))}")
    click.echo(f"  project {found.project}" if found.project else "  no project: it files no tickets")
    if found.epic:
        click.echo(f"  epic {found.epic}: its tickets are suggestions, none a member until you add it")
    click.echo("\nText:")
    for line in printable(found.text).splitlines():
        click.echo(f"    {line}")
    members = initiatives.members_of(ctx.conn, found.id)
    bound = ctx.config.policy.max_initiative_tickets
    click.echo(f"\nMembers ({len(members)} of at most {bound}):")
    for member in members:
        fulfils = ", ".join(initiatives.entries_of(ctx.conn, member.id)) or "no entry"
        click.echo(f"  {member.ticket_key}  {fulfils}  added {age(member.added_at)} ago via {member.added_channel}")
    if not members:
        click.echo(f"  none yet: `canopy initiative add init:{found.id} KEY` adds one")
    _show_plan(ctx, found.id)


def _show_plan(ctx: Context, initiative_id: int) -> None:
    """Print the initiative's plan runs, each with how it ended, and its current plan's status and file (DESIGN §43)."""
    runs = initiative_runs.runs_of(ctx.conn, initiative_id)
    click.echo(f"\nPlan runs ({len(runs)} of at most {ctx.config.policy.max_plan_attempts}):")
    for run in runs:
        said = ""
        if run.result_json:
            result = json.loads(run.result_json)
            said = one_line(str(result.get("harness") or result.get("question") or result.get("summary") or ""))
        click.echo(f"  {run.id}  {run.status}  {age(run.started_at)} ago" + (f"  {printable(said)}" if said else ""))
    if not runs:
        click.echo("  none yet: the next tick starts one")
    plan = initiatives.current_plan(ctx.conn, initiative_id)
    if plan is None:
        return
    path = initiatives.plan_path(ctx.state_dir, initiative_id, plan.run_id)
    reading = plans.read(path)
    where = path if reading.text is not None else f"{path} ({reading.problem})"
    click.echo(f"\nPlan: {plan.status}, written {age(plan.created_at)} ago by run {plan.run_id}\n  {where}")
    if plan.status is PlanStatus.PROPOSED:
        click.echo(
            f"  `canopy plan init:{initiative_id} --approve` approves it; `canopy reply init:{initiative_id}` asks",
        )
        click.echo("  for changes.")
    _show_breakdown(ctx, initiative_id)


def _show_breakdown(ctx: Context, initiative_id: int) -> None:
    """Print each entry of the approved plan's breakdown with the members that fulfil it, or none yet (DESIGN §43)."""
    try:
        outline = initiatives.approved_outline(ctx.conn, ctx.state_dir, initiative_id)
    except conversation.Refused as r:
        click.echo(f"\nBreakdown: cannot be read ({r.reason})")
        return
    if outline is None:
        return
    fulfilling: dict[str, list[str]] = {}
    for member in initiatives.members_of(ctx.conn, initiative_id):
        for entry in initiatives.entries_of(ctx.conn, member.id):
            fulfilling.setdefault(entry, []).append(member.ticket_key)
    left = sum(1 for e in outline.entries if e not in fulfilling)
    click.echo(f"\nBreakdown of the approved plan ({left} of {len(outline.entries)} with no member yet):")
    for entry in outline.entries.values():
        members = ", ".join(fulfilling.get(entry.id, [])) or "none yet"
        trivial = "  trivial" if entry.trivial is not None else ""
        click.echo(f"  {entry.id}. {printable(one_line(entry.title))}  {members}{trivial}")


def replied(ctx: Context, initiative_id: int) -> None:
    """Say what a reply to initiative `initiative_id` starts: its next plan run, at the next tick or after its run."""
    runs = initiative_runs.runs_of(ctx.conn, initiative_id)
    limit = ctx.config.policy.max_plan_attempts
    if len(runs) >= limit:
        click.echo(f"It has had {len(runs)} plan runs, policy.max_plan_attempts; none starts again for this reply.")
    elif any(r.status is RunStatus.RUNNING for r in runs):
        click.echo("Its plan run is still working; the first tick after it ends starts the next, with your reply.")
    else:
        click.echo("The next tick starts its next plan run, which reads your reply.")


def approve(ctx: Context, initiative_id: int) -> None:
    """Approve initiative `initiative_id`'s waiting plan as its file stands, and say what it changed (DESIGN §43).

    Raises:
        CliError: canopy has no such initiative, or refused the approval.
    """
    if initiatives.get(ctx.conn, initiative_id) is None:
        raise CliError(f"canopy has no init:{initiative_id}")
    repos = frozenset(initiatives.repos_of(ctx.conn, initiative_id))
    try:
        done = initiatives.approve(ctx.conn, ctx.state_dir, initiative_id, repos=repos, channel=CLI)
    except conversation.Refused as r:
        raise CliError(f"plan refused ({r.guard}): {r.reason}") from None
    except plans.PlanFileError as e:
        raise CliError(f"plan refused (unwritable): {e}") from None
    logs.for_tick(None).info("initiative plan approved", extra={"initiative": initiative_id, "plan": done.plan.id})
    click.echo(f"Approved init:{initiative_id}'s plan, written by run {done.plan.run_id}.")
    if done.change is not None:
        for word, ids in (
            ("added", done.change.added),
            ("removed", done.change.removed),
            ("changed", done.change.changed),
        ):
            if ids:
                click.echo(f"  {word}: {', '.join(sorted(ids, key=lambda i: (i[0], int(i[1:]))))}")


def _initiative(ref: str, verb: str) -> int:
    """The initiative `ref` names, `init:N`.

    Returns:
        Its id.

    Raises:
        CliError: `ref` is not an initiative's reference.
    """
    try:
        subject = conversation.parse_ref(ref)
    except conversation.Refused as r:
        raise CliError(f"initiative {verb} refused ({r.guard}): {r.reason}") from None
    if subject.kind != conversation.INITIATIVE:
        raise CliError(f"initiative {verb} refused (bad_ref): {ref} is a {subject.kind}; name an initiative, init:N")
    return int(subject.id)
