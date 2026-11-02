"""`canopy review`: `show`, `noise`, `eval`, and drafts, for you. The overseer starts reviews through its tools (§27).

The detached `_review` does one review run (DESIGN §21), or one revision of a review's draft (§34). A review of a PR
the loop does not own is a draft of a review on that PR (§34): `draft` shows it as it would post, `edit` changes it,
`publish` posts one version as the operator's own comment review, named by the hash `draft` printed, and `discard`
says it will not post. A draft's text is the reviewer's, or a reviser's, written from the PR's, until the operator
publishes it, so it is printed as plain text with each character that hides text named. The commands that write refuse
inside canopy's own ticks and runs; `canopy reply review:ID` notes what a revision should change.
"""

from __future__ import annotations

import contextlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, assert_never

import click

from canopy.cli.common import CliError, leave_the_tick, open_context
from canopy.cli.params import EVAL_CASE, PERSONA
from canopy.core import conversation, db, records, review_drafts, review_drafts_manage, review_revisions
from canopy.core.memory_text import visible
from canopy.core.vocab import ReviewDraftAuthor, ReviewDraftStatus
from canopy.infra import logs, tracing
from canopy.reviews import evals, execute, findings, noise, view

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.config import EvalCase

#: The channel `show` marks a review seen through, and a draft's edit or publish is recorded with (DESIGN §22).
CLI = "cli"


@click.group("review")
def review_group() -> None:
    """Read what canopy's reviews found, and the drafts of reviews of PRs the loop does not own."""


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
            limit = ctx.config.runtime.review_timeout_minutes
            click.echo(findings.described(ctx.conn, run_id, card=conversation.is_operator(), timeout_minutes=limit))
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


@review_group.command("noise")
@click.option(
    "--days",
    type=click.IntRange(min=1, max=3650),
    default=90,
    show_default=True,
    metavar="N",
    help="How many days of reviews to count.",
)
@click.option("--json", "as_json", is_flag=True, help="Print the tallies as one JSON object instead.")
@click.pass_context
def cmd_review_noise(click_ctx: click.Context, *, days: int, as_json: bool) -> int:
    """Count the last days' review findings by severity, persona, and model, and what became of each.

    A finding dismissed `wrong` is the reviewer's noise; `intentional`, `not_worth_it`, and `out_of_scope` held and were
    left, the last for another PR. One not dismissed counts by a worker's latest answer to it, `fixed` or `declined`;
    your dismissal wins over an answer. A rebuttal is a finding held as one of a worker's decline. The `wrong` rate is
    the share of a group's findings dismissed so.
    """
    ctx = open_context(click_ctx)
    found = noise.tally(ctx.conn, db.format_time(datetime.now(UTC) - timedelta(days=days)))
    click.echo(json.dumps(found.as_json(), indent=2) if as_json else "\n".join(noise.lines(found)))
    return 0


