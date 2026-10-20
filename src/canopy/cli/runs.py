"""`canopy dispatch`, and the detached `canopy _run` it starts."""

from __future__ import annotations

import os
import sys

import click

from canopy.cli.common import CliError, OverseerCommand, open_context
from canopy.cli.params import REPO, SLUG, TICKET_KEY, CursorType, TextType, verb
from canopy.core.vocab import ResumeReason
from canopy.loop import tick, tools
from canopy.runs import dispatch, policy, worker


@click.command("dispatch", cls=OverseerCommand)
@click.argument("key", type=TICKET_KEY)
# `fix-ci` and `split` are taken only to be refused naming what replaced them, a refusal the decisions record.
@click.option(
    "--kind",
    required=True,
    type=click.Choice([*(str(k) for k in policy.DISPATCH_KINDS), str(policy.RETIRED), str(policy.SPLIT)]),
    help="What the worker does.",
)
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
    "several. Required.",
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
    "--review-run",
    type=click.IntRange(min=1),
    metavar="RUN_ID",
    help="resume only: the canopy review run whose findings the worker addresses. Its prompt carries them from the "
    "journal; nothing of the review is on the PR.",
)
@click.option(
    "--reason",
    "reasons",
    type=click.Choice([str(r) for r in ResumeReason]),
    multiple=True,
    help="resume only, and required for it: why it runs, once for each: ci (failed checks), review (review feedback "
    "or a canopy review's findings), reply (an authorized reply or an operator message), conflict (with its base), "
    "no_pr (a pushed branch with no PR), retarget (its blocker merged). A cursor the dispatch moves needs its reason.",
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
    review_run: int | None,
    reasons: tuple[str, ...],
    context: str | None,
    cursor_pairs: tuple[tuple[str, str], ...],
) -> int:
    """Start a worker on a ticket (overseer only)."""
    return verb(
        click_ctx,
        tools.dispatch_run,
        tools.Dispatch,
        key=key,
        kind=kind,
        label=label,
        repos=repos,
        slug=slug,
        base=base,
        review_run=review_run,
        reasons=reasons,
        context=context,
        cursors=dict(cursor_pairs),
    )


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
