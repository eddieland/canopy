"""The overseer's journal commands: `decide`, `queried`, `attention`, `ticket set`, and `mirror`, each `canopy <it>`."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import click

from canopy.cli.common import CliError, Group, OverseerCommand, open_context, optional_tick, require_tick
from canopy.cli.params import (
    KEY_RE,
    MAX_TEXT,
    PR_URL,
    REASON_RE,
    REPO,
    TICKET_KEY,
    CursorType,
    TextType,
    TitleType,
    valid_key,
)
from canopy.core import conversation, db, vocab
from canopy.infra import logs
from canopy.loop import attention, duties
from canopy.reviews import grants

if TYPE_CHECKING:
    from canopy.core.context import Context

DECIDE_ACTIONS = ("wait", "skip", "done")


@click.command("decide", cls=OverseerCommand)
# click has no optional positional before a required one, so `[KEY] ACTION` is parsed by hand.
@click.argument("words", nargs=-1, required=True, metavar="[KEY] ACTION")
@click.option(
    "--rationale", required=True, type=TextType(), help="Why, in your own words: `canopy decisions` shows it."
)
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


@click.command("queried", cls=OverseerCommand)
@click.argument("keys", nargs=-1, type=TICKET_KEY, metavar="[KEY]...")
@click.pass_context
def cmd_queried(click_ctx: click.Context, keys: tuple[str, ...]) -> int:
    """Record that this tick ran the tracker query, naming each open ticket it returned (overseer only).

    Name none when it returned no open ticket. Every ticket named is owed a decision this tick, unless the state block
    lists it in `stopped` or `recently_done`. Record a long result in several calls.
    """
    found = list(dict.fromkeys(keys))
    rationale = duties.queried_rationale(found)
    if len(rationale) > MAX_TEXT:
        raise click.UsageError(f"{len(found)} keys do not fit in one call: name them in several", click_ctx)
    ctx = open_context(click_ctx)
    current = require_tick(ctx)
    # Into the journal at once, so the next tick's block carries each one even if this tick ends without deciding it.
    for key in found:
        db.touch_ticket(ctx.conn, key, ctx.repo)
    db.record_decision(ctx.conn, current["id"], None, duties.QUERIED_ACTION, rationale)
    click.echo(f"recorded the query: {len(found)} open ticket(s)")
    return 0


def _unit(ctx: Context, repo: str | None) -> str | None:
    """Return the repository `--repo` names, checked against the map, or None if it names none.

    Raises:
        CliError: `repo` is not a repository in this workspace.
    """
    ws = ctx.workspace
    if repo is None:
        return None
    found = ws.repo(repo)
    if found is None:
        names = ", ".join(r.name for r in ws.repos) or "none yet"
        raise CliError(f"{repo!r} is not a repository in this workspace ({names})")
    return found.name


@click.command("attention", cls=OverseerCommand)
# click has no optional positional before a required one, so `[KEY] REASON` is parsed by hand.
@click.argument("words", nargs=-1, required=True, metavar="[KEY] REASON")
@click.option(
    "--detail", required=True, type=TextType(), help="What the operator needs to know, shown on the attention list."
)
@click.option("--repo", type=REPO, help="The repository of the ticket's unit the item is about, in a workspace.")
@click.option("--pr", "pr", type=PR_URL, help="A PR the loop reviews; in place of KEY for a PR with no ticket.")
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
    ctx = open_context(click_ctx)
    current = require_tick(ctx)
    unit = _unit(ctx, repo)
    if key is not None:
        db.touch_ticket(ctx.conn, key, ctx.repo)
    if reason == "review_limit" and pr is not None:
        # However the overseer words it, the item names what lifts the limit (DESIGN §21).
        detail = f"{detail}; {grants.hint(pr)}"
    db.record_decision(ctx.conn, current["id"], key, f"{attention.ACTION_PREFIX}{reason}", detail, repo=unit, pr=pr)
    click.echo(f"recorded attention {reason} for {attention.subject(key or f'{attention.PR_PREFIX}{pr}', unit)}")
    return 0


@click.group("ticket", cls=Group)
def ticket_group() -> None:
    """Update the journal's view of a ticket (overseer only)."""


@ticket_group.command("set", cls=OverseerCommand)
@click.argument("key", type=TICKET_KEY)
@click.option(
    "--repo",
    type=REPO,
    help="The unit a phase about a PR and the review and ci cursors are for.",
)
@click.option(
    "--phase",
    type=click.Choice([p.value for p in vocab.Phase]),
    help="The ticket's phase, or a unit's with --repo: pushed_no_pr to merged are about a PR, so a unit's.",
)
@click.option(
    "--cursor",
    "cursor_pairs",
    type=CursorType(),
    multiple=True,
    help="Advance a cursor past what you handled. comment and message are the ticket's; review and ci a unit's, "
    "with --repo. Repeat it for several. A dry run advances none.",
)
@click.option("--done", is_flag=True, help="Mark the ticket done in the journal. A dry run does not.")
@click.option(
    "--title",
    type=TitleType(),
    help="A short name for the ticket, from its own title: shown beside its key, and the session title of its runs.",
)
@click.pass_context
def cmd_ticket_set(
    click_ctx: click.Context,
    *,
    key: str,
    repo: str | None,
    phase: str | None,
    cursor_pairs: tuple[tuple[str, str], ...],
    done: bool,
    title: str | None,
) -> int:
    """Record a ticket's phase, cursors, done flag, or title, or a unit's phase and cursors.

    The comment cursor, the done flag, and the ticket's own phases are the ticket's. The review and ci cursors and the
    phases about a PR, `pushed_no_pr` to `merged`, are a unit's, one per repository the ticket has a PR in.
    """
    ctx = open_context(click_ctx)
    unit_pairs = [(name, value) for name, value in cursor_pairs if name in db.UNIT_CURSORS]
    unit_phase = phase if phase in vocab.UNIT_PHASES else None
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
        title=title,
    )
    unit_cursors: dict[str, str] = {} if dry_run else dict(unit_pairs)
    if unit is not None and (unit_phase is not None or unit_cursors):
        db.set_unit(ctx.conn, key, ctx.repo, unit, phase=unit_phase, cursors=unit_cursors)
    note = f"; dry run, {' and '.join(ignored)}" if ignored else ""
    click.echo(f"updated {key if repo is None else attention.subject(key, unit)}{note}")
    return 0


@click.command("mirror", cls=OverseerCommand)
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
