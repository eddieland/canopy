"""`canopy draft`: the comments workers drafted under `trust.review_replies = "approve"`, for the operator (DESIGN §29).

A draft is a worker's text, written from coworkers' comments, until the operator sends it, so every command prints it
as plain text with each character that hides text named. A draft is named as a review's finding is: its run,
`run:ID`, and its number in that run. Sending, or staging in a pending review to submit on GitHub, names each draft
with the hash of its text as `list` or `show` printed it, so what is posted is what the operator read. The commands that
write refuse inside canopy's own ticks and runs.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

from canopy.cli.common import CliError, Group, open_context
from canopy.core import conversation, drafts, drafts_manage, records, replies
from canopy.core.memory_text import visible
from canopy.core.vocab import DraftKind, DraftStatus, Reaction, ReviewItem
from canopy.infra import logs
from canopy.loop import attention

if TYPE_CHECKING:
    import sqlite3

# The channel a send or an edit from the shell is recorded with (DESIGN §22).
CLI = "cli"
_RUN_REF = re.compile(r"run:([1-9][0-9]*)")
_WANTED = re.compile(r"([1-9][0-9]*)@([0-9a-f]+)")
# The statuses `list` shows: what still waits on the operator, or on a read.
_OPEN = (DraftStatus.WAITING, DraftStatus.UNCHECKED, DraftStatus.UNCONFIRMED, DraftStatus.STAGED)


def _run_ref(value: str) -> int:
    found = _RUN_REF.fullmatch(value)
    if found is None:
        raise click.BadParameter(f"{value!r} is not a run's ref, like run:12")
    return int(found.group(1))


def _wanted(run_id: int, wanted: tuple[str, ...]) -> list[drafts_manage.Wanted]:
    named: list[drafts_manage.Wanted] = []
    for item in wanted:
        found = _WANTED.fullmatch(item)
        if found is None:
            raise click.BadParameter(f"{item!r} is not N@HASH, as `canopy draft list` prints them")
        named.append(drafts_manage.Wanted(run_id, int(found.group(1)), found.group(2)))
    return named


@click.group("draft", cls=Group)
def draft_group() -> None:
    """Read, edit, drop, and send the comments workers drafted for you under `trust.review_replies = "approve"`."""


@draft_group.command("list")
@click.argument("subject", metavar="[KEY|URL]", required=False)
@click.pass_context
def cmd_list(click_ctx: click.Context, subject: str | None) -> int:
    """List the drafts that wait on you, of a ticket KEY or a PR's URL, or every one.

    Each comes with its thread as last read, its text, and its hash.
    """
    ctx = open_context(click_ctx)
    marks = ", ".join("?" * len(_OPEN))
    where = f"status IN ({marks})"
    params: list[object] = list(_OPEN)
    if subject is not None:
        where += " AND (ticket_key = ? OR pr_url = ?)"
        params += [subject, subject]
    found = records.fetch_all(
        ctx.conn,
        records.Draft,
        f"SELECT * FROM drafts WHERE {where} ORDER BY run_id, number",  # noqa: S608  (placeholders only)
        params,
    )
    click.echo(f"Review replies: {ctx.config.trust.review_replies}.")
    if not found:
        click.echo(f"\nNo drafts wait on you{f' for {subject}' if subject else ''}.")
    for draft in found:
        _print(ctx.conn, draft)
    return 0


@draft_group.command("show")
@click.argument("run_ref", metavar="run:ID")
@click.pass_context
def cmd_show(click_ctx: click.Context, run_ref: str) -> int:
    """Print every draft of one run, whatever became of it, and the drafts canopy refused of it."""
    run_id = _run_ref(run_ref)
    ctx = open_context(click_ctx)
    found = drafts.of_run(ctx.conn, run_id)
    rendered = replies.run_replies(ctx.conn, run_id)
    if rendered is None:
        click.echo(f"Run {run_id} was not rendered under trust.review_replies; it has no drafts.")
        return 0
    click.echo(f"Run {run_id} was rendered under review_replies = {rendered.mode}.")
    for draft in found:
        _print(ctx.conn, draft)
    refused = drafts.refused_of(rendered)
    if refused:
        click.echo("\nRefused:")
        for r in refused:
            click.echo(f"  {r.number}: {r.why}")
    return 0


@draft_group.command("edit")
@click.argument("run_ref", metavar="run:ID")
@click.argument("number", metavar="N", type=int)
@click.option("--text", help="The draft's new text; empty, with a reaction, to send the reaction alone.")
@click.option("--file", "path", type=click.Path(dir_okay=False, allow_dash=True), help="Read it from a file, - stdin.")
@click.option(
    "--react",
    "reaction",
    type=click.Choice([r.value for r in Reaction]),
    help="A thread's draft: the reaction it adds to the comment it answers.",
)
@click.option("--no-react", "unreact", is_flag=True, help="Take the draft's reaction off.")
@click.pass_context
def cmd_edit(  # noqa: PLR0917  (click passes each option)
    click_ctx: click.Context,
    run_ref: str,
    number: int,
    text: str | None,
    path: str | None,
    reaction: str | None,
    *,
    unreact: bool,
) -> int:
    """Make the words of draft N of run:ID yours: its text, its reaction, or both. The run's own are kept beside them.

    What you leave out stays as it stands.
    """
    if text is not None and path is not None:
        raise click.UsageError("give the new text with --text or --file, not both")
    if reaction is not None and unreact:
        raise click.UsageError("give --react or --no-react, not both")
    if text is None and path is None and reaction is None and not unreact:
        raise click.UsageError("give the new text with --text or --file, or a reaction with --react or --no-react")
    if text is None and path is not None:
        text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    run_id = _run_ref(run_ref)
    try:
        conversation.check_operator()
        ctx = open_context(click_ctx)
        current = drafts.text_of(ctx.conn, drafts_manage.find(ctx.conn, run_id, number).id)
        react = None if unreact else Reaction(reaction) if reaction is not None else current.reaction
        words = current.body if text is None else text
        version = drafts_manage.edit(ctx.conn, run_id, number, words, react, channel=CLI)
    except conversation.Refused as r:
        raise CliError(f"edit refused ({r.guard}): {r.reason}") from None
    click.echo(f"Run {run_id}'s draft {number} is in your words now, version {version.version}, hash "
               f"{drafts_manage.hash_of_version(version)}.")  # fmt: skip
    return 0


@draft_group.command("drop")
@click.argument("run_ref", metavar="run:ID")
@click.argument("numbers", metavar="N...", type=int, nargs=-1, required=True)
@click.option("--undo", is_flag=True, help="Take the drop back.")
@click.pass_context
def cmd_drop(click_ctx: click.Context, run_ref: str, numbers: tuple[int, ...], *, undo: bool) -> int:
    """Drop drafts of run:ID, so nobody sends them."""
    run_id = _run_ref(run_ref)
    try:
        conversation.check_operator()
        ctx = open_context(click_ctx)
        found = drafts_manage.drop(ctx.conn, run_id, numbers, undo=undo)
    except conversation.Refused as r:
        raise CliError(f"drop refused ({r.guard}): {r.reason}") from None
    attention.write(ctx, logs.for_tick(None))
    for draft in found:
        click.echo(f"Run {run_id}'s draft {draft.number} is {draft.status}.")
    return 0


@draft_group.command("send")
@click.argument("run_ref", metavar="run:ID")
@click.argument("wanted", metavar="N@HASH...", nargs=-1, required=True)
@click.pass_context
def cmd_send(click_ctx: click.Context, run_ref: str, wanted: tuple[str, ...]) -> int:
    """Send drafts of run:ID as your own words, each N with the HASH of its text that `list` or `show` printed.

    The drafts for one PR go as one comment review, which approves nothing and resolves no thread. A send that ends
    without saying whether it posted leaves its drafts unconfirmed until a read of the PR says.
    """
    run_id = _run_ref(run_ref)
    named = _wanted(run_id, wanted)
    try:
        conversation.check_operator()
        ctx = open_context(click_ctx)
        log = logs.for_tick(None)
        sent = drafts_manage.send(ctx.conn, ctx.config, ctx.runner, named, channel=CLI, log=log)
    except conversation.Refused as r:
        raise CliError(f"send refused ({r.guard}): {r.reason}") from None
    attention.write(ctx, log)
    for draft in sent.posted:
        click.echo(f"Sent run {run_id}'s draft {draft.number}: {draft.sent_url or draft.pr_url or draft.issue_url}")
    for draft in sent.already:
        click.echo(f"Run {run_id}'s draft {draft.number} was sent already: {draft.sent_url}")
    for draft, why in sent.failed:
        click.echo(f"Run {run_id}'s draft {draft.number} was not sent: {why}")
    for draft in sent.unconfirmed:
        click.echo(
            f"Run {run_id}'s draft {draft.number} may have been posted: the post ended without saying. A read of "
            "its PR settles it; canopy sends it no other time."
        )
    return 1 if sent.failed or sent.unconfirmed else 0


@draft_group.command("stage")
@click.argument("run_ref", metavar="run:ID")
@click.argument("wanted", metavar="N@HASH...", nargs=-1, required=True)
@click.pass_context
def cmd_stage(click_ctx: click.Context, run_ref: str, wanted: tuple[str, ...]) -> int:
    """Start a review on GitHub holding drafts of run:ID, for you to finish and submit there, each N@HASH as for send.

    The drafts for one PR go into one pending review, which only you see until you submit it. A reaction is added only
    by a send, so a draft that adds one is refused. Each read of the PR after you submit or delete the review settles
    its drafts: sent, or waiting on you again.
    """
    run_id = _run_ref(run_ref)
    named = _wanted(run_id, wanted)
    try:
        conversation.check_operator()
        ctx = open_context(click_ctx)
        log = logs.for_tick(None)
        staged = drafts_manage.stage(ctx.conn, ctx.config, ctx.runner, named, channel=CLI, log=log)
    except conversation.Refused as r:
        raise CliError(f"stage refused ({r.guard}): {r.reason}") from None
    attention.write(ctx, log)
    for pr in dict.fromkeys(d.pr_url for d in staged.staged):
        numbers = ", ".join(str(d.number) for d in staged.staged if d.pr_url == pr)
        click.echo(f"Staged run {run_id}'s drafts {numbers} in a review on {pr}; finish it at {pr}/files")
    for draft in staged.already:
        click.echo(f"Run {run_id}'s draft {draft.number} was sent already: {draft.sent_url}")
    for draft, why in staged.failed:
        click.echo(f"Run {run_id}'s draft {draft.number} was not staged: {why}")
    for draft in staged.unconfirmed:
        click.echo(
            f"Run {run_id}'s draft {draft.number} may have been staged: the post ended without saying. A read of its "
            "PR settles it."
        )
    return 1 if staged.failed or staged.unconfirmed else 0


@draft_group.command("settle")
@click.argument("run_ref", metavar="run:ID")
@click.argument("number", metavar="N", type=int)
@click.option("--sent/--unsent", "sent", required=True, help="Whether it was posted, as the ticket shows.")
@click.pass_context
def cmd_settle(click_ctx: click.Context, run_ref: str, number: int, *, sent: bool) -> int:
    """Say whether an unconfirmed draft of run:ID was posted, as for a ticket's, which no read settles."""
    run_id = _run_ref(run_ref)
    try:
        conversation.check_operator()
        ctx = open_context(click_ctx)
        draft = drafts_manage.settle(ctx.conn, run_id, number, sent=sent)
    except conversation.Refused as r:
        raise CliError(f"settle refused ({r.guard}): {r.reason}") from None
    click.echo(f"Run {run_id}'s draft {number} is {draft.status}.")
    return 0