@review_group.command("eval")
@click.option(
    "--case",
    "names",
    type=EVAL_CASE,
    multiple=True,
    help="Review this case alone; give it again for each. Default: every case.",
)
@click.option("--persona", type=PERSONA, help="Review in this persona. Default: [personas] reviewer's.")
@click.option("--model", metavar="MODEL", help="Review on this model, provider/model. Default: runtime.models'.")
@click.option("--dry-run", is_flag=True, help="Show the cases and what each would be reviewed with; start nothing.")
@click.option("--json", "as_json", is_flag=True, help="Print the result as one JSON object instead.")
@click.pass_context
def cmd_review_eval(
    click_ctx: click.Context,
    *,
    names: tuple[str, ...],
    persona: str | None,
    model: str | None,
    dry_run: bool,
    as_json: bool,
) -> int:
    """Score the reviewer on your cases, `[[review.eval_cases]]` in your private config, one review each, in turn.

    A bug case is found when a finding is within 3 lines of a line you confirmed its bug on; every finding on a clean
    case is a false alarm. A review that ends any way but done is not scored. The eval records nothing in the journal:
    no review, draft, attention item, or notification. Its result, with the digests of the prompt and the persona and
    the model, is saved in .canopy/review-evals/ to compare with the next, and printed as a section to paste into
    docs/MEASUREMENTS.md. It gates nothing. A case the review guards refuse (the daily limit, review capacity,
    max_workers) is skipped and not scored, so run it while the loop is idle.
    """
    try:
        conversation.check_operator()
    except conversation.Refused as r:
        raise CliError(f"review eval refused ({r.guard}): {r.reason}") from None
    ctx = open_context(click_ctx)
    try:
        setup = evals.prepare(ctx, names=names, persona=persona, model=model)
    except evals.EvalError as e:
        raise CliError(f"review eval refused: {e}") from None
    if dry_run:
        plan = {**evals.setup_json(setup), "cases": [evals.case_json(c) for c in setup.cases]}
        click.echo(json.dumps(plan, indent=2) if as_json else "\n".join(evals.planned(ctx, setup)))
        return 0
    count = len(setup.cases)

    def reviewing(case: EvalCase) -> None:
        number = next(n for n, c in enumerate(setup.cases, 1) if c.name == case.name)
        click.echo(f"reviewing case {number} of {count}, {case.name}: {case.pr} at {case.sha[:12]}", err=True)

    try:
        done = evals.run(ctx, setup, reviewing=reviewing)
    except evals.EvalError as e:
        raise CliError(f"review eval refused: {e}") from None
    click.echo(json.dumps(done.as_json(), indent=2) if as_json else "\n".join(evals.lines(done)))
    click.echo(f"saved to {done.saved}", err=True)
    return 0


@review_group.command("draft")
@click.argument("run_id", type=click.IntRange(min=1))
@click.pass_context
def cmd_review_draft(click_ctx: click.Context, run_id: int) -> int:
    """Show the review of RUN_ID that canopy would publish on the PR in your name, word for word, and its hash.

    Only a `done` review of a PR the loop does not own has one. Its text is the reviewer's until you publish it.
    """
    ctx = open_context(click_ctx)
    try:
        draft = review_drafts_manage.find(ctx.conn, run_id)
    except conversation.Refused as r:
        raise CliError(f"no draft ({r.guard}): {r.reason}") from None
    _print_draft(ctx.conn, draft)
    return 0


@review_group.command("edit")
@click.argument("run_id", type=click.IntRange(min=1))
@click.option("--body", "body", is_flag=True, help="Make the text the review's body; empty posts the comments alone.")
@click.option("--comment", "comment", type=click.IntRange(min=1), metavar="N", help="Make the text comment N's.")
@click.option("--drop", "drop", type=click.IntRange(min=1), metavar="N", help="Drop comment N.")
@click.option("--add", "add", metavar="PATH:LINE", help="Add the text as a comment on a line of the diff it read.")
@click.option("--text", help="The new text.")
@click.option("--file", "path", type=click.Path(dir_okay=False, allow_dash=True), help="Read it from a file, - stdin.")
@click.pass_context
def cmd_review_edit(
    click_ctx: click.Context,
    run_id: int,
    *,
    body: bool,
    comment: int | None,
    drop: int | None,
    add: str | None,
    text: str | None,
    path: str | None,
) -> int:
    """Change the draft of review RUN_ID: its body, a comment, or one comment more or less, as a new version.

    Dismissing a finding (`canopy dismiss review:RUN_ID N`) drops what it made of the draft, and taking it back
    restores it.
    """
    if sum((body, comment is not None, drop is not None, add is not None)) != 1:
        raise click.UsageError("give one of --body, --comment N, --drop N, or --add PATH:LINE")
    if text is not None and path is not None:
        raise click.UsageError("give the text with --text or --file, not both")
    if text is None and path is not None:
        text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    if drop is None and text is None:
        raise click.UsageError("give the text with --text or --file")
    words = text or ""
    try:
        conversation.check_operator()
        ctx = open_context(click_ctx)
        if body:
            version = review_drafts_manage.edit_body(ctx.conn, run_id, words, channel=CLI)
        elif comment is not None:
            version = review_drafts_manage.edit_comment(ctx.conn, run_id, comment, words, channel=CLI)
        elif drop is not None:
            version = review_drafts_manage.drop_comment(ctx.conn, run_id, drop, channel=CLI)
        else:
            version = review_drafts_manage.add_comment(ctx.conn, run_id, str(add), words, channel=CLI)
    except conversation.Refused as r:
        raise CliError(f"edit refused ({r.guard}): {r.reason}") from None
    click.echo(f"Review run {run_id}'s draft is version {version.number} now, hash {version.hash}: {version.change}.")
    return 0


