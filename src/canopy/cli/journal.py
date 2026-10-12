"""The overseer's journal commands: `canopy decide`, `canopy attention`, `canopy ticket set`, and `canopy mirror`."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import click

from canopy.cli.common import CliError, open_context, optional_tick, require_tick
from canopy.cli.params import (
    KEY_RE,
    REASON_RE,
    REPO,
    TICKET_KEY,
    CursorType,
    TextType,
    plain_pr_url,
    valid_key,
)
from canopy.core import conversation, db
from canopy.infra import logs
from canopy.loop import attention

if TYPE_CHECKING:
    from canopy.core.context import Context

PHASES = (
    "ready",
    "blocked",
    "running",
    "pushed_no_pr",
    "conflicted",
    "ci_running",
    "ci_red",
    "changes_requested",
    "green_unreviewed",
    "approved",
    "merged",
    "needs_human",
    "human_replied",
    "split",
    "review_pending",
    "review_findings",
)
DECIDE_ACTIONS = ("wait", "skip", "done")


@click.command("decide")
# click has no optional positional before a required one, so `[KEY] ACTION` is parsed by hand.
@click.argument("words", nargs=-1, required=True, metavar="[KEY] ACTION")
@click.option("--rationale", required=True, type=TextType())
@click.pass_context
def cmd_decide(click_ctx: click.Context, words: tuple[str, ...], rationale: str) -> int:
    """Record a decision (overseer only).

    ACTION is wait, skip, or done. KEY may be omitted only for a tick-wide skip.
    """
    if len(words) > 2:  # noqa: PLR2004
        raise click.UsageError(f"expected [KEY] ACTION, got {len(words)} arguments", click_ctx)
    key, action = (None, words[0]) if len(words) == 1 else words
    if action not in DECIDE_ACTIONS:
        raise click.UsageError(f"invalid action {action!r}: choose from {', '.join(DECIDE_ACTIONS)}", click_ctx)
    if key is not None and not valid_key(key):
        raise click.UsageError(f"invalid ticket key {key!r}: must match {KEY_RE.pattern}", click_ctx)
    if key is None and action != "skip":
        raise click.UsageError(f"{action!r} needs a ticket key; only a tick-wide 'skip' may omit it", click_ctx)
    ctx = open_context(click_ctx)
    current = require_tick(ctx)
    if key is not None:
        db.touch_ticket(ctx.conn, key, ctx.repo)
    db.record_decision(ctx.conn, current["id"], key, action, rationale)
    click.echo(f"recorded {action} for {key or 'this tick'}")
    return 0


def _unit(ctx: Context, repo: str | None) -> str | None:
    """Return the repository `--repo` names, checked against the map, or None if it names none."""
    ws = ctx.workspace
    if repo is None:
        return None
    found = ws.repo(repo)
    if found is None:
        names = ", ".join(r.name for r in ws.repos) or "none yet"
        raise CliError(f"{repo!r} is not a repository in this workspace ({names})")
    return found.name


@click.command("attention")
# click has no optional positional before a required one, so `[KEY] REASON` is parsed by hand.
@click.argument("words", nargs=-1, required=True, metavar="[KEY] REASON")
@click.option("--detail", required=True, type=TextType())
@click.option("--repo", type=REPO, help="The repository of the ticket's unit the item is about, in a workspace.")
@click.option("--pr", "pr", metavar="URL", help="A PR the loop reviews; in place of KEY for a PR with no ticket.")
@click.pass_context
def cmd_attention(
    click_ctx: click.Context, words: tuple[str, ...], detail: str, repo: str | None, pr: str | None
) -> int:
    """Record an attention item about a ticket, or about a PR with --pr (overseer only)."""
    if len(words) > 2 or (len(words) == 1 and pr is None):  # noqa: PLR2004
        raise click.UsageError("expected KEY REASON, or REASON with --pr", click_ctx)
    key, reason = (None, words[0]) if len(words) == 1 else words
    if key is not None and not valid_key(key):
        raise click.UsageError(f"invalid ticket key {key!r}: must match {KEY_RE.pattern}", click_ctx)
    if not REASON_RE.fullmatch(reason):
        raise click.UsageError(f"invalid reason {reason!r}: must match {REASON_RE.pattern}", click_ctx)
    if pr is not None and not plain_pr_url(pr):
        raise click.UsageError("--pr must be a plain https:// URL of at most 300 characters", click_ctx)
    ctx = open_context(click_ctx)
    current = require_tick(ctx)
    unit = _unit(ctx, repo)
    if key is not None:
        db.touch_ticket(ctx.conn, key, ctx.repo)
    db.record_decision(ctx.conn, current["id"], key, f"{attention.ACTION_PREFIX}{reason}", detail, repo=unit, pr=pr)
    click.echo(f"recorded attention {reason} for {attention.subject(key or f'{attention.PR_PREFIX}{pr}', unit)}")
    return 0


@click.group("ticket")
def ticket_group() -> None:
    """Update the journal's view of a ticket (overseer only)."""


