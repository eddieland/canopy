"""`canopy dispatch`, and the detached `canopy _run` it starts."""

from __future__ import annotations

import os
import sys
from collections.abc import Collection, Iterable, Sequence
from typing import TYPE_CHECKING

import click

from canopy.cli.common import CliError, OverseerCommand, open_context, require_tick
from canopy.cli.params import COMMENT_ID, REPO, SLUG, TICKET_KEY, CursorType, TextType, truncate
from canopy.core import db
from canopy.core.vocab import ResumeReason, RunKind
from canopy.infra import logs
from canopy.loop import attention, tick
from canopy.reviews import findings
from canopy.runs import dispatch, policy, worker

if TYPE_CHECKING:
    import sqlite3


@click.command("dispatch", cls=OverseerCommand)
@click.argument("key", type=TICKET_KEY)
# `fix-ci` is taken only to be refused naming `resume --reason ci`, a refusal the overseer's decisions record.
@click.option(
    "--kind",
    required=True,
    type=click.Choice([*(str(k) for k in policy.DISPATCH_KINDS), str(policy.RETIRED)]),
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
    "--request",
    type=COMMENT_ID,
    metavar="COMMENT_ID",
    help="split only, and required for it: the authorized replier's comment on the ticket that asked for the split.",
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
    request: str | None,
    review_run: int | None,
    reasons: tuple[str, ...],
    context: str | None,
    cursor_pairs: tuple[tuple[str, str], ...],
) -> int:
    """Start a worker on a ticket (overseer only)."""
    ctx = open_context(click_ctx)
    unit_cursors = [name for name, _ in cursor_pairs if name in db.UNIT_CURSORS]
    if unit_cursors and len(set(repos)) > 1:
        raise click.UsageError(
            f"a {unit_cursors[0]} cursor belongs to one unit: advance it with `canopy ticket set {key} --repo NAME`",
            click_ctx,
        )
    current = require_tick(ctx)
    tick_id = current.id
    log = logs.for_tick(tick_id)
    db.touch_ticket(ctx.conn, key, ctx.repo)
    dry_run = current.dry_run
    try:
        dispatch.check_kind(kind)
        review = _review_findings(ctx.conn, key, kind, repos, review_run)
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
                reasons=reasons,
                cursors=_handles(cursor_pairs, review_run),
            )
            branch, queue_label, repo_names, starts = plan.branch, plan.label, plan.repos, plan.starts
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
                review=review,
                reasons=reasons,
                cursors=_handles(cursor_pairs, review_run),
            )
            branch, queue_label, repo_names, starts = started.branch, started.label, started.repos, started.starts
    except dispatch.Refusal as r:
        db.record_decision(ctx.conn, tick_id, key, f"refused:{r.guard}", r.reason)
        if r.attention is not None:
            # The overseer wants work a guard forbids, and only a human can lift it: the attempt limit, or a retired
            # prompt override (DESIGN §8, §14). In a workspace of several, the item is about the unit it holds.
            db.record_decision(ctx.conn, tick_id, key, f"{attention.ACTION_PREFIX}{r.attention}", r.reason, repo=r.repo)
        log.info("dispatch refused", extra={"ticket": key, "kind": kind, "guard": r.guard, "reason": r.reason})
        raise CliError(f"dispatch refused ({r.guard}): {r.reason}; the refusal was recorded") from None
    # `base` passed the guards, so it is the branch this run is stacked on. `queue_label` is the configured spelling, or
    # empty for a private ticket, which its start record authorizes (DESIGN §22). Under `tracker.private` the label
    # authorizes a ticket's first run, which starts it privately.
    authorized = f"label {queue_label}" if queue_label else "private: started by the operator"
    authorized += "; starts it privately (tracker.private)" if starts else ""
    in_repo = f" in {', '.join(repo_names)}"
    work = _work(key, kind, branch, base, repo_names)
    requested = f"; request {request}" if request is not None else ""
    requested += f"; review run {review_run}" if review_run is not None else ""
    requested += f"; {_for(reasons)}" if reasons else ""
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
                        if kind in policy.TICKET_KINDS
                        else f"dry run: not dispatched; would work on {work}{in_repo}"
                    ),
                    authorized,
                    f"request {request}" if request is not None else "",
                    f"review run {review_run}" if review_run is not None else "",
                    _for(reasons) if reasons else "",
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
        db.set_unit(ctx.conn, key, ctx.repo, repo_names[0], cursors=cursors)
    where = _where(started)
    rationale = f"run {started.run_id}: {work}{where}; {authorized}{requested}"
    db.record_decision(ctx.conn, tick_id, key, f"dispatch:{kind}", rationale)
    log.info("dispatched", extra={"ticket": key, "kind": kind, "run_id": started.run_id, "pid": started.pid})
    click.echo(f"dispatched {kind} for {key}: {rationale}")
    return 0


def _where(started: dispatch.Started) -> str:
    """Return where a dispatch's decision says the run works: its slots, or the clones a triage reads, and its desk."""
    if started.slots:
        where = " in " + ", ".join(f"{s.repo} at {s.slot_path}" for s in started.slots)
    else:
        # A triage leases no slot: it reads the primary clones (DESIGN §25).
        where = " reading the primary clones"
    return where + (f"; desk {started.desk}" if started.desk is not None else "")


def _work(key: str, kind: str, branch: str, base: str | None, repos: Sequence[str]) -> str:
    """Return what a dispatch's decision says the run works on: its branch, or for a kind counted per ticket, its key.

    A split, a plan, or a triage works on no branch: it reads its repositories, and creates a ticket for each, writes a
    plan, or judges whether the ticket needs one.
    """
    if kind == policy.SPLIT:
        return f"split {key} into {', '.join(repos)}"
    if kind == policy.PLAN:
        return f"plan {key} over {', '.join(repos)}"
    if kind == policy.NEEDS_PLAN:
        return f"triage {key}'s plan over {', '.join(repos)}"
    return f"{branch} on {base}" if base is not None else branch


def _handles(cursor_pairs: Iterable[tuple[str, str]], review_run: int | None) -> frozenset[str]:
    """What the dispatch handles, each needing its reason (DESIGN §8): the cursors it moves, and `review_run`."""
    return frozenset(name for name, _ in cursor_pairs) | ({"review_run"} if review_run is not None else frozenset())


def _for(reasons: Collection[str]) -> str:
    """How a decision's rationale names a resume's reasons, in the vocabulary's order."""
    return f"for {', '.join(r for r in ResumeReason if r in reasons)}"


def _review_findings(
    conn: sqlite3.Connection, key: str, kind: str, repos: Sequence[str], run_id: int | None
) -> str | None:
    """Return the worker's `{{REVIEW_FINDINGS}}` for `--review-run`, or None without it (DESIGN §21).

    Raises:
        dispatch.Refusal: `--review-run` is given for a kind other than `resume`, or its review run is missing, of
            another ticket or repository, not `done`, or found nothing.
    """
    if run_id is None:
        return None
    if kind != RunKind.RESUME:
        raise dispatch.Refusal(
            "bad_review", "--review-run names findings for a resume to address; it is for resume only"
        )
    try:
        return findings.for_worker(conn, run_id, key, repos)
    except findings.Unusable as e:
        raise dispatch.Refusal("bad_review", str(e)) from None


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