def _print(conn: sqlite3.Connection, draft: records.Draft) -> None:
    text = drafts.text_of(conn, draft.id)
    edited = " (your edit)" if text.version > 1 else ""
    match draft.kind:
        case DraftKind.THREAD:
            where = f"a reply to comment {draft.comment_id} on {draft.pr_url} ({draft.stance})"
        case DraftKind.PR:
            where = f"the comment on {draft.pr_url}"
        case DraftKind.TICKET:
            where = f"a comment on {draft.ticket_key}'s ticket, {draft.issue_url}"
    click.echo(f"\nrun:{draft.run_id} {draft.number}  {draft.status}  {where}")
    staged = f"in the review you staged; submit or delete it at {draft.pr_url}/files"
    note = staged if draft.status is DraftStatus.STAGED else draft.why
    if note:
        click.echo(f"  {note}")
    if draft.kind is DraftKind.THREAD and draft.thread_id is not None:
        for c in records.fetch_all(
            conn,
            records.ObservedReview,
            "SELECT * FROM observed_reviews WHERE pr_url = ? AND item = ? AND thread_id = ? ORDER BY created_at, id",
            (draft.pr_url, ReviewItem.COMMENT, draft.thread_id),
        ):
            click.echo(f"  > {c.author} at {c.created_at}: {visible(' '.join(c.body.split()))}")
    if draft.reacted is not None and draft.status is not DraftStatus.SENT:
        click.echo(
            f"  {draft.reacted} is on comment {draft.comment_id} already: a send that did not post the rest added it"
        )
    hashed = f"  hash {drafts_manage.hash_of_version(text)}{edited}"
    if text.reaction is not None and not text.body:
        click.echo(f"{hashed}, the reaction {text.reaction} alone")
        return
    click.echo(f"{hashed}, with the reaction {text.reaction}:" if text.reaction is not None else f"{hashed}:")
    for line in text.body.split("\n"):
        click.echo(f"    {visible(line)}")
