"""`canopy desk`: the operator's own checkout of a ticket's branch, a slot per repository (DESIGN §18).

Opening and closing a desk change the pools, so each waits for a running tick to end and holds the dispatch lock,
as `canopy workspace release` does. Both refuse inside canopy's own ticks and runs: a desk is the operator's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from canopy.cli.common import CliError, between_ticks, open_context, require_workspace
from canopy.cli.params import REPO, TICKET_KEY
from canopy.core import conversation, db
from canopy.runs import checkouts

if TYPE_CHECKING:
    from canopy.core.context import Context


@click.command("desk")
@click.argument("key", type=TICKET_KEY)
@click.option(
    "--repo",
    "repos",
    multiple=True,
    type=REPO,
    help="Only this repository's unit; repeat for several. Every unit with the branch, without it.",
)
@click.option("--close", "close", is_flag=True, help="Return the desk's slots and remove it.")
@click.option("--discard", is_flag=True, help="With --close, lose uncommitted changes and commits origin lacks.")
@click.pass_context
def cmd_desk(click_ctx: click.Context, key: str, repos: tuple[str, ...], *, close: bool, discard: bool) -> int:
    """Check KEY's branch out for yourself, in a slot of each repository it has a unit in, linked from one directory.

    The desk is `checkouts/KEY/` in the workspace: a link per repository to its slot, each on the ticket's branch as a
    local branch tracking origin's, so you commit and push as in any checkout, and a `KEY.code-workspace` file that
    opens every slot in one VS Code window. The slots are leased as yours until you close the desk: no tick returns
    them, and a run of the ticket works in slots of its own and pushes to the same branch. --close returns the slots,
    refusing while one has uncommitted changes or commits origin lacks, unless --discard loses them. Waits for a
    running tick to end.
    """
    try:
        conversation.check_operator()
    except conversation.Refused as r:
        raise CliError(f"desk refused ({r.guard}): {r.reason}") from None
    if discard and not close:
        raise click.UsageError("--discard is for --close")
    if close and repos:
        raise click.UsageError("--close returns every slot of the desk; leave out --repo")
    require_workspace()
    ctx = open_context(click_ctx)
    for name in repos:
        if ctx.workspace.repo(name) is None:
            raise CliError(f"the map lists no repository {name}")
    with between_ticks(ctx, "desk", dispatches=True):
        found = checkouts.find(ctx.workspace.root, key)
        if close:
            return _close(ctx, key, found, discard=discard)
        if found is not None:
            click.echo(f"{key}'s desk is already open" + ("; close it to change its repositories." if repos else "."))
            _show(found)
            return 0
        try:
            desk = checkouts.open_desk(ctx, key, repos)
        except checkouts.CheckoutError as e:
            raise CliError(str(e)) from None
        click.echo(f"{key}'s desk is open.")
        _show(desk)
        running = db.running_run_of(ctx.conn, key)
        if running is not None:
            click.echo(
                f"Run {running.id} ({running.kind}) is working {key} now, in slots of its own, and pushes to the "
                "same branch; pull before you push.",
            )
    return 0


def _close(ctx: Context, key: str, desk: checkouts.Desk | None, *, discard: bool) -> int:
    if desk is None:
        click.echo(f"{key} has no desk open.")
        return 0
    try:
        unsafe = checkouts.close_desk(ctx, desk, discard=discard)
    except checkouts.CheckoutError as e:
        raise CliError(str(e)) from None
    if unsafe:
        raise CliError(
            f"{key}'s desk has work origin lacks: {'; '.join(str(u) for u in unsafe)}. Commit and push it, "
            "or `--discard` it; nothing was returned.",
        )
    click.echo(f"{key}'s desk is closed; its slots are returned: {', '.join(desk.slots)}.")
    return 0


def _show(desk: checkouts.Desk) -> None:
    for name, slot in desk.slots.items():
        click.echo(f"  {name}: {slot} on {desk.branch}")
    click.echo(f"Open it in VS Code: code {desk.workspace_file}")
    click.echo(f"Close it when you are done: canopy desk {desk.key} --close")
