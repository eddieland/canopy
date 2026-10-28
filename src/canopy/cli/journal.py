"""The overseer's journal commands: `decide`, `queried`, `attention`, and `ticket set`, each `canopy <it>`."""

from __future__ import annotations

import click

from canopy.cli.common import Group, OverseerCommand
from canopy.cli.params import (
    KEY_RE,
    PR_URL,
    REASON_RE,
    REPO,
    TICKET_KEY,
    CursorType,
    TextType,
    TitleType,
    valid_key,
    verb,
)
from canopy.loop import tools


@click.command("decide", cls=OverseerCommand)
# click has no optional positional before a required one, nor groups of arguments, so `[KEY] ACTION`, once for each
# --rationale, is parsed by hand: the Nth KEY ACTION pair is the Nth --rationale's.
@click.argument("words", nargs=-1, required=True, metavar="[KEY] ACTION")
@click.option(
    "--rationale",
    "rationales",
    required=True,
    multiple=True,
    type=TextType(),
    help="Why, in your own words: `canopy decisions` shows it. One for each decision.",
)
@click.pass_context
def cmd_decide(click_ctx: click.Context, words: tuple[str, ...], rationales: tuple[str, ...]) -> int:
    """Record a decision, or several, all or none (overseer only).

    ACTION is wait, skip, or done. KEY may be omitted only for a tick-wide skip, whose rationale starts
    `mcp_unavailable:` or `tracker_unsupported:`; a skip with KEY may not give either. Decide several tickets at once
    as `KEY ACTION --rationale WHY`, repeated.
    """
    if len(rationales) == 1 and len(words) <= 2:  # noqa: PLR2004
        pairs = [(None, words[0]) if len(words) == 1 else (words[0], words[1])]
    elif len(words) == 2 * len(rationales):
        pairs = list(zip(words[::2], words[1::2], strict=True))
    else:
        raise click.UsageError(
            f"expected [KEY] ACTION, or KEY ACTION for each of {len(rationales)} --rationale; "
            f"got {len(words)} arguments",
            click_ctx,
        )
    for key, action in pairs:
        if action not in tools.DECIDE_ACTIONS:
            raise click.UsageError(
                f"invalid action {action!r}: choose from {', '.join(tools.DECIDE_ACTIONS)}",
                click_ctx,
            )
        if key is not None and not valid_key(key):
            raise click.UsageError(f"invalid ticket key {key!r}: must match {KEY_RE.pattern}", click_ctx)
    decisions = [
        {"key": key, "action": action, "rationale": rationale}
        for (key, action), rationale in zip(pairs, rationales, strict=True)
    ]
    return verb(click_ctx, tools.decide, tools.Decisions, decisions=decisions)


@click.command("queried", cls=OverseerCommand)
@click.argument("keys", nargs=-1, type=TICKET_KEY, metavar="[KEY]...")
@click.pass_context
def cmd_queried(click_ctx: click.Context, keys: tuple[str, ...]) -> int:
    """Record that this tick ran the tracker query, naming each open ticket it returned (overseer only).

    Name none when it returned no open ticket. Every ticket named is owed a decision this tick, unless the state block
    lists it in `stopped` or `recently_done`. Record a long result in several calls.
    """
    return verb(click_ctx, tools.queried, tools.Queried, keys=keys)


@click.command("attention", cls=OverseerCommand)
# click has no optional positional before a required one, so `[KEY] REASON` is parsed by hand.
@click.argument("words", nargs=-1, required=True, metavar="[KEY] REASON")
@click.option(
    "--detail",
    required=True,
    type=TextType(),
    help="What the operator needs to know, shown on the attention list.",
)
@click.option("--repo", type=REPO, help="The repository of the ticket's unit the item is about, in a workspace.")
@click.option("--pr", "pr", type=PR_URL, help="A PR the loop reviews; in place of KEY for a PR with no ticket.")
@click.option(
    "--item",
    type=click.IntRange(min=1),
    help="needs_author and notice_rerun: the number of the comment, review item, or review run one waits on, or of "
    "the check run one holds.",
)
@click.pass_context
def cmd_attention(  # noqa: PLR0917  (click passes each option)
    click_ctx: click.Context,
    words: tuple[str, ...],
    detail: str,
    repo: str | None,
    pr: str | None,
    item: int | None,
) -> int:
    """Record an attention item about a ticket, or about a PR with --pr (overseer only)."""
    # A REASON with neither KEY nor --pr is the request's to refuse, in the words its tool's refusal uses.
    if len(words) > 2:  # noqa: PLR2004
        raise click.UsageError("expected KEY REASON, or REASON with --pr", click_ctx)
    key, reason = (None, words[0]) if len(words) == 1 else words
    if key is not None and not valid_key(key):
        raise click.UsageError(f"invalid ticket key {key!r}: must match {KEY_RE.pattern}", click_ctx)
    if not REASON_RE.fullmatch(reason):
        raise click.UsageError(f"invalid reason {reason!r}: must match {REASON_RE.pattern}", click_ctx)
    return verb(
        click_ctx,
        tools.attend,
        tools.Attention,
        key=key,
        reason=reason,
        detail=detail,
        repo=repo,
        pr=pr,
        item=item,
    )


@click.group("ticket", cls=Group)
def ticket_group() -> None:
    """Update the journal's view of a ticket (overseer only)."""


@ticket_group.command("set", cls=OverseerCommand)
@click.argument("keys", nargs=-1, required=True, type=TICKET_KEY, metavar="KEY...")
@click.option(
    "--repo",
    type=REPO,
    help="The unit a phase about a PR and the review and ci cursors are for.",
)
@click.option(
    "--phase",
    type=click.Choice(tools.SETTABLE_PHASES),
    help="The ticket's phase, or a unit's with --repo: pushed_no_pr to merged are about a PR, so a unit's.",
)
@click.option(
    "--cursor",
    "cursor_pairs",
    type=CursorType(),
    multiple=True,
    help="Advance a cursor to the newest handled item's number. comment and message are the ticket's; review and ci "
    "a unit's, with --repo. Repeat it for several. A dry run advances none.",
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
    keys: tuple[str, ...],
    repo: str | None,
    phase: str | None,
    cursor_pairs: tuple[tuple[str, str], ...],
    done: bool,
    title: str | None,
) -> int:
    """Record tickets' phase, cursors, done flag, or title, or a unit's phase and cursors, all or none.

    The comment cursor, the done flag, and the ticket's own phases are the ticket's. The review and ci cursors and the
    phases about a PR, `pushed_no_pr` to `merged`, are a unit's, one per repository the ticket has a PR in. Name several
    KEYs to set each the same; a cursor and a title are one ticket's, so they take one KEY.
    """
    if len(keys) > 1 and (cursor_pairs or title is not None):
        raise click.UsageError("--cursor and --title are one ticket's: name one KEY with them", click_ctx)
    settings = [
        {"key": key, "repo": repo, "phase": phase, "cursors": dict(cursor_pairs), "done": done, "title": title}
        for key in keys
    ]
    return verb(click_ctx, tools.ticket_set, tools.TicketSets, tickets=settings)
