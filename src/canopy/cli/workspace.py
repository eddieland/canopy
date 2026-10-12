"""`canopy workspace sync` and `add`: make the workspace match its map and the declared slots (DESIGN §18)."""

from __future__ import annotations

import contextlib
import dataclasses
from collections.abc import Sequence
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
    _require_workspace()
    check_synced(sync(click_ctx, dry_run=dry_run))
    return 0


@workspace_group.command("add")
@click.argument("repos", metavar="[NAME=]URL...", nargs=-1, required=True)
@click.pass_context
def cmd_add(click_ctx: click.Context, repos: tuple[str, ...]) -> int:
    """Add repositories to the map by clone URL, then sync.

    Each repository is named after its URL's last path segment without .git, unless given as NAME=URL. A URL the map
    already lists is left as it is. Write a one-line summary for each in the map, and describe them in MAP.md, for the
    overseer.
    """
    _require_workspace()
    check_synced(sync(click_ctx, dry_run=False, add=repos))
    return 0


def _require_workspace() -> Path:
    root = workspace.find_root(Path.cwd())
    if root is None:
        raise CliError(f"no {config.WORKSPACE_FILE_NAME} here or above; run `canopy init` first")
    return root


def add_repos(ws: workspace.Workspace, repos: Sequence[str]) -> None:
    """Add each `[NAME=]URL` in `repos` to the map, and print what was added. Nothing is written if one is refused."""
    try:
        entries = [setup_workspace.repo_arg(arg) for arg in repos]
        added = setup_workspace.add(ws, entries)
    except ValueError as e:
        raise CliError(f"{e}; nothing was added to {ws.map_file}") from e
    for a in added:
        detail = f": {a.detail}" if a.detail else ""
        click.echo(f"{a.name}: {a.outcome}{detail}")


def sync(click_ctx: click.Context, *, dry_run: bool, add: Sequence[str] = ()) -> list[setup_workspace.Checked]:
    """Add the `[NAME=]URL`s in `add` to the map, then make the workspace match its map and declared slots.

    Both happen between ticks, under the tick lock, which also serializes two of these. Returns what each sync step
    found or did.
    """
    ctx = open_context(click_ctx)
    with contextlib.ExitStack() as stack:
        # A tick leases slots and reads the pools; sync changes them only between ticks.
        try:
            stack.enter_context(lock.hold(ctx.lock_path))
        except lock.LockBusyError:
            click.echo("A tick is running; sync starts when it ends.")
            stack.enter_context(lock.hold(ctx.lock_path, wait=True))
        if add:
            # Read again under the lock: another add may have written the map since this command opened it.
            add_repos(workspace.load(ctx.repo_root), add)
            ctx = dataclasses.replace(ctx, ws=workspace.load(ctx.repo_root))
        return _sync(ctx, dry_run=dry_run)


def check_synced(results: Sequence[setup_workspace.Checked]) -> None:
    """Refuse, exit 1, if any step did not reach what is declared."""
    unmet = sum(r.outcome in _UNMET for r in results)
    if unmet:
        raise CliError(f"{unmet} of {len(results)} steps did not reach what is declared; see above")


def _sync(ctx: Context, *, dry_run: bool) -> list[setup_workspace.Checked]:
    ws = ctx.workspace
    results: list[setup_workspace.Checked] = []
    if not ws.repos:
        click.echo(f"The map lists no repositories; add them under [repos.<name>] in {ws.map_file}.")
    for repo in ws.repos:
        results.append(_report(_clone_or_check(ctx, ws, repo, dry_run=dry_run)))
        # What git pushes to, after the operator's `insteadOf` and `pushInsteadOf` rewrites, not the map's URL (D038).
        if repo.cloned and (urls := init.ssh_push_urls(ctx.runner, repo.path)):
            click.echo(
                f"{repo.name}: warning: origin pushes over SSH ({', '.join(urls)}); canopy recommends HTTPS (D038)"
            )
        want = ctx.config.capacity.slots_for(repo.name)
        if want is not None and repo.cloned:
            results.append(
                _report(setup_workspace.converge_pool(ctx.runner, ctx.pool(repo.name), repo, want, dry_run=dry_run))
            )
        elif want is not None and dry_run:
            # Not cloned yet, so it has no pool: a real sync clones it, then makes every slot.
            results.append(_report(setup_workspace.Checked(repo, "slots", f"0 of {want}, would make {want}")))
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
    return setup_workspace.clone(ctx.runner, ws, repo)


def _report(checked: setup_workspace.Checked) -> setup_workspace.Checked:
    detail = f": {checked.detail}" if checked.detail else ""
    click.echo(f"{checked.repo.name}: {checked.outcome}{detail}")
    return checked
