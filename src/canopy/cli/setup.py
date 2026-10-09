"""`canopy init`, `canopy skill` for the operator's own agent sessions, and `canopy secret` for the web UI."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from canopy.cli import workspace as cli_workspace
from canopy.cli.common import CliError
from canopy.core import config, conversation, definitions, workspace
from canopy.infra import resources
from canopy.serve import secret
from canopy.setup import init
from canopy.setup import workspace as setup_workspace


@click.command("init")
@click.option("--provider", help="Tracker provider for a new workspace map (jira, github, linear, ...).")
@click.option(
    "--workspace",
    "in_checkout",
    is_flag=True,
    help="Make this directory a workspace even though it is inside a git repository, such as one that holds only "
    "the workspace's own files.",
)
@click.argument("repos", metavar="[[NAME=]URL]...", nargs=-1)
@click.pass_context
def cmd_init(click_ctx: click.Context, provider: str | None, repos: tuple[str, ...], *, in_checkout: bool) -> int:
    """Set up a workspace in this directory, and your user config.

    canopy runs from a workspace, even for one repository: a directory of its own, ideally empty, where it clones each
    repository and keeps their worktree pools and its journal. Clone URLs add those repositories to the map and sync:
    each is cloned, and its pool made the size your user config declares. A repository is named after its URL, unless
    given as NAME=URL. Run inside a workspace, init fills in what it is missing.
    """
    root = workspace.find_root(Path.cwd())
    if root is None:
        root = Path.cwd().resolve()
        checkout = _git_root(root)
        if checkout is not None and not in_checkout:
            raise click.UsageError(
                f"{root} is inside the git repository {checkout}. canopy runs from a workspace of its own and writes "
                f"nothing into a code repository: run `canopy init` in an empty directory, with the repository's clone "
                f"URL. Pass --workspace to make this directory a workspace anyway."
            )
    provider = _provider(provider, root / config.WORKSPACE_FILE_NAME, "workspace")
    return _init_workspace(click_ctx, root, provider, repos)


def _git_root(start: Path) -> Path | None:
    """The nearest directory at or above `start` holding `.git`, a directory or a worktree's file, or None."""
    return next((d for d in (start, *start.parents) if (d / ".git").exists()), None)


def _provider(provider: str | None, shared_file: Path, what: str) -> str | None:
    """Return the tracker provider for a new shared file, asking for it on a terminal. None if the file exists."""
    if provider is None and not shared_file.exists():
        if not sys.stdin.isatty():
            raise click.UsageError(f"the {what} has no {shared_file.name}; pass --provider (jira, github, linear, ...)")
        answer: str = click.prompt(f"Tracker provider for this {what} (jira, github, linear, ...)")
        provider = answer.strip().lower()
    if provider is not None and not init.valid_provider(provider):
        raise click.UsageError(f"invalid provider {provider!r}: use a short lowercase name such as jira or github")
    return provider


def _init_workspace(click_ctx: click.Context, root: Path, provider: str | None, repos: tuple[str, ...]) -> int:
    user_file = config.user_config_path()
    report = setup_workspace.run_init(root, user_file, provider)
    _print_files(report)
    if report.label is not None:
        click.echo(f"\nYour queue label is {report.label!r}. Add it to a ticket to hand the ticket to canopy.")
    map_file = root / config.WORKSPACE_FILE_NAME
    if map_file in report.written and not repos:
        click.echo(
            f"Edit tracker.query and add each repository under [repos.<name>] in {map_file}, describe them in "
            f"{workspace.MAP_FILE_NAME}, then run `canopy workspace sync`. Or pass clone URLs to "
            f"`canopy workspace add`, which adds and syncs them."
        )
    try:
        ws = workspace.load(root)
        prefix = config.load(root, user_file).trust.branch_prefix
    except config.ConfigError as e:
        click.echo(f"\nThe config does not load yet; fix it before the first tick:\n{e}")
        if repos:
            raise CliError("nothing was added or synced; fix the config, then run `canopy workspace add`") from e
        return 0
    synced: list[setup_workspace.Checked] = []
    if repos:
        click.echo()
        synced = cli_workspace.sync(click_ctx, dry_run=False, add=repos)
        ws = workspace.load(root)
        click.echo(
            f"\nWrite a one-line summary for each repository in {map_file}, and describe them in "
            f"{workspace.MAP_FILE_NAME}: the overseer reads both to choose repositories. Edit tracker.query too."
        )
    click.echo()
    click.echo(init.BRANCH_PROTECTION.format(prefix=prefix), nl=False)
    click.echo(setup_workspace.protection_targets(ws), nl=False)
    _print_shadowing(report)
    cli_workspace.check_synced(synced)
    return 0


def _print_files(report: init.Report) -> None:
    for path in report.written:
        click.echo(f"wrote   {path}")
    for path in report.updated:
        click.echo(f"updated {path}")
    for path in report.kept:
        click.echo(f"kept    {path}")


def _print_shadowing(report: init.Report) -> None:
    if report.shadowing:
        click.echo()
        click.echo(f"Warning: {definitions.shadowing_message(report.shadowing)}")
        click.echo(
            "  Earlier versions of `canopy init` put them there. Agent runs refuse to start until they are gone."
        )


@click.command("skill")
def cmd_skill() -> int:
    """Print the canopy skill for your own agent sessions.

    Save it where your agent runtime reads skills, and again after upgrading canopy:

    \b
        mkdir -p ~/.agents/skills/canopy
        canopy skill > ~/.agents/skills/canopy/SKILL.md
    """  # noqa: D301  (\b is click's marker for a paragraph it must not rewrap)
    click.echo(resources.operator_skill().read_text(encoding="utf-8"), nl=False)
    return 0


@click.command("secret")
@click.option("--rotate", is_flag=True, help="Replace the secret with a new one, signing every browser out.")
def cmd_secret(*, rotate: bool) -> int:
    """Print the listener secret the web UI's sign-in asks for, making one first if there is none.

    It is kept in a file only you can read, next to your user config. `canopy loop` reads it when it starts serving;
    restart the loop after --rotate.
    """
    try:
        conversation.check_operator()
    except conversation.Refused as r:
        raise CliError(f"secret refused ({r.guard}): {r.reason}") from None
    path = secret.path()
    try:
        value, written = secret.create(path, rotate=rotate)
    except secret.SecretError as e:
        raise CliError(str(e)) from None
    click.echo(f"{'wrote' if written else 'kept '} {path}", err=True)
    if written and rotate:
        click.echo("Every browser is signed out once the loop restarts.", err=True)
    click.echo(value)
    return 0
