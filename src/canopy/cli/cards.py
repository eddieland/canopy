"""`canopy cards`: how often running agents' cards went stale over the last days, by role (DESIGN §41, ROADMAP M65)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import click

from canopy.cli.common import open_context
from canopy.cli.spend import since_text
from canopy.core import card_lapses, spend

if TYPE_CHECKING:
    from canopy.core.card_lapses import Lapses

#: The table's count columns after the role, as its head names them.
_COUNTS = ("runs", "carded", "lapsed", "lapses", "ended", "ended stale")


@click.command("cards")
@click.option(
    "--days",
    type=click.IntRange(min=1, max=spend.MAX_DAYS),
    default=spend.DEFAULT_DAYS,
    show_default=True,
    metavar="N",
    help="How many local days to read, today's so far included.",
)
@click.option("--json", "as_json", is_flag=True, help="Print the counts as one JSON object instead.")
@click.pass_context
def cmd_cards(click_ctx: click.Context, *, days: int, as_json: bool) -> int:
    """Count, per role, how often the cards of the runs of the last days went stale.

    A role is a worker's or a planner's run kind, review, or task, and a run is counted by when it started. Carded is
    the runs that posted a card; lapsed, those whose card, or the run with none yet, went stale at least once; lapses,
    each time a card went from fresh to stale, counted once; ended stale, the ended runs whose card was stale as they
    ended. A card is stale after the tool calls or minutes canopy status marks it so.
    """
    ctx = open_context(click_ctx)
    found = card_lapses.counts(ctx.conn, datetime.now(UTC), days)
    click.echo(json.dumps(found.as_json(), indent=2) if as_json else "\n".join(render(found)))
    return 0


def render(found: Lapses) -> list[str]:
    """The counts as `canopy cards` prints them: a line per role.

    Returns:
        Its lines, without line ends.
    """
    days = f"{found.days} day{'s' if found.days != 1 else ''}"
    head = f"Running cards over {days}, since {since_text(found.since)}, by role."
    if not found.roles:
        return [head, "", "No run started in the window."]
    width = max(len("role"), *(len(r.role) for r in found.roles))
    lines = [head, "", f"{'role':<{width}}" + "".join(f"  {h}" for h in _COUNTS)]
    for r in found.roles:
        values = (r.runs, r.carded, r.lapsed, r.lapses, r.ended, r.ended_stale)
        lines.append(f"{r.role:<{width}}" + "".join(f"  {v:>{len(h)}}" for h, v in zip(_COUNTS, values, strict=True)))
    return lines
