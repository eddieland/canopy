"""`canopy workspace sync` and `add`: make the workspace match its map and the declared slots (DESIGN §18).

The commands for one pool's slots, `slots`, `release`, and `remove-slot`, are `cli.slots`'s.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final, assert_never

import click

from canopy.cli import slots
from canopy.cli.common import CliError, between_ticks, open_context, require_workspace
from canopy.core import pool, workspace
from canopy.core.vocab import PoolKind
from canopy.infra import lock
from canopy.setup import init
from canopy.setup import workspace as setup_workspace

if TYPE_CHECKING:
    from canopy.core.context import Context

#: What sync reports for a repository it could not bring to what is declared; any of them makes it exit 1.
_UNMET: Final = ("failed", "kept")


@click.group("workspace")
def workspace_group() -> None:
    """Manage a workspace of several repositories."""


workspace_group.add_command(slots.cmd_slots)
workspace_group.add_command(slots.cmd_release)
workspace_group.add_command(slots.cmd_remove_slot)


@workspace_group.command("sync")
@click.option("--dry-run", is_flag=True, help="Say what sync would clone, make, and remove, and change nothing.")
@click.option(
    "--seed",
    "seeds",
    metavar="NAME=PATH",
    multiple=True,
    help="Clone repository NAME taking what it can from the clone you already have at PATH, so only what that lacks "
    "is fetched; the clone made does not depend on it. Repeatable.",
)
@click.pass_context
def cmd_sync(click_ctx: click.Context, *, dry_run: bool, seeds: tuple[str, ...]) -> int:
    """Make the workspace match the map and the slots declared for its pools.

    Clones the map's repositories that have no clone, each from the clone --seed names for it, if any, and reports an
    origin that differs from the map. Fetches each
    clone already there, and fast-forwards its default branch when that is checked out, clean, and behind. With
    capacity.slots_per_repo or capacity.repo_slots set, makes or removes idle slots until each pool has its declared
    size. Removes a clone under repos/ that the map no longer lists, with its slots, when nothing in either would be
    lost. Prints each clone before it runs. Never changes an existing clone's remotes, and never moves a branch with
    local changes or commits. Waits for a running tick to end.
    """
    require_workspace()
    check_synced(sync(click_ctx, dry_run=dry_run, seeds=_seeds(seeds)))
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
    require_workspace()
    check_synced(sync(click_ctx, dry_run=False, add=repos))
    return 0


def add_repos(ws: workspace.Workspace, repos: Sequence[str]) -> None:
    """Add each `[NAME=]URL` in `repos` to the map, and print what was added. Nothing is written if one is refused.

    Raises:
        CliError: An argument's name or URL is not valid, or the map already has a repository by its name.
    """
    try:
        entries = [setup_workspace.repo_arg(arg) for arg in repos]
        added = setup_workspace.add(ws, entries)
    except ValueError as e:
        raise CliError(f"{e}; nothing was added to {ws.map_file}") from e
    for a in added:
        detail = f": {a.detail}" if a.detail else ""
        click.echo(f"{a.name}: {a.outcome}{detail}")


def sync(
    click_ctx: click.Context,
    *,
    dry_run: bool,
    add: Sequence[str] = (),
    seeds: Mapping[str, Path] | None = None,
) -> list[setup_workspace.Checked]:
    """Add the `[NAME=]URL`s in `add` to the map, then make the workspace match its map and declared slots.

    Both happen between ticks, under the tick lock, which also serializes two of these. A repository named in `seeds`
    is cloned taking what objects it can from the clone at its path.

    Returns:
        What each sync step found or did.

    Raises:
        CliError: `seeds` names a repository the map does not list.
    """
    ctx = open_context(click_ctx)
    with between_ticks(ctx, "sync"):
        if add:
            # Read again under the lock: another add may have written the map since this command opened it.
            add_repos(workspace.load(ctx.repo_root), add)
            ctx = dataclasses.replace(ctx, ws=workspace.load(ctx.repo_root))
        seeds = seeds or {}
        if unknown := sorted(set(seeds) - {r.name for r in ctx.workspace.repos}):
            raise CliError(f"sync: --seed names {', '.join(unknown)}, which the map does not list")
        return _sync(ctx, dry_run=dry_run, seeds=seeds)


def check_synced(results: Sequence[setup_workspace.Checked]) -> None:
    """Refuse, exit 1, if any step did not reach what is declared.

    Raises:
        CliError: A step ended `failed` or `kept`.
    """
    unmet = sum(r.outcome in _UNMET for r in results)
    if unmet:
        raise CliError(f"{unmet} of {len(results)} steps did not reach what is declared; see above")


def _seeds(args: Iterable[str]) -> dict[str, Path]:
    """Read each `NAME=PATH` of `--seed` into the clone it names, by repository.

    Returns:
        Each PATH made absolute, by NAME.

    Raises:
        CliError: an argument is not `NAME=PATH`, names one repository twice, or its PATH is not a directory.
    """
    found: dict[str, Path] = {}
    for arg in args:
        name, sep, path = arg.partition("=")
        if not sep or not name or not path:
            raise CliError(f"sync: --seed {arg!r} is not NAME=PATH")
        if name in found:
            raise CliError(f"sync: --seed names {name} twice")
        seed = Path(path).expanduser().absolute()
        if not seed.is_dir():
            raise CliError(f"sync: --seed {name}: {seed} is not a directory")
        found[name] = seed
    return found


def _sync(ctx: Context, *, dry_run: bool, seeds: Mapping[str, Path]) -> list[setup_workspace.Checked]:
    ws = ctx.workspace
    results: list[setup_workspace.Checked] = []
    if not ws.repos:
        click.echo(f"The map lists no repositories; add them under [repos.<name>] in {ws.map_file}.")
    for repo in ws.repos:
        checked = _report(_clone_or_check(ctx, ws, repo, dry_run=dry_run, seed=seeds.get(repo.name)))
        results.append(checked)
        if repo.cloned and not dry_run and (failed := setup_workspace.turn_off_auto_maintenance(ctx.runner, repo)):
            results.append(_report(failed))
        if checked.outcome == "present":
            results.append(_report(_fast_forward(ctx, repo, dry_run=dry_run)))
        # What git pushes to, after the operator's `insteadOf` and `pushInsteadOf` rewrites, not the map's URL. Only a
        # warning, refusing nothing: HTTPS is recommended because a sandboxed worker cannot reach the SSH agent socket.
        if repo.cloned and (urls := init.ssh_push_urls(ctx.runner, repo.path)):
            click.echo(f"{repo.name}: warning: origin pushes over SSH ({', '.join(urls)}); canopy recommends HTTPS")
        switched = _switch(ctx, repo, dry_run=dry_run) if repo.cloned else None
        if switched is not None:
            results.append(_report(switched))
        want = ctx.config.capacity.slots_for(repo.name)
        if want is not None and repo.cloned:
            incoming = _incoming(ctx, repo, dry_run=dry_run)
            converged = setup_workspace.converge_pool(
                ctx.pool(repo.name),
                repo,
                want,
                dry_run=dry_run,
                incoming=incoming,
            )
            results.append(_report(converged))
        elif want is not None and dry_run:
            # Not cloned yet, so it has no pool: a real sync clones it, then makes every slot.
            results.append(_report(setup_workspace.Checked(repo, "slots", f"0 of {want}, would make {want}")))
    results += [
        _report(setup_workspace.remove(ctx.runner, ctx.pool(r.name), r, dry_run=dry_run))
        for r in setup_workspace.undeclared(ws)
    ]
    return results


def _fast_forward(ctx: Context, repo: workspace.Repo, *, dry_run: bool) -> setup_workspace.Checked:
    """Fetch `repo`'s clone and fast-forward its default branch, under the dispatch lock a lease's fetch takes.

    Returns:
        What it came to, or what it would do in a dry run, which fetches nothing.
    """
    if dry_run:
        detail = "would fetch origin, and fast-forward the default branch if it is checked out and clean"
        return setup_workspace.Checked(repo, "to fetch", detail)
    with lock.hold(ctx.dispatch_lock_path, wait=True):
        return setup_workspace.fast_forward(ctx.runner, repo)


def _switch(ctx: Context, repo: workspace.Repo, *, dry_run: bool) -> setup_workspace.Checked | None:
    """Bring `repo`'s slots over from the pool `pools.backend` does not name, if it has any (DESIGN §18).

    Returns:
        What moving or removing them came to, or None when there was nothing to do.
    """
    match ctx.config.pools.backend:
        case PoolKind.CANOPY:
            if not (ctx.repo_root / workspace.POOLS_DIR).is_dir():
                return None
            source = ctx.pool_of(PoolKind.TREEHOUSE, repo.name)
            return setup_workspace.move_slots(source, ctx.canopy_pool(repo.name), repo, dry_run=dry_run)
        case PoolKind.TREEHOUSE:
            if not (ctx.repo_root / pool.POOLS_DIR / repo.name).is_dir():
                return None
            return setup_workspace.drop_idle(ctx.canopy_pool(repo.name), repo, dry_run=dry_run)
        case unknown:
            assert_never(unknown)


def _incoming(ctx: Context, repo: workspace.Repo, *, dry_run: bool) -> setup_workspace.Incoming:
    """Count the slots of treehouse's pool that canopy's is to count as its own, after `_switch` (DESIGN §18).

    Returns:
        The slots moving in now, in a dry run, and those waiting for a later sync; none unless `pools.backend` names
        canopy's pool and the workspace still has treehouse's.
    """
    if ctx.config.pools.backend is not PoolKind.CANOPY or not (ctx.repo_root / workspace.POOLS_DIR).is_dir():
        return setup_workspace.Incoming()
    return setup_workspace.incoming(ctx.pool_of(PoolKind.TREEHOUSE, repo.name), dry_run=dry_run)


def _clone_or_check(
    ctx: Context,
    ws: workspace.Workspace,
    repo: workspace.Repo,
    *,
    dry_run: bool,
    seed: Path | None,
) -> setup_workspace.Checked:
    if repo.cloned:
        if seed is not None:
            click.echo(f"{repo.name}: --seed not used: it is cloned already")
        return setup_workspace.check_origin(ctx.runner, repo)
    url = setup_workspace.shown(str(repo.url))
    seeded = f", seeded from {seed}" if seed is not None else ""
    if dry_run:
        return setup_workspace.Checked(repo, "to clone", f"{url} into {repo.path}{seeded}")
    click.echo(f"{repo.name}: cloning {url} into {repo.path}{seeded}")
    return setup_workspace.clone(ctx.runner, ws, repo, seed=seed)


def _report(checked: setup_workspace.Checked) -> setup_workspace.Checked:
    detail = f": {checked.detail}" if checked.detail else ""
    click.echo(f"{checked.repo.name}: {checked.outcome}{detail}")
    return checked
