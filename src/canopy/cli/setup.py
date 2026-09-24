"""`canopy init`."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from canopy.cli.common import Obj
from canopy.core import config
from canopy.setup import init


@click.command("init")
@click.option("--provider", help="Tracker provider for a new canopy.toml (jira, github, linear, ...).")
@click.pass_context
def cmd_init(click_ctx: click.Context, provider: str | None) -> int:
    """Set up canopy for this repository and this user."""
    repo_root = config.find_repo_root(Path.cwd())
    if provider is None and not (repo_root / config.REPO_FILE_NAME).exists():
        if not sys.stdin.isatty():
            raise click.UsageError("the repository has no canopy.toml; pass --provider (jira, github, linear, ...)")
        answer: str = click.prompt("Tracker provider for this repository (jira, github, linear, ...)")
        provider = answer.strip().lower()
    if provider is not None and not init.valid_provider(provider):
        raise click.UsageError(f"invalid provider {provider!r}: use a short lowercase name such as jira or github")

    user_file = config.user_config_path()
    report = init.run(repo_root, user_file, provider)
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
    except config.ConfigError:
        prefix = "agent/"
    click.echo()
    click.echo(init.BRANCH_PROTECTION.format(prefix=prefix), nl=False)
    obj = click_ctx.find_object(Obj)
    if obj is not None and (ssh_urls := init.ssh_push_urls(obj.runner, repo_root)):
        click.echo()
        click.echo(init.SSH_REMOTE_WARNING.format(urls=", ".join(ssh_urls)), nl=False)
    return 0
