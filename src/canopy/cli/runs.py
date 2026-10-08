"""`canopy dispatch`, and the detached `canopy _run` it starts."""

from __future__ import annotations

import os
import sys

import click

from canopy.cli.common import CliError, open_context, require_tick
from canopy.cli.params import COMMENT_ID, REPO, SLUG, SUBJECT_KEY, CursorType, TextType, truncate
from canopy.core import db
from canopy.infra import logs
from canopy.loop import attention, tick
from canopy.runs import dispatch, policy, worker


@click.command("dispatch")
@click.argument("key", type=SUBJECT_KEY)
@click.option("--kind", required=True, type=click.Choice(policy.DISPATCH_KINDS))
@click.option(
    "--label",
    metavar="LABEL",
    help="The configured queue label you read on the ticket just now. Required for a public ticket: without one of "
    "tracker.labels the dispatch is refused as unauthorized. A ticket the operator started needs none.",
)
@click.option(
    "--repo",
    "repos",
    type=REPO,
    multiple=True,
    help="A repository in the workspace the run works in: one unit of the ticket. Repeat it for a joint run over "
    "several. Required in a workspace; optional in a single repository.",
)
@click.option(
    "--slug",
    type=SLUG,
    help=f"implement only: short name for the work, from the ticket title; the branch is <prefix><KEY>-<slug>. "
    f"Default {dispatch.DEFAULT_SLUG!r}. The ticket's first implement names it; later dispatches continue it.",
)
@click.option(
    "--base",
    metavar="BRANCH",
    help="Stack on another ticket's branch, <prefix><KEY>-<slug>, whose PR is open and green: start from it and target "
    "the PR at it. Default: the repository's base branch.",
)
@click.option(
    "--branch",
    metavar="BRANCH",
    help="A PR only (KEY is REPO#N), and required for it: the PR's head branch, read on the PR just now. The worker "
    "continues it and pushes only to it.",
)
@click.option(
    "--request",
    type=COMMENT_ID,
    metavar="COMMENT_ID",
    help="split only, and required for it: the authorized replier's comment on the ticket that asked for the split.",
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
    help="Advance a cursor, only if the worker starts: what this dispatch handles. A review or ci cursor is its "
    "unit's, so the dispatch names one repository.",
)
@click.pass_context
def cmd_dispatch(
    click_ctx: click.Context,
    *,
    key: str,
    kind: str,
    label: str | None,
    repos: tuple[str, ...],
    slug: str | None,
    base: str | None,
    branch: str | None,
    request: str | None,
    context: str | None,
    cursor_pairs: tuple[tuple[str, str], ...],
) -> int:
    """Start a worker on a ticket, or on the operator's own PR, REPO#N (overseer only)."""
    ctx = open_context(click_ctx)
    unit_cursors = [name for name, _ in cursor_pairs if name in db.UNIT_CURSORS]
    if unit_cursors and len(set(repos)) > 1:
        raise click.UsageError(
            f"a {unit_cursors[0]} cursor belongs to one unit: advance it with `canopy ticket set {key} --repo NAME`",
            click_ctx,
        )
    current = require_tick(ctx)
    tick_id = int(current["id"])
    log = logs.for_tick(tick_id)
    db.touch_ticket(ctx.conn, key, ctx.repo)
    dry_run = bool(current["dry_run"])
    try:
        # A dry run checks the same guards, so its plan holds the refusals a live tick would get (D036).
        if dry_run:
            plan = dispatch.check(
                ctx,
                tick_id=tick_id,
                key=key,
                kind=kind,
                label=label,
                slug=slug,
                base=base,
                repos=repos,
                request=request,
                branch=branch,
            )
            branch, queue_label, repo_names = plan.branch, plan.label, plan.repos
            started = None
        else:
            started = dispatch.start(
                ctx,
                tick_id=tick_id,
                key=key,
                kind=kind,
                label=label,
                slug=slug,
                base=base,
                context=context,
                repos=repos,
                request=request,
                branch=branch,
            )
            branch, queue_label, repo_names = started.branch, started.label, started.repos
    except dispatch.Refusal as r:
        db.record_decision(ctx.conn, tick_id, key, f"refused:{r.guard}", r.reason)
        if r.guard == "attempt_limit":
            # The overseer wants work the limit forbids: a human has to look (DESIGN §14). In a workspace of several,
            # the item is about the unit at its limit.
            db.record_decision(ctx.conn, tick_id, key, f"{attention.ACTION_PREFIX}attempt_limit", r.reason, repo=r.repo)
        log.info("dispatch refused", extra={"ticket": key, "kind": kind, "guard": r.guard, "reason": r.reason})
        raise CliError(f"dispatch refused ({r.guard}): {r.reason}; the refusal was recorded") from None
    # `base` passed the guards, so it is the branch this run is stacked on. `queue_label` is the configured spelling, or
    # empty for a private ticket, which its start record authorizes (DESIGN §22).
    authorized = f"label {queue_label}" if queue_label else "private: started by the operator"
    on_base = f" on {base}" if base is not None else ""
    # A workspace of one has one repository, so naming it would say nothing.
    in_repo = "" if ctx.workspace.single else f" in {', '.join(repo_names)}"
    # A split works on no branch: it reads its repositories and creates a ticket for each.
    work = f"split {key} into {', '.join(repo_names)}" if kind == policy.SPLIT else f"{branch}{on_base}"
    requested = f"; request {request}" if request is not None else ""
    if started is None:
        extras = [
            *(f"cursor {name}={value}" for name, value in cursor_pairs),
            f"context={context}" if context else "",
        ]
        rationale = truncate(
            "; ".join(
                e
                for e in [
                    (
                        f"dry run: not dispatched; would {work}"
                        if kind == policy.SPLIT
                        else f"dry run: not dispatched; would work on {work}{in_repo}"
                    ),
                    authorized,
                    f"request {request}" if request is not None else "",
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
    ticket_cursors = {name: value for name, value in cursor_pairs if name in db.TICKET_CURSORS}
    db.set_ticket(ctx.conn, key, ctx.repo, cursors=ticket_cursors)
    if unit_cursors:
        cursors = {name: value for name, value in cursor_pairs if name in db.UNIT_CURSORS}
        db.set_unit(ctx.conn, key, ctx.repo, repo_names[0], single=ctx.workspace.single, cursors=cursors)
    if in_repo:
        where = " in " + ", ".join(f"{s.repo} at {s.slot_path}" for s in started.slots)
        where += f"; desk {started.desk}" if started.desk is not None else ""
    else:
        where = f" in {started.slots[0].slot_path}"
    rationale = f"run {started.run_id}: {work}{where}; {authorized}{requested}"
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