@review_group.command("publish")
@click.argument("run_id", type=click.IntRange(min=1))
@click.argument("version_hash", metavar="HASH")
@click.option("--submit", is_flag=True, help="Submit it on GitHub now, rather than leave it pending for you to submit.")
@click.pass_context
def cmd_review_publish(click_ctx: click.Context, run_id: int, version_hash: str, *, submit: bool) -> int:
    """Post the draft of review RUN_ID, the version whose HASH `draft` printed, on its PR as your own review.

    It goes word for word, unmarked, as one comment review on the commit the review read, its comments on their lines;
    it approves nothing and requests no change. By default it waits on GitHub as a pending review, which only you see
    until you submit it there; with --submit, canopy submits it. A draft publishes once. A post that ends without
    saying whether it submitted leaves the draft unconfirmed until a read of the PR says.
    """
    try:
        conversation.check_operator()
        ctx = open_context(click_ctx)
        log = logs.for_tick(None)
        done = review_drafts_manage.publish(
            ctx.conn,
            ctx.config,
            ctx.runner,
            run_id,
            version_hash,
            submit=submit,
            channel=CLI,
            log=log,
        )
    except conversation.Refused as r:
        raise CliError(f"publish refused ({r.guard}): {r.reason}") from None
    draft, number = done.draft, done.version.number
    match draft.status:
        case ReviewDraftStatus.PUBLISHED:
            click.echo(f"Published version {number} of review run {run_id}'s draft: {draft.published_url}")
        case ReviewDraftStatus.STAGED:
            click.echo(
                f"Staged version {number} of review run {run_id}'s draft in a pending review on {draft.pr_url}; "
                f"submit or delete it at {draft.pr_url}/files",
            )
        case ReviewDraftStatus.UNCONFIRMED:
            click.echo(
                f"Version {number} of review run {run_id}'s draft may have been posted: the post ended without saying. "
                "A read of the PR settles it; canopy posts it no other time.",
            )
        case ReviewDraftStatus.WAITING | ReviewDraftStatus.PUBLISHING | ReviewDraftStatus.DISCARDED:
            click.echo(f"Version {number} of review run {run_id}'s draft was not published: {done.failed}")
        case _:
            assert_never(draft.status)
    return 0 if done.failed is None and draft.status is not ReviewDraftStatus.UNCONFIRMED else 1


@review_group.command("discard")
@click.argument("run_id", type=click.IntRange(min=1))
@click.pass_context
def cmd_review_discard(click_ctx: click.Context, run_id: int) -> int:
    """Discard the draft of review RUN_ID: you have seen it and will not post it.

    Nothing is posted, the draft takes no edit, note, or publish from now on, and its PR stops waiting on you. A review
    of a later commit is a new draft.
    """
    try:
        conversation.check_operator()
        ctx = open_context(click_ctx)
        draft = review_drafts_manage.discard(ctx.conn, run_id, channel=CLI)
    except conversation.Refused as r:
        raise CliError(f"discard refused ({r.guard}): {r.reason}") from None
    click.echo(f"Discarded review run {run_id}'s draft of {draft.pr_url}; nothing was posted.")
    return 0


