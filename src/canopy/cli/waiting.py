"""`canopy waiting`: what waits on the operator, and what happened since a time, as one JSON object."""

from __future__ import annotations

import click
from pydantic import ValidationError

from canopy.cli.common import CliError, open_context
from canopy.loop import waiting


@click.command("waiting")
@click.option(
    "--since",
    metavar="TIME",
    help="What counts as new, an ISO 8601 time with its zone, such as 2026-11-13T09:00:00Z. Default: a day back.",
)
@click.pass_context
def cmd_waiting(click_ctx: click.Context, since: str | None) -> int:
    """Print what waits on you, and what happened since a time, as one JSON object.

    The attention list, each item marked new when it began since then; each open ticket's open PRs, with each
    reviewer's latest review and the feedback no plan has handled yet, by who wrote it; and the counts of ticks, runs,
    and spend since then. A briefing chore reads it through its tool of the same name; `canopy status` is the list
    for you to read.
    """
    try:
        request = waiting.Waiting(since=since)
    except ValidationError as e:
        raise CliError(f"--since: {e.errors()[0]['msg']}") from None
    ctx = open_context(click_ctx)
    click.echo(waiting.read_waiting(ctx, request))
    return 0
