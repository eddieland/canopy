"""`canopy spend`: what agent runs cost over the last days, by kind and by what the ticks bought (ROADMAP M33)."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import click

from canopy.cli.common import open_context
from canopy.core import spend

if TYPE_CHECKING:
    from canopy.core.spend import Breakdown, Costs

GROUP_LABELS: dict[spend.Group, str] = {
    "idle": "idle",
    "busy": "not idle",
    "hand_run": "hand-run",
    "not_ok": "not ok",
    "dry_run": "dry run",
}
KIND_LABELS: dict[spend.Kind, str] = {
    "overseer": "overseer runs",
    "workers": "worker and split runs",
    "chores": "chore runs",
    "reviews": "review runs",
}
# The per-day table's columns: a heading and the cost it shows.
_COLUMNS: tuple[tuple[str, str], ...] = (
    ("overseer", "overseer"),
    ("idle", "idle"),
    ("workers", "workers"),
    ("chores", "chores"),
    ("reviews", "reviews"),
    ("dry run", "dry_run"),
    ("total", "total"),
)
_DAY_WIDTH = 10
_COST_WIDTH = 9


@click.command("spend")
@click.option(
    "--days",
    type=click.IntRange(min=1, max=spend.MAX_DAYS),
    default=spend.DEFAULT_DAYS,
    show_default=True,
    metavar="N",
    help="How many UTC days to read, today's so far included.",
)
@click.option("--json", "as_json", is_flag=True, help="Print the breakdown as one JSON object instead.")
@click.pass_context
def cmd_spend(click_ctx: click.Context, *, days: int, as_json: bool) -> int:
    """Print what agent runs cost per day, by kind, and the ticks by what they bought.

    The overseer, workers and splits, chores, and reviews, as the agent runtime reported each; dry runs apart from
    the live ticks, and idle ticks' share of the overseer's spend.
    """
    ctx = open_context(click_ctx)
    found = spend.breakdown(ctx.conn, datetime.now(UTC), days)
    if as_json:
        click.echo(json.dumps(as_dict(found), sort_keys=True))
        return 0
    for line in render(found):
        click.echo(line)
    return 0


def as_dict(found: Breakdown) -> dict[str, Any]:
    """The breakdown as JSON-ready values, each set of costs with its total.

    Returns:
        A dict `json.dumps` takes as it is.
    """
    data = dataclasses.asdict(found)
    for day, row in zip(data["per_day"], found.per_day, strict=True):
        day["costs"]["total"] = row.costs.total
    data["totals"]["total"] = found.totals.total
    return data


def render(found: Breakdown) -> list[str]:
    """The breakdown as `canopy spend` prints it.

    Returns:
        Its lines, without line ends.
    """
    since = found.since[:10]
    lines = [
        f"Spend over {found.days} day{'s' if found.days != 1 else ''}, since {since} UTC, as the runtime reported it.",
        "",
        f"{'day':<{_DAY_WIDTH}}" + "".join(f"{title:>{_COST_WIDTH}}" for title, _ in _COLUMNS),
    ]
    lines.extend(_row(day.day, day.costs) for day in found.per_day)
    lines.append(_row("all", found.totals))
    lines.extend(["", f"{'ticks':<{_DAY_WIDTH}}{'count':>{_COST_WIDTH}}{'spent':>{_COST_WIDTH}}"])
    lines.extend(
        f"{GROUP_LABELS[g.group]:<{_DAY_WIDTH}}{g.ticks:>{_COST_WIDTH}}{cost_text(g.cost_usd):>{_COST_WIDTH}}"
        for g in found.ticks
    )
    if found.idle_share is not None:
        lines.append(f"Idle ticks were {found.idle_share:.0%} of the live overseer's spend.")
    lines.extend(["", f"{'woken by':<{_DAY_WIDTH}}{'count':>{_COST_WIDTH}}{'spent':>{_COST_WIDTH}}"])
    lines.extend(
        f"{w.by:<{_DAY_WIDTH}}{w.ticks:>{_COST_WIDTH}}{cost_text(w.cost_usd):>{_COST_WIDTH}}" for w in found.woken
    )
    if not found.woken:
        lines.append("no tick canopy loop ran")
    unpriced = ", ".join(f"{u.unpriced} of {u.runs} {KIND_LABELS[u.kind]}" for u in found.unpriced)
    lines.extend(["", f"No cost reported: {unpriced}."])
    return lines


def cost_text(usd: float | None) -> str:
    """A cost to the cent, `$0.42`, or `-` when nothing reported one.

    Returns:
        The text.
    """
    return "-" if usd is None else f"${usd:.2f}"


def _row(label: str, costs: Costs) -> str:
    cells = [costs.total if name == "total" else getattr(costs, name) for _, name in _COLUMNS]
    return f"{label:<{_DAY_WIDTH}}" + "".join(f"{cost_text(c):>{_COST_WIDTH}}" for c in cells)