def _print_draft(conn: sqlite3.Connection, draft: records.ReviewDraft) -> None:
    """Print a review's draft: where it stands, its newest version word for word, and every version's line."""
    run_id = draft.review_run_id
    current = review_drafts.newest(conn, draft.id)
    _print_standing(conn, draft)
    click.echo(f"\nVersion {current.number}, hash {current.hash}: {current.change}, {_by(current)}.")
    for why in current.refused:
        click.echo(f"  Left out: {why}")
    click.echo("Body:" if current.body else "Body: none.")
    for line in current.body.split("\n") if current.body else ():
        click.echo(f"    {visible(line)}")
    for n, c in enumerate(current.comments, 1):
        made = f" (finding {c.finding})" if c.finding is not None else ""
        click.echo(f"Comment {n}, on {visible(c.path)}:{c.line}{made}:")
        for line in c.text.split("\n"):
            click.echo(f"    {visible(line)}")
    click.echo("\nVersions:")
    for v in review_drafts.versions(conn, draft.id):
        click.echo(f"  {v.number}  {v.hash}  {_by(v)}: {v.change}")
    if draft.status is ReviewDraftStatus.WAITING:
        click.echo(
            f"\nTo leave it pending on GitHub for you to submit: canopy review publish {run_id} {current.hash}"
            "\nTo submit it now, add --submit."
            f"\nTo post nothing and stop it waiting on you: canopy review discard {run_id}",
        )


def _print_standing(conn: sqlite3.Connection, draft: records.ReviewDraft) -> None:
    """Print where a draft stands, and whether the PR has moved on from the commit its review read."""
    click.echo(f"Review run {draft.review_run_id}'s draft, of {draft.pr_url} at {draft.sha}: {draft.status}.")
    match draft.status:
        case ReviewDraftStatus.PUBLISHED:
            click.echo(f"  Published at {draft.published_at}: {draft.published_url}")
        case ReviewDraftStatus.STAGED:
            click.echo(f"  In the review you staged; submit or delete it at {draft.pr_url}/files")
        case _:
            if draft.why:
                click.echo(f"  {draft.why}")
    revising = review_revisions.running(conn, draft.id)
    if revising is not None:
        click.echo(f"  Review run {revising.id} is revising it on your notes.")
    elif draft.status is ReviewDraftStatus.WAITING and review_revisions.pending(conn, draft.id):
        click.echo("  Your note asks for a revision: the next tick starts one.")
    pr = records.select(records.ObservedPr).where("url = ?", draft.pr_url).one(conn)
    if pr is not None and pr.head_sha and not draft.sha.startswith(pr.head_sha):
        click.echo(f"  The PR is at {pr.head_sha} now: its comments would show as outdated, on the commit it read.")


def _by(version: review_drafts.Version) -> str:
    match version.author:
        case ReviewDraftAuthor.REVIEWER:
            return "by the reviewer"
        case ReviewDraftAuthor.REVISER:
            return "by a revision"
        case ReviewDraftAuthor.OPERATOR:
            return f"by you through {version.channel}"
        case _:
            assert_never(version.author)


@click.command("_review", hidden=True)
@click.argument("run_id", type=click.IntRange(min=1))
@click.pass_context
def cmd_review_process(click_ctx: click.Context, run_id: int) -> int:
    """Do one review run. Started by a tick, detached; not for people or agents."""
    leave_the_tick()
    ctx = open_context(click_ctx)
    try:
        with tracing.span("review", review_run_id=run_id) as traced:
            outcome = execute.execute(ctx, run_id, out=sys.stdout)
            traced.set(status=outcome.status)
    except execute.ReviewError as e:
        raise CliError(str(e)) from None
    click.echo(f"review run {run_id}: {outcome.status}")
    return 0
