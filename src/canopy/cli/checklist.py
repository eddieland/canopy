"""`canopy checklist`: how workers answered each repository's checklist over the last days (DESIGN §42, ROADMAP M66)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import click

from canopy.cli.common import open_context
from canopy.cli.params import REPO
from canopy.cli.spend import since_text
from canopy.core import checklist_answers, spend
from canopy.core.vocab import ItemAnswer

if TYPE_CHECKING:
    from canopy.core.checklist_answers import Counts

#: The table's count columns after the item: the runs given it, then each answer by its word.
_COUNTS = ("reminded", *(str(a) for a in ItemAnswer))


@click.command("checklist")
@click.option(
    "--days",
    type=click.IntRange(min=1, max=spend.MAX_DAYS),
    default=spend.DEFAULT_DAYS,
    show_default=True,
    metavar="N",
    help="How many local days to read, today's so far included.",
)
@click.option("--repo", type=REPO, help="Count only this repository's list.")
@click.option("--json", "as_json", is_flag=True, help="Print the counts as one JSON object instead.")
@click.pass_context
def cmd_checklist(click_ctx: click.Context, *, days: int, repo: str | None, as_json: bool) -> int:
    """Count, per repository and item of its checklist, how the worker runs of the last days answered it.

    Reminded is the runs given the item, by when they started. Each answered it pass, fixed, held, or n/a, or said
    nothing of it, counted unanswered. An item mostly n/a or never failing is one to reword or drop; one often held is
    one to argue. Why a run held an item is on its run: canopy show run:ID.
    """
    ctx = open_context(click_ctx)
    found = checklist_answers.counts(ctx.conn, datetime.now(UTC), days, repo=repo)
    click.echo(json.dumps(found.as_json(), indent=2) if as_json else "\n".join(render(found)))
    return 0


def render(found: Counts) -> list[str]:
    """The counts as `canopy checklist` prints them: a line per repository and item, in its list's order.

    A `held` answer's reason is the worker's text, and its run's `show` prints it: this table counts it alone.

    Returns:
        Its lines, without line ends.
    """
    days = f"{found.days} day{'s' if found.days != 1 else ''}"
    whose = f"{found.repo}'s checklist" if found.repo is not None else "Checklists"
    head = f"{whose} over {days}, since {since_text(found.since)}, by repository and item."
    if not found.items:
        return [head, "", "No worker run of the window was given a list."]
    repo_width = max(len("repo"), *(len(c.repo) for c in found.items))
    item_width = max(len("item"), *(len(c.item) for c in found.items))
    lines = [head, "", f"{'repo':<{repo_width}}  {'item':<{item_width}}" + "".join(f"  {h}" for h in _COUNTS)]
    lines.extend(
        f"{c.repo:<{repo_width}}  {c.item:<{item_width}}  {c.reminded:>{len('reminded')}}"
        + "".join(f"  {c.of(a):>{len(a)}}" for a in ItemAnswer)
        for c in found.items
    )
    lines.extend(["", "Why a run held an item is on its run: canopy show run:ID."])
    return lines
