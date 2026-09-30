"""`canopy init`, and `canopy skill` for the operator's own agent sessions."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from canopy.cli.common import Obj
from canopy.core import config, definitions, workspace
from canopy.infra import resources
from canopy.setup import init
from canopy.setup import workspace as setup_workspace


@click.command("init")
@click.option("--provider", help="Tracker provider for a new canopy.toml or workspace map (jira, github, linear, ...).")
@click.option(
    "--workspace",
    "as_workspace",
    is_flag=True,
    help="Set up this directory as a workspace of several repositories (canopy-workspace.toml). Implied inside one.",
)
@click.pass_context
def cmd_init(click_ctx: click.Context, provider: str | None, *, as_workspace: bool) -> int:
    """Set up canopy for this repository, or workspace, and this user."""
    workspace_root = workspace.find_root(Path.cwd())
    if as_workspace or workspace_root is not None:
        root = workspace_root or Path.cwd().resolve()
        provider = _provider(provider, root / config.WORKSPACE_FILE_NAME, "workspace")
        return _init_workspace(root, provider)
    repo_root = config.find_repo_root(Path.cwd())
    provider = _provider(provider, repo_root / config.REPO_FILE_NAME, "repository")

    user_file = config.user_config_path()
    report = init.run(repo_root, user_file, provider)
    _print_report(report, repo_root, user_file)
    obj = click_ctx.find_object(Obj)
    if obj is not None and (ssh_urls := init.ssh_push_urls(obj.runner, repo_root)):
        click.echo()
        click.echo(init.SSH_REMOTE_WARNING.format(urls=", ".join(ssh_urls)), nl=False)
    return 0


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


def _init_workspace(root: Path, provider: str | None) -> int:
    user_file = config.user_config_path()
    report = setup_workspace.run_init(root, user_file, provider)
    _print_files(report)
    if report.label is not None:
        click.echo(f"\nYour queue label is {report.label!r}. Add it to a ticket to hand the ticket to canopy.")
    if (root / config.WORKSPACE_FILE_NAME) in report.written:
        click.echo(
            f"Edit tracker.query and add each repository under [repos.<name>] in {root / config.WORKSPACE_FILE_NAME}, "
            f"describe them in {workspace.MAP_FILE_NAME}, then run `canopy workspace sync`."
        )
    try:
        ws = workspace.load(root)
        prefix = config.load(root, user_file).trust.branch_prefix
    except config.ConfigError as e:
        click.echo(f"\nThe config does not load yet; fix it before the first tick:\n{e}")
        return 0
    click.echo()
    click.echo(init.BRANCH_PROTECTION.format(prefix=prefix), nl=False)
    click.echo(setup_workspace.protection_targets(ws), nl=False)
    _print_shadowing(report)
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


def _print_report(report: init.Report, repo_root: Path, user_file: Path) -> None:
    for path in report.written:
        click.echo(f"wrote {path}")
    for path in report.kept:
        click.echo(f"kept  {path}")
    if report.label is not None:
        click.echo(f"\nYour queue label is {report.label!r}. Add it to a ticket to hand the ticket to canopy.")
    if (repo_root / config.REPO_FILE_NAME) in report.written:
        click.echo(f"Edit tracker.query in {repo_root / config.REPO_FILE_NAME} before the first tick.")
    try:
        prefix = config.load(repo_root, user_file).trust.branch_prefix
    except config.ConfigError as e:
        # Most often an existing user file from an earlier canopy whose templates lack {definitions_dir} (D040).
        click.echo(f"\nThe config does not load yet; fix it before the first tick:\n{e}")
        prefix = "agent/"
    click.echo()
    click.echo(init.BRANCH_PROTECTION.format(prefix=prefix), nl=False)
    _print_shadowing(report)
