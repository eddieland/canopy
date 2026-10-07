"""`canopy workspace sync`: make the workspace match its map and the declared slots (DESIGN §18)."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING

import click

from canopy.cli.common import CliError, open_context
from canopy.core import config, workspace
from canopy.infra import lock
from canopy.setup import init
from canopy.setup import workspace as setup_workspace

if TYPE_CHECKING:
    from canopy.core.context import Context

# What sync reports for a repository it could not bring to what is declared; any of them makes it exit 1.
_UNMET = ("failed", "kept")


@click.group("workspace")
def workspace_group() -> None:
    """Manage a workspace of several repositories."""


@workspace_group.command("sync")
@click.option("--dry-run", is_flag=True, help="Say what sync would clone, make, and remove, and change nothing.")
@click.pass_context
def cmd_sync(click_ctx: click.Context, *, dry_run: bool) -> int:
    """Make the workspace match the map and the slots declared for its pools.

    Clones the map's repositories that have no clone, and reports an origin that differs from the map. With
    capacity.slots_per_repo or capacity.repo_slots set, makes or removes idle slots until each pool has its declared
    size. Removes a clone under repos/ that the map no longer lists, with its slots, when nothing in either would be
    lost. Prints each clone before it runs. Never changes an existing clone's remotes. Waits for a running tick to end.
    """
    if workspace.find_root(Path.cwd()) is None:
        raise CliError(f"no {config.WORKSPACE_FILE_NAME} here or above; run `canopy init --workspace` first")
    ctx = open_context(click_ctx)
    with contextlib.ExitStack() as stack:
        # A tick leases slots and reads the pools; sync changes them only between ticks.
        try:
            stack.enter_context(lock.hold(ctx.lock_path))
        except lock.LockBusyError:
            click.echo("A tick is running; sync starts when it ends.")
            stack.enter_context(lock.hold(ctx.lock_path, wait=True))
        results = _sync(ctx, dry_run=dry_run)
    unmet = sum(r.outcome in _UNMET for r in results)
    if unmet:
        raise CliError(f"{unmet} of {len(results)} steps did not reach what is declared; see above")
    return 0


def _sync(ctx: Context, *, dry_run: bool) -> list[setup_workspace.Checked]:
    ws = ctx.workspace
    results: list[setup_workspace.Checked] = []
    if not ws.repos:
        click.echo(f"The map lists no repositories; add them under [repos.<name>] in {ws.map_file}.")
    for repo in ws.repos:
        results.append(_report(_clone_or_check(ctx, ws, repo, dry_run=dry_run)))
        want = ctx.config.capacity.slots_for(repo.name)
        if want is not None and repo.cloned:
            results.append(_report(setup_workspace.converge_pool(ctx.runner, ws, repo, want, dry_run=dry_run)))
    results += [
        _report(setup_workspace.remove(ctx.runner, ws, r, dry_run=dry_run)) for r in setup_workspace.undeclared(ws)
    ]
    return results


def _clone_or_check(
    ctx: Context, ws: workspace.Workspace, repo: workspace.Repo, *, dry_run: bool
) -> setup_workspace.Checked:
    if repo.cloned:
        return setup_workspace.check_origin(ctx.runner, repo)
    url = setup_workspace.shown(str(repo.url))
    if dry_run:
        return setup_workspace.Checked(repo, "to clone", f"{url} into {repo.path}")
    click.echo(f"{repo.name}: cloning {url} into {repo.path}")
    if repo.url is not None and init.is_ssh_url(repo.url):
        click.echo(f"{repo.name}: warning: {url} is reached over SSH; canopy recommends HTTPS (D038)")
    return setup_workspace.clone(ctx.runner, ws, repo)


def _report(checked: setup_workspace.Checked) -> setup_workspace.Checked:
    detail = f": {checked.detail}" if checked.detail else ""
    click.echo(f"{checked.repo.name}: {checked.outcome}{detail}")
    return checked
