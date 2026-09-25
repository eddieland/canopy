"""The overseer's journal commands: `canopy decide`, `canopy attention`, and `canopy ticket set`."""

from __future__ import annotations

import click

from canopy.cli.common import open_context, optional_tick, require_tick
from canopy.cli.params import KEY_RE, REASON, TICKET_KEY, CursorType, TextType, valid_key
from canopy.core import db
from canopy.loop import attention

PHASES = (
    "ready",
    "blocked",
    "running",
    "pushed_no_pr",
    "ci_running",
    "ci_red",
    "changes_requested",
    "green_unreviewed",
    "approved",
    "merged",
    "needs_human",
    "human_replied",
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


@click.command("attention")
@click.argument("key", type=TICKET_KEY)
@click.argument("reason", type=REASON)
@click.option("--detail", required=True, type=TextType())
@click.pass_context
def cmd_attention(click_ctx: click.Context, key: str, reason: str, detail: str) -> int:
    """Record an attention item (overseer only)."""
    ctx = open_context(click_ctx)
    current = require_tick(ctx)
    db.touch_ticket(ctx.conn, key, ctx.repo)
    db.record_decision(ctx.conn, current["id"], key, f"{attention.ACTION_PREFIX}{reason}", detail)
    click.echo(f"recorded attention {reason} for {key}")
    return 0


@click.group("ticket")
def ticket_group() -> None:
    """Update the journal's view of a ticket (overseer only)."""


@ticket_group.command("set")
@click.argument("key", type=TICKET_KEY)
@click.option("--phase", type=click.Choice(PHASES))
@click.option("--cursor", "cursor_pairs", type=CursorType(), multiple=True)
@click.option("--done", is_flag=True)
@click.pass_context
def cmd_ticket_set(
    click_ctx: click.Context,
    *,
    key: str,
    phase: str | None,
    cursor_pairs: tuple[tuple[str, str], ...],
    done: bool,
) -> int:
    """Record a ticket's phase, cursors, or done flag."""
    ctx = open_context(click_ctx)
    current = optional_tick(ctx)
    # A dry run must not advance cursors or mark a ticket done: the first live tick would then miss everything the dry
    # runs saw, or never see the ticket at all.
    dry_run = current is not None and bool(current["dry_run"])
    ignored = [
        *(["cursors not advanced"] if dry_run and cursor_pairs else []),
        *(["not marked done"] if dry_run and done else []),
    ]
    cursors = {} if dry_run else dict(cursor_pairs)
    db.set_ticket(ctx.conn, key, ctx.repo, phase=phase, cursors=cursors, done=done and not dry_run)
    note = f"; dry run, {' and '.join(ignored)}" if ignored else ""
    click.echo(f"updated {key}{note}")
    return 0
