"""`canopy workspace sync`: clone the map's missing repositories and check the others' `origin` (DESIGN §18)."""

from __future__ import annotations

from pathlib import Path

import click

from canopy.cli.common import CliError, Obj
from canopy.core import config, workspace
from canopy.setup import init
from canopy.setup import workspace as setup_workspace


@click.group("workspace")
def workspace_group() -> None:
    """Manage a workspace of several repositories."""


@workspace_group.command("sync")
@click.pass_context
def cmd_sync(click_ctx: click.Context) -> int:
    """Clone the map's repositories that have no clone, and report an origin that differs from the map.

    Prints each clone before it runs. Never changes an existing clone or its remotes.
    """
    obj = click_ctx.find_object(Obj)
    if obj is None:
        raise RuntimeError("canopy commands run through canopy.cli.main")
    root = workspace.find_root(Path.cwd())
    if root is None:
        raise CliError(f"no {config.WORKSPACE_FILE_NAME} here or above; run `canopy init --workspace` first")
    ws = workspace.load(root)
    if not ws.repos:
        click.echo(f"The map lists no repositories; add them under [repos.<name>] in {ws.map_file}.")
        return 0

    failed = 0
    for repo in ws.repos:
        if repo.cloned:
            checked = setup_workspace.check_origin(obj.runner, repo)
        else:
            url = setup_workspace.shown(str(repo.url))
            click.echo(f"{repo.name}: cloning {url} into {repo.path}")
            if repo.url is not None and init.is_ssh_url(repo.url):
                click.echo(f"{repo.name}: warning: {url} is reached over SSH; canopy recommends HTTPS (D038)")
            checked = setup_workspace.clone(obj.runner, ws, repo)
        failed += checked.outcome == "failed"
        detail = f": {checked.detail}" if checked.detail else ""
        click.echo(f"{repo.name}: {checked.outcome}{detail}")
    if failed:
        raise CliError(f"{failed} of {len(ws.repos)} repositories failed; see above")
    return 0
