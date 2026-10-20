"""The overseer's journal commands: `decide`, `queried`, `attention`, `ticket set`, and `mirror`, each `canopy <it>`."""

from __future__ import annotations

import sys

import click

from canopy.cli.common import CliError, Group, OverseerCommand, open_context
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
    validated,
    verb,
)
from canopy.core import conversation
from canopy.loop import tools


@click.command("decide", cls=OverseerCommand)
# click has no optional positional before a required one, so `[KEY] ACTION` is parsed by hand.
@click.argument("words", nargs=-1, required=True, metavar="[KEY] ACTION")
@click.option(
    "--rationale", required=True, type=TextType(), help="Why, in your own words: `canopy decisions` shows it."
)
@click.pass_context
def cmd_decide(click_ctx: click.Context, words: tuple[str, ...], rationale: str) -> int:
    """Record a decision (overseer only).

    ACTION is wait, skip, or done. KEY may be omitted only for a tick-wide skip, whose rationale starts
    `mcp_unavailable:` or `tracker_unsupported:`; a skip with KEY may not give either.
    """
    if len(words) > 2:  # noqa: PLR2004
        raise click.UsageError(f"expected [KEY] ACTION, got {len(words)} arguments", click_ctx)
    key, action = (None, words[0]) if len(words) == 1 else words
    if action not in tools.DECIDE_ACTIONS:
        raise click.UsageError(f"invalid action {action!r}: choose from {', '.join(tools.DECIDE_ACTIONS)}", click_ctx)
    if key is not None and not valid_key(key):
        raise click.UsageError(f"invalid ticket key {key!r}: must match {KEY_RE.pattern}", click_ctx)
    return verb(click_ctx, tools.decide, tools.Decide, key=key, action=action, rationale=rationale)


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
    "--detail", required=True, type=TextType(), help="What the operator needs to know, shown on the attention list."
)
@click.option("--repo", type=REPO, help="The repository of the ticket's unit the item is about, in a workspace.")
@click.option("--pr", "pr", type=PR_URL, help="A PR the loop reviews; in place of KEY for a PR with no ticket.")
@click.pass_context
def cmd_attention(
    click_ctx: click.Context, words: tuple[str, ...], detail: str, repo: str | None, pr: str | None
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
    return verb(click_ctx, tools.attend, tools.Attention, key=key, reason=reason, detail=detail, repo=repo, pr=pr)


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
    type=click.Choice(tools.SETTABLE_PHASES),
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
    return verb(
        click_ctx,
        tools.ticket_set,
        tools.TicketSet,
        key=key,
        repo=repo,
        phase=phase,
        cursors=dict(cursor_pairs),
        done=done,
        title=title,
    )


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
    try:
        # Refused outside a tick before stdin is read, which would wait on a terminal.
        tools.running_tick(ctx)
        said = tools.mirror(
            ctx,
            validated(
                click_ctx,
                tools.Mirror,
                ref=ref,
                comment=comment_id,
                author=author,
                at=at,
                body=_body(ref, body),
            ),
        )
    except tools.Refused as e:
        raise CliError(str(e)) from None
    click.echo(said)
    return 0


def _body(ref: str, body: str | None) -> str:
    """Return a mirrored comment's body: `body`, or else stdin, read only once `ref` is a reference.

    A bad ref is refused without reading stdin, which would wait on an open one: the verb refuses the ref, and records
    it, before it looks at the body, so it is given none.
    """
    if body is not None:
        return body
    try:
        conversation.parse_ref(ref)
    except conversation.Refused:
        return ""
    return sys.stdin.read()
