"""`canopy spend`: what agent runs cost over the last days, by kind and by what the ticks bought (ROADMAP M33)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import click

from canopy.cli.common import open_context
from canopy.core import db, reports, spend
from canopy.runtime.report import count_text

if TYPE_CHECKING:
    from canopy.core.spend import Breakdown, Costs, Month

GROUP_LABELS: dict[spend.Group, str] = {
    "idle": "idle",
    "busy": "not idle",
    "hand_run": "hand-run",
    "not_ok": "not ok",
    "dry_run": "dry run",
}
KIND_LABELS: dict[spend.Kind, str] = {
    "overseer": "overseer runs",
    "workers": "worker runs",
    "plans": "plan runs",
    "chores": "chore runs",
    "reviews": "review runs",
    "tasks": "task runs",
}
# The per-day table's columns: a heading and the cost it shows.
_COLUMNS: tuple[tuple[str, str], ...] = (
    ("overseer", "overseer"),
    ("idle", "idle"),
    ("workers", "workers"),
    ("plans", "plans"),
    ("chores", "chores"),
    ("reviews", "reviews"),
    ("tasks", "tasks"),
    ("dry run", "dry_run"),
    ("outside", "outside"),
    ("total", "total"),
)
_DAY_WIDTH = 10
_COST_WIDTH = 9
#: The ticks' tables' last column: how many ran no overseer, left nothing to judge or halted before it (DESIGN §39).
_NO_OVERSEER = "no overseer"
_KEY_WIDTH = 16
# The costliest tickets the text lists; `--json` lists every one.
_TICKETS = 10
# The tools that returned the most the text lists, and the width of their names' column; `--json` lists every one.
_TOOLS = 10
_TOOL_WIDTH = 32
# What `canopy spend` says for a kind's runs whose sessions named no model: those canopy has yet to read (running, not
# read yet, or failed to read), and those read that named none (no longer kept, no session, or no model call).
UNREAD = "(unread)"
NO_MODEL = "(none)"


@click.command("spend")
@click.option(
    "--days",
    type=click.IntRange(min=1, max=spend.MAX_DAYS),
    default=spend.DEFAULT_DAYS,
    show_default=True,
    metavar="N",
    help="How many local days to read, today's so far included.",
)
@click.option("--json", "as_json", is_flag=True, help="Print the breakdown as one JSON object instead.")
@click.pass_context
def cmd_spend(click_ctx: click.Context, *, days: int, as_json: bool) -> int:
    """Print what agent runs cost per day, by kind, and the ticks by what they bought, beside what got done.

    The overseer, workers, plan runs, chores, and reviews, as the agent runtime reported each; dry runs apart from the
    live ticks, and idle ticks' share of the overseer's spend. Then the tickets marked done, the spend for each, and
    the costliest tickets, the tools whose calls put the most into context, and each kind's spend by the models its
    sessions name, each kind's first model calls by week, and every session the runtime keeps, canopy's apart from the
    rest; --json adds every ticket, PR, and tool, each kind's first model calls by definitions snapshot, and their weeks
    by chore and by model.
    """
    ctx = open_context(click_ctx)
    if as_json:
        click.echo(reports.read_spend(ctx, reports.Spend(days=days)))
        return 0
    now = datetime.now(UTC)
    month = spend.budget_month(ctx.conn, now, ctx.config.spend, state_dir=ctx.state_dir)
    for line in render(spend.breakdown(ctx.conn, now, days, state_dir=ctx.state_dir), month):
        click.echo(line)
    return 0


def render(found: Breakdown, month: Month | None = None) -> list[str]:
    """The breakdown as `canopy spend` prints it, led by the month against its budget when one is set.

    Returns:
        Its lines, without line ends.
    """
    since = since_text(found.since)
    lines = [
        f"Spend over {found.days} day{'s' if found.days != 1 else ''}, since {since}, as the runtime reported it.",
        *([budget_text(month)] if month is not None else []),
        "",
        f"{'day':<{_DAY_WIDTH}}" + "".join(f"{title:>{_COST_WIDTH}}" for title, _ in _COLUMNS),
    ]
    lines.extend(_row(day.day, day.costs) for day in found.per_day)
    lines.append(_row("all", found.totals))
    lines.extend(["", *_tickets(found)])
    lines.extend(["", *_tools(found)])
    lines.extend(["", *_models(found)])
    lines.extend(["", *_first_call_weeks(found)])
    lines.extend(["", *_sessions(found)])
    lines.extend(["", _tick_line("ticks", "count", "spent", _NO_OVERSEER)])
    lines.extend(
        _tick_line(GROUP_LABELS[g.group], g.ticks, cost_text(g.cost_usd), g.without_overseer) for g in found.ticks
    )
    if found.idle_share is not None:
        lines.append(f"Idle ticks were {found.idle_share:.0%} of the live overseer's spend.")
    lines.extend(["", _tick_line("woken by", "count", "spent", _NO_OVERSEER)])
    lines.extend(_tick_line(w.by, w.ticks, cost_text(w.cost_usd), w.without_overseer) for w in found.woken)
    if not found.woken:
        lines.append("no tick canopy loop ran")
    unpriced = ", ".join(f"{u.unpriced} of {u.runs} {KIND_LABELS[u.kind]}" for u in found.unpriced if u.unpriced)
    lines.extend(["", f"No cost reported: {unpriced}." if unpriced else "Every run that ended reported a cost."])
    return lines


def budget_text(month: Month) -> str:
    """The month so far against its budget, as `canopy spend` says it.

    Returns:
        The month's spend, then its parts: `This month, 2026-10: $123.45 of a $300 budget (41%), on pace for $280.00.
        Canopy's runs $100.00, outside canopy $23.45.`
    """
    pace = f", on pace for {cost_text(month.projected_usd)}" if month.projected_usd is not None else ""
    over = " Over budget." if month.over else ""
    runs = f"Canopy's runs {cost_text(month.runs_usd or 0.0)}"
    outside = (
        f", outside canopy {cost_text(month.outside_usd)}"
        if month.sessions_read_at is not None
        else "; outside canopy is not counted until canopy loop reads the runtime's sessions"
    )
    return (
        f"This month, {month.month}: {cost_text(month.spent_usd or 0.0)} of a ${month.budget_usd} budget "
        f"({month.percent}%){pace}. {runs}{outside}.{over}"
    )


def _tick_line(label: str, ticks: int | str, spent: str, without: int | str) -> str:
    """A line of the ticks' tables: a group or a cause, how many, what their overseers cost, and how many ran none.

    Returns:
        The line, in the tables' columns.
    """
    return f"{label:<{_DAY_WIDTH}}{ticks:>{_COST_WIDTH}}{spent:>{_COST_WIDTH}}{without:>{len(_NO_OVERSEER) + 2}}"


def since_text(stamp: str) -> str:
    """When a window starts, as a report's first line says it: its first day in local time, and the zone.

    Returns:
        The day and the zone's abbreviation, `2026-10-02 PDT`.
    """
    return db.parse_time(stamp).astimezone().strftime("%Y-%m-%d %Z")


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
    if not found.tickets:
        return lines
    lines.append(f"{'ticket':<{_KEY_WIDTH}}{'runs':>{_COST_WIDTH}}{'spent':>{_COST_WIDTH}}  done")
    lines.extend(
        f"{t.key:<{_KEY_WIDTH}}{t.runs + t.reviews:>{_COST_WIDTH}}{cost_text(t.cost_usd):>{_COST_WIDTH}}"
        + (f"  {spend.local_day(t.done_at)} {t.done}" if t.done_at is not None else "")
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
            count_text(t.result_chars),
            count_text(t.est_tokens),
        )
        for t in found.tools[:_TOOLS]
    )
    if len(found.tools) > _TOOLS:
        lines.append(f"and {len(found.tools) - _TOOLS} more; --json lists every one")
    lines.append(f"Returned is in characters; ~tokens is that over {spend.CHARS_PER_TOKEN}, an estimate.")
    return lines


# Each kind's spend by model, as the runs' sessions name them, read after each run and a few past ones each tick. The
# model column is as wide as its longest name, since a model's name, unlike a tool's, is the point of the line.
def _models(found: Breakdown) -> list[str]:
    if not any(m.model is not None for m in found.models):
        return ["No run's models read yet: canopy reads them from each run's session, a few runs each tick."]
    width = max(len(_model_name(m)) for m in found.models)

    def line(model: str, kind: str, *counts: str) -> str:
        return f"{model:<{width}} {kind:<{_DAY_WIDTH}}" + "".join(f"{c:>{_COST_WIDTH}}" for c in counts)

    lines = [line("model", "kind", "runs", "replies", "spent")]
    lines.extend(
        line(
            _model_name(m),
            m.kind,
            str(m.runs),
            str(m.replies) if m.model is not None else "-",
            cost_text(m.cost_usd),
        )
        for m in found.models
    )
    lines.append("A run on two models counts under each.")
    return lines


def _model_name(row: spend.ModelSpend) -> str:
    if row.model is not None:
        return row.model
    return UNREAD if row.unread else NO_MODEL


# Each kind's first model calls by local ISO week: the median one's size, and what they all read from the cache of what
# they were sent, with the runtime's versions and the definitions snapshots the week's runs used and no earlier week's
# did, where the prefix the runs share may have changed.
def _first_call_weeks(found: Breakdown) -> list[str]:
    weeks = [w for w in found.first_call_weeks if w.by == "kind"]
    if not weeks:
        return ["No first model call recorded."]
    lines = [_week_line("week", "kind", "runs", "sent", "hit") + "  new"]
    lines.extend(
        _week_line(
            w.week,
            w.kind,
            str(w.runs),
            count_text(w.first_call),
            "-" if w.hit_rate is None else f"{w.hit_rate:.0%}",
        )
        + "".join(f"  {part}" for part in _week_changes(w))
        for w in weeks
    )
    lines.extend(
        [
            "Sent is the week's median first call, in tokens; hit is what first calls read from the cache.",
            "--json breaks each kind's weeks down by chore and by model.",
        ],
    )
    return lines


def _week_line(week: str, kind: str, *counts: str) -> str:
    return f"{week:<{_DAY_WIDTH}}{kind:<{_DAY_WIDTH}}" + "".join(f"{c:>{_COST_WIDTH}}" for c in counts)


# What a week's runs used first: a runtime's version or a definitions snapshot the series' earlier weeks did not. A
# kind renders a snapshot for each prompt, persona, and model its runs use, so a change to canopy or its config makes
# them all at once: more than one is counted, and `--json` names them.
def _week_changes(week: spend.FirstCallWeek) -> list[str]:
    digests = week.new_digests
    snapshots = [f"snapshot {d}" for d in digests] if len(digests) <= 1 else [f"{len(digests)} snapshots"]
    return [f"runtime {v}" for v in week.new_runtime_versions] + snapshots


# Every session the runtime keeps that started in the window, canopy's apart from the rest, and where the rest ran, as
# `canopy loop` recorded them between ticks.
def _sessions(found: Breakdown) -> list[str]:
    spent = found.sessions
    if spent is None or spent.read_at is None:
        return ["The runtime's sessions were never read: canopy loop reads them, canopy's and not, between ticks."]
    read = f"read {spend.local_day(spent.read_at)}" + (f", last {spent.status}" if spent.status != "found" else "")
    lines = [
        f"Every runtime session, as its record says ({read}):",
        _session_line("sessions", "count", "spent"),
        _session_line("canopy's runs", str(spent.canopy.sessions), cost_text(spent.canopy.cost_usd)),
        _session_line("outside canopy", str(spent.outside.sessions), cost_text(spent.outside.cost_usd)),
    ]
    # Where the rest ran, the directory last, since a path is as long as it is.
    lines.extend(
        f"{_session_line('', str(d.sessions), cost_text(d.cost_usd))}  {d.directory}" for d in spent.directories
    )
    lines.append("A subagent's session counts with the session it ran for; another workspace's runs are outside.")
    return lines


def _session_line(label: str, *counts: str) -> str:
    return f"{label:<{_KEY_WIDTH}}" + "".join(f"{c:>{_COST_WIDTH}}" for c in counts)


def _tool_line(tool: str, kind: str, *counts: str) -> str:
    return f"{tool:<{_TOOL_WIDTH}} {kind:<{_DAY_WIDTH}}" + "".join(f"{c:>{_COST_WIDTH}}" for c in counts)


def _row(label: str, costs: Costs) -> str:
    cells = [costs.total if name == "total" else getattr(costs, name) for _, name in _COLUMNS]
    return f"{label:<{_DAY_WIDTH}}" + "".join(f"{cost_text(c):>{_COST_WIDTH}}" for c in cells)
