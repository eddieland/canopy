"""`canopy review run`, `wait`, and `end` for the overseer, `show` for the operator, the detached `_review` (§21)."""

from __future__ import annotations

import contextlib
import os
import sys
from datetime import UTC, datetime

import click

from canopy.cli.common import CliError, Group, OverseerCommand, open_context
from canopy.cli.params import PR_URL, REPO, TICKET_KEY, TextType, verb
from canopy.core import conversation, db, review_requests
from canopy.loop import tick, tools
from canopy.reviews import execute, findings, view

#: The channel `show` marks a review seen through (DESIGN §22).
CLI = "cli"


@click.group("review", cls=Group)
def review_group() -> None:
    """Review PRs: `run`, `wait`, and `end` are the overseer's; `show` is how you read what canopy's reviews found."""


@review_group.command("run", cls=OverseerCommand)
@click.option("--pr", "pr", required=True, metavar="URL", help="The PR's https:// URL, as an opaque string.")
@click.option("--sha", required=True, metavar="SHA", help="The full head commit you read on the PR just now.")
@click.option("--ticket", type=TICKET_KEY, help="The ticket of one of the loop's own PRs.")
@click.option("--repo", type=REPO, help="The PR's repository, by its name in the map. Required.")
@click.option("--context", type=TextType(), help="What the reviewer should look at first. Never quoted text.")
@click.pass_context
def cmd_review_run(
    click_ctx: click.Context, *, pr: str, sha: str, ticket: str | None, repo: str | None, context: str | None
) -> int:
    """Start a review of the PR at URL, at commit SHA, if its guards allow one now."""
    return verb(click_ctx, tools.review_run, tools.ReviewRun, pr=pr, sha=sha, ticket=ticket, repo=repo, context=context)


@review_group.command("wait", cls=OverseerCommand)
@click.option("--pr", "pr", required=True, type=PR_URL, help="The PR's https:// URL.")
@click.option("--ticket", type=TICKET_KEY, help="The ticket of one of the loop's own PRs.")
@click.option(
    "--rationale", required=True, type=TextType(), help="Why not now, such as checks still running, or a draft."
)
@click.pass_context
def cmd_review_wait(click_ctx: click.Context, *, pr: str, ticket: str | None, rationale: str) -> int:
    """Record that the PR at URL is not to be reviewed now, and why."""
    return verb(click_ctx, tools.review_wait, tools.ReviewWait, pr=pr, ticket=ticket, rationale=rationale)


@review_group.command("end", cls=OverseerCommand)
@click.option("--pr", "pr", required=True, type=PR_URL, help="The requested PR's https:// URL.")
@click.option("--reason", required=True, type=click.Choice(review_requests.OVERSEER_REASONS), help="What you read.")
@click.pass_context
def cmd_review_end(click_ctx: click.Context, *, pr: str, reason: str) -> int:
    """End the operator's review request on the PR at URL: it merged or closed first, or is in no repository here."""
    return verb(click_ctx, tools.review_end, tools.ReviewEnd, pr=pr, reason=reason)


@review_group.command("show")
@click.argument("run_id", type=click.IntRange(min=1), required=False)
@click.pass_context
def cmd_review_show(click_ctx: click.Context, run_id: int | None) -> int:
    """List the last 14 days' reviews, newest first, or show review run RUN_ID in full.

    canopy's reviews post nothing on the PR; this, and the state block, are where they are. A review whose result you
    have not seen ends its line with `new`; showing it in full marks it seen, as its page in the web UI does.
    """
    ctx = open_context(click_ctx)
    if run_id is not None:
        try:
            click.echo(findings.described(ctx.conn, run_id))
        except findings.Unusable as e:
            raise CliError(str(e)) from None
        # Seen once shown to the operator. Inside one of canopy's own runs it marks nothing, and a review still running
        # has no result to see yet: either refusal leaves it as it was, and the show stands.
        with contextlib.suppress(conversation.Refused):
            conversation.check_operator()
            conversation.see(ctx.conn, [conversation.Ref(conversation.REVIEW, str(run_id))], channel=CLI)
        return 0
    lines = findings.listed(ctx.conn, db.format_time(datetime.now(UTC) - view.RECENT))
    click.echo("\n".join(lines) if lines else "no reviews in the last 14 days")
    return 0


@click.command("_review", hidden=True)
@click.argument("run_id", type=click.IntRange(min=1))
@click.pass_context
def cmd_review_process(click_ctx: click.Context, run_id: int) -> int:
    """Do one review run. Started by `canopy review run`, detached; not for people or agents."""
    # The reviewer must not be able to act as the overseer of the tick that started it (D020).
    os.environ.pop(tick.TICK_ID_ENV, None)
    ctx = open_context(click_ctx)
    try:
        outcome = execute.execute(ctx, run_id, out=sys.stdout)
    except execute.ReviewError as e:
        raise CliError(str(e)) from None
    click.echo(f"review run {run_id}: {outcome.status}")
    return 0
