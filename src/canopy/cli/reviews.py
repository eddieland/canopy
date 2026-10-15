"""`canopy review run` and `wait` for the overseer, `show` for the operator, and the detached `_review` (DESIGN §21)."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime

import click

from canopy.cli.common import CliError, open_context, require_tick
from canopy.cli.params import PR_URL, REPO, TICKET_KEY, TextType, truncate
from canopy.core import db
from canopy.infra import logs
from canopy.loop import attention, tick
from canopy.reviews import execute, findings, grants, start, view


@click.group("review")
def review_group() -> None:
    """Review PRs: `run` and `wait` are the overseer's; `show` is how you read what canopy's reviews found."""


@review_group.command("run")
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
    ctx = open_context(click_ctx)
    current = require_tick(ctx)
    tick_id = int(current["id"])
    log = logs.for_tick(tick_id)
    request = start.Request(pr=pr, sha=sha, ticket=ticket, repo=repo)
    # A malformed URL is recorded cut short; the refusal says what was wrong with it.
    pr_key = pr if len(pr) <= start.MAX_PR_URL else pr[: start.MAX_PR_URL]
    try:
        if current["dry_run"]:
            start.check(ctx, tick_id=tick_id, request=request)
            started = None
        else:
            started = start.start(ctx, tick_id=tick_id, request=request, context=context)
    except start.Refusal as r:
        db.record_decision(ctx.conn, tick_id, ticket, f"refused:{r.guard}", r.reason, pr=pr_key)
        if r.guard == "review_limit":
            # The overseer wants a review the limit forbids: a human has to look (DESIGN §21).
            action = f"{attention.ACTION_PREFIX}review_limit"
            db.record_decision(ctx.conn, tick_id, ticket, action, f"{r.reason}; {grants.hint(pr_key)}", pr=pr_key)
        log.info("review refused", extra={"pr": pr_key, "guard": r.guard, "reason": r.reason})
        raise CliError(f"review refused ({r.guard}): {r.reason}; the refusal was recorded") from None
    on_context = f"; context={context}" if context else ""
    if started is None:
        rationale = truncate(f"dry run: not dispatched; would review {sha}{on_context}")
        db.record_decision(ctx.conn, tick_id, ticket, start.DISPATCH_ACTION, rationale, pr=pr)
        click.echo(f"dry run: recorded review of {pr}; nothing was started")
        return 0
    rationale = truncate(f"review run {started.run_id}: {sha} in {started.slot}{on_context}")
    db.record_decision(ctx.conn, tick_id, ticket, start.DISPATCH_ACTION, rationale, pr=pr)
    log.info("review started", extra={"pr": pr, "review_run_id": started.run_id, "pid": started.pid})
    click.echo(f"started review of {pr}: run {started.run_id}")
    return 0


@review_group.command("wait")
@click.option("--pr", "pr", required=True, type=PR_URL, help="The PR's https:// URL.")
@click.option("--ticket", type=TICKET_KEY, help="The ticket of one of the loop's own PRs.")
@click.option("--rationale", required=True, type=TextType())
@click.pass_context
def cmd_review_wait(click_ctx: click.Context, *, pr: str, ticket: str | None, rationale: str) -> int:
    """Record that the PR at URL is not to be reviewed now, and why."""
    ctx = open_context(click_ctx)
    current = require_tick(ctx)
    if not ctx.config.reviews_on:
        raise CliError("reviews are off in this configuration")
    db.record_decision(ctx.conn, int(current["id"]), ticket, "wait", rationale, pr=pr)
    click.echo(f"recorded wait for {pr}")
    return 0


@review_group.command("show")
@click.argument("run_id", type=click.IntRange(min=1), required=False)
@click.pass_context
def cmd_review_show(click_ctx: click.Context, run_id: int | None) -> int:
    """List the last 14 days' reviews, newest first, or show review run RUN_ID in full.

    canopy's reviews post nothing on the PR; this, and the state block, are where they are.
    """
    ctx = open_context(click_ctx)
    if run_id is not None:
        try:
            click.echo(findings.described(ctx.conn, run_id))
        except findings.Unusable as e:
            raise CliError(str(e)) from None
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