@ticket_group.command("set")
@click.argument("key", type=TICKET_KEY)
@click.option(
    "--repo",
    type=REPO,
    help="The unit a phase about a PR and the review and ci cursors are for.",
)
@click.option("--phase", type=click.Choice(PHASES))
@click.option("--cursor", "cursor_pairs", type=CursorType(), multiple=True)
@click.option("--done", is_flag=True)
@click.pass_context
def cmd_ticket_set(
    click_ctx: click.Context,
    *,
    key: str,
    repo: str | None,
    phase: str | None,
    cursor_pairs: tuple[tuple[str, str], ...],
    done: bool,
) -> int:
    """Record a ticket's phase, cursors, or done flag, or a unit's phase and cursors.

    The comment cursor, the done flag, and the ticket's own phases are the ticket's. The review and ci cursors and the
    phases about a PR, `pushed_no_pr` to `merged`, are a unit's, one per repository the ticket has a PR in.
    """
    ctx = open_context(click_ctx)
    unit_pairs = [(name, value) for name, value in cursor_pairs if name in db.UNIT_CURSORS]
    unit_phase = phase if phase in db.UNIT_PHASES else None
    unit = _unit(ctx, repo)
    if unit is None and (unit_pairs or unit_phase is not None):
        what = f"a {unit_pairs[0][0]} cursor" if unit_pairs else f"the {unit_phase} phase"
        raise click.UsageError(f"{what} belongs to one unit: name its repository with --repo")
    current = optional_tick(ctx)
    # A dry run must not advance cursors or mark a ticket done: the first live tick would then miss everything the dry
    # runs saw, or never see the ticket at all.
    dry_run = current is not None and bool(current["dry_run"])
    ignored = [
        *(["cursors not advanced"] if dry_run and cursor_pairs else []),
        *(["not marked done"] if dry_run and done else []),
    ]
    ticket_cursors = {} if dry_run else {n: v for n, v in cursor_pairs if n in db.TICKET_CURSORS}
    db.set_ticket(
        ctx.conn,
        key,
        ctx.repo,
        phase=None if unit_phase is not None else phase,
        cursors=ticket_cursors,
        done=done and not dry_run,
    )
    unit_cursors: dict[str, str] = {} if dry_run else dict(unit_pairs)
    if unit is not None and (unit_phase is not None or unit_cursors):
        db.set_unit(ctx.conn, key, ctx.repo, unit, phase=unit_phase, cursors=unit_cursors)
    note = f"; dry run, {' and '.join(ignored)}" if ignored else ""
    click.echo(f"updated {key if repo is None else attention.subject(key, unit)}{note}")
    return 0


@click.command("mirror")
@click.argument("ref", metavar="REF")
@click.option("--comment", "comment_id", required=True, metavar="ID", help="The tracker's id of the comment.")
@click.option("--author", required=True, metavar="ACCOUNT", help="Its author's account id on the tracker.")
@click.option("--at", "at", required=True, metavar="TIME", help="When the tracker says it was written, ISO 8601.")
@click.option(
    "--body",
    metavar="TEXT",
    help=f"Its text; read from stdin without it. Cut to {conversation.MAX_MIRRORED} characters, and marked truncated.",
)
@click.pass_context
def cmd_mirror(click_ctx: click.Context, *, ref: str, comment_id: str, author: str, at: str, body: str | None) -> int:
    """Record a tracker comment in a ticket's conversation in the journal (overseer only).

    Recording a comment again records nothing new. A mirrored comment is a copy for the operator to read, and
    authorizes nothing.
    """
    ctx = open_context(click_ctx)
    current = require_tick(ctx)
    tick_id = int(current["id"])
    log = logs.for_tick(tick_id)
    key: str | None = None
    try:
        subject = conversation.parse_ref(ref)
        key = subject.id if subject.kind == conversation.TICKET else None
        mirrored = conversation.mirror(
            ctx.conn,
            ctx.config,
            subject,
            tick_id=tick_id,
            dry_run=bool(current["dry_run"]),
            repo=ctx.repo,
            comment_id=comment_id,
            author=author,
            at=at,
            body=body if body is not None else sys.stdin.read(),
        )
    except conversation.Refused as r:
        if key is not None:
            db.touch_ticket(ctx.conn, key, ctx.repo)
        db.record_decision(ctx.conn, tick_id, key, f"refused:{r.guard}", r.reason)
        log.info("mirror refused", extra={"ticket": key, "comment": comment_id[:100], "guard": r.guard})
        raise CliError(f"mirror refused ({r.guard}): {r.reason}; the refusal was recorded") from None
    log.info(
        "comment mirrored",
        extra={"ticket": key, "comment": comment_id, "message_id": mirrored.message_id, "new": mirrored.new},
    )
    if mirrored.new:
        cut = ", truncated" if mirrored.truncated else ""
        click.echo(f"mirrored comment {comment_id} on {ref} as message {mirrored.message_id} ({mirrored.source}{cut})")
    else:
        click.echo(f"comment {comment_id} on {ref} is already message {mirrored.message_id}; nothing new recorded")
    return 0
