"""`canopy spend`: what agent runs cost over the last days, by kind and by what the ticks bought (ROADMAP M33)."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import click

from canopy.cli.common import open_context
from canopy.core import agent_output, spend

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
    "triage": "triage runs",
    "chores": "chore runs",
    "reviews": "review runs",
}
# The per-day table's columns: a heading and the cost it shows.
_COLUMNS: tuple[tuple[str, str], ...] = (
    ("overseer", "overseer"),
    ("idle", "idle"),
    ("workers", "workers"),
    ("triage", "triage"),
    ("chores", "chores"),
    ("reviews", "reviews"),
    ("dry run", "dry_run"),
    ("total", "total"),
)
_DAY_WIDTH = 10
_COST_WIDTH = 9
_KEY_WIDTH = 16
# The costliest tickets the text lists; `--json` lists every one.
_TICKETS = 10
# The tools that returned the most the text lists, and the width of their names' column; `--json` lists every one.
_TOOLS = 10
_TOOL_WIDTH = 32


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
    """Print what agent runs cost per day, by kind, and the ticks by what they bought, beside what got done.

    The overseer, workers and splits, triages before a plan, chores, and reviews, as the agent runtime reported each;
    dry runs apart from the live ticks, and idle ticks' share of the overseer's spend. Then the tickets marked done,
    the spend for each, the plans triage waived, and the costliest tickets, and the tools whose calls put the most
    into context; --json adds every ticket, PR, and tool, and each kind's first model calls by definitions snapshot.
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
    lines.extend(["", *_tickets(found)])
    lines.extend(["", *_tools(found)])
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
    unpriced = ", ".join(f"{u.unpriced} of {u.runs} {KIND_LABELS[u.kind]}" for u in found.unpriced if u.unpriced)
    lines.extend(["", f"No cost reported: {unpriced}." if unpriced else "Every run that ended reported a cost."])
    return lines


def cost_text(usd: float | None) -> str:
    """A cost to the cent, `$0.42`, or `-` when nothing reported one.

    Returns:
        The text.
    """
    return "-" if usd is None else f"${usd:.2f}"


# The tickets marked done, what the window cost for each, and the costliest tickets with what their own runs cost.
def _tickets(found: Breakdown) -> list[str]:
    if found.done:
        each = f", {cost_text(found.per_done)} of all spend for each" if found.per_done is not None else ""
        lines = [f"{found.done} ticket{'s' if found.done != 1 else ''} marked done{each}."]
    else:
        lines = ["No ticket marked done."]
    if found.waived:
        plans = "plan" if found.waived == 1 else "plans"
        lines.append(f"Triage waived {found.waived} {plans}, each a planner run saved.")
    if not found.tickets:
        return lines
    lines.append(f"{'ticket':<{_KEY_WIDTH}}{'runs':>{_COST_WIDTH}}{'spent':>{_COST_WIDTH}}  done")
    lines.extend(
        f"{t.key:<{_KEY_WIDTH}}{t.runs + t.reviews:>{_COST_WIDTH}}{cost_text(t.cost_usd):>{_COST_WIDTH}}"
        + (f"  {t.done_at[:10]} {t.done}" if t.done_at is not None else "")
        for t in found.tickets[:_TICKETS]
    )
    if len(found.tickets) > _TICKETS:
        lines.append(f"and {len(found.tickets) - _TICKETS} more; --json lists every one")
    return lines


# The tools whose calls returned the most, by kind, with their calls and errors, and the tokens that is, estimated.
def _tools(found: Breakdown) -> list[str]:
    if not found.tools:
        return ["No tool call recorded."]
    lines = [_tool_line("tool", "kind", "calls", "errors", "returned", "~tokens")]
    lines.extend(
        _tool_line(
            t.tool,
            t.kind,
            str(t.calls),
            str(t.errors),
            agent_output.count_text(t.result_chars),
            agent_output.count_text(t.est_tokens),
        )
        for t in found.tools[:_TOOLS]
    )
    if len(found.tools) > _TOOLS:
        lines.append(f"and {len(found.tools) - _TOOLS} more; --json lists every one")
    lines.append(f"Returned is in characters; ~tokens is that over {spend.CHARS_PER_TOKEN}, an estimate.")
    return lines


def _tool_line(tool: str, kind: str, *counts: str) -> str:
    return f"{tool:<{_TOOL_WIDTH}} {kind:<{_DAY_WIDTH}}" + "".join(f"{c:>{_COST_WIDTH}}" for c in counts)


def _row(label: str, costs: Costs) -> str:
    cells = [costs.total if name == "total" else getattr(costs, name) for _, name in _COLUMNS]
    return f"{label:<{_DAY_WIDTH}}" + "".join(f"{cost_text(c):>{_COST_WIDTH}}" for c in cells)
