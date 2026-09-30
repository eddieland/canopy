"""`canopy dispatch`, and the detached `canopy _run` it starts."""

from __future__ import annotations

import os
import sys

import click

from canopy.cli.common import CliError, open_context, require_tick
from canopy.cli.params import REPO, SLUG, TICKET_KEY, CursorType, TextType, truncate
from canopy.core import db
from canopy.infra import logs
from canopy.loop import attention, tick
from canopy.runs import dispatch, policy, worker


@click.command("dispatch")
@click.argument("key", type=TICKET_KEY)
@click.option("--kind", required=True, type=click.Choice(policy.KINDS))
@click.option(
    "--label",
    metavar="LABEL",
    help="The configured queue label you read on the ticket just now. Required: without one of tracker.labels the "
    "dispatch is refused as unauthorized.",
)
@click.option(
    "--repo",
    type=REPO,
    help="The repository in the workspace the work is in. Required in a workspace; a ticket stays in the repository of "
    "its first dispatch. Optional in a single repository.",
)
@click.option(
    "--slug",
    type=SLUG,
    help=f"implement only: short name for the work, from the ticket title; the branch is <prefix><KEY>-<slug>. "
    f"Default {dispatch.DEFAULT_SLUG!r}. fix-ci and resume continue the ticket's recorded branch.",
)
@click.option(
    "--base",
    metavar="BRANCH",
    help="Stack on another ticket's branch, <prefix><KEY>-<slug>, whose PR is open and green: start from it and target "
    "the PR at it. Default: the repository's base branch.",
)
@click.option(
    "--context",
    type=TextType(),
    help="What the worker should read or do: links, comment ids, check names. Never quoted ticket or PR text.",
)
@click.option(
    "--cursor",
    "cursor_pairs",
    type=CursorType(),
    multiple=True,
    help="Advance a cursor, only if the worker starts: what this dispatch handles.",
)
@click.pass_context
def cmd_dispatch(
    click_ctx: click.Context,
    *,
    key: str,
    kind: str,
    label: str | None,
    repo: str | None,
    slug: str | None,
    base: str | None,
    context: str | None,
    cursor_pairs: tuple[tuple[str, str], ...],
) -> int:
    """Start a worker on a ticket (overseer only)."""
    ctx = open_context(click_ctx)
    current = require_tick(ctx)
    tick_id = int(current["id"])
    log = logs.for_tick(tick_id)
    db.touch_ticket(ctx.conn, key, ctx.repo)
    dry_run = bool(current["dry_run"])
    try:
        # A dry run checks the same guards, so its plan holds the refusals a live tick would get (D036).
        if dry_run:
            plan = dispatch.check(
                ctx, tick_id=tick_id, key=key, kind=kind, label=label, slug=slug, base=base, repo=repo
            )
            branch, queue_label, repo_name = plan.branch, plan.label, plan.repo
            started = None
        else:
            started = dispatch.start(
                ctx, tick_id=tick_id, key=key, kind=kind, label=label, slug=slug, base=base, context=context, repo=repo
            )
            branch, queue_label, repo_name = started.branch, started.label, started.repo
    except dispatch.Refusal as r:
        db.record_decision(ctx.conn, tick_id, key, f"refused:{r.guard}", r.reason)
        if r.guard == "attempt_limit":
            # The overseer wants work the limit forbids: a human has to look (DESIGN §14).
            db.record_decision(ctx.conn, tick_id, key, f"{attention.ACTION_PREFIX}attempt_limit", r.reason)
        log.info("dispatch refused", extra={"ticket": key, "kind": kind, "guard": r.guard, "reason": r.reason})
        raise CliError(f"dispatch refused ({r.guard}): {r.reason}; the refusal was recorded") from None
    # `base` passed the guards, so it is the branch this run is stacked on. `queue_label` is the configured spelling.
    on_base = f" on {base}" if base is not None else ""
    # A workspace of one has one repository, so naming it would say nothing.
    in_repo = "" if ctx.workspace.single else f" in {repo_name}"
    if started is None:
        extras = [
            *(f"cursor {name}={value}" for name, value in cursor_pairs),
            f"context={context}" if context else "",
        ]
        rationale = truncate(
            "; ".join(
                e
                for e in [
                    f"dry run: not dispatched; would work on {branch}{on_base}{in_repo}",
                    f"label {queue_label}",
                    *extras,
                ]
                if e
            )
        )
        db.record_decision(ctx.conn, tick_id, key, f"dispatch:{kind}", rationale)
        log.info("dry-run dispatch recorded", extra={"ticket": key, "kind": kind})
        click.echo(f"dry run: recorded dispatch {kind} for {key}; nothing was started")
        return 0
    # Cursors advance only now, so what a refused dispatch was meant to handle is still new next tick.
    db.set_ticket(ctx.conn, key, ctx.repo, cursors=dict(cursor_pairs))
    where = f"{in_repo} at {started.slot}" if in_repo else f" in {started.slot}"
    rationale = f"run {started.run_id}: {branch}{on_base}{where}; label {queue_label}"
    db.record_decision(ctx.conn, tick_id, key, f"dispatch:{kind}", rationale)
    log.info("dispatched", extra={"ticket": key, "kind": kind, "run_id": started.run_id, "pid": started.pid})
    click.echo(f"dispatched {kind} for {key}: {rationale}")
    return 0


@click.command("_run", hidden=True)
@click.argument("run_id", type=click.IntRange(min=1))
@click.pass_context
def cmd_run(click_ctx: click.Context, run_id: int) -> int:
    """Do one dispatched run. Started by `canopy dispatch`, detached; not for people or agents."""
    # The worker must not be able to act as the overseer of the tick that dispatched it (D020).
    os.environ.pop(tick.TICK_ID_ENV, None)
    ctx = open_context(click_ctx)
    try:
        outcome = worker.execute(ctx, run_id, out=sys.stdout)
    except worker.WorkerError as e:
        raise CliError(str(e)) from None
    click.echo(f"run {run_id}: {outcome.status}")
    return 0
