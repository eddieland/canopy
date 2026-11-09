"""`canopy plans`: how the last days' plans were approved, and what their PRs needed after (DESIGN §25, #1872)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import click

from canopy.cli.common import open_context
from canopy.cli.latency import duration_text
from canopy.cli.spend import since_text
from canopy.core import plan_report, spend
from canopy.core.plan_report import Outcome

if TYPE_CHECKING:
    from collections.abc import Collection
    from datetime import timedelta

    from canopy.core.plan_report import Group, Length, Plans
    from canopy.core.vocab import PlannerApproval

#: How many days the report reads unless told otherwise: the Plans page's shorter window, since a week holds few plans.
DEFAULT_DAYS = 30
#: The approvals table's columns after the level and how, as its head names them.
_GROUP_COLUMNS = (
    "plans",
    "edited",
    "commented",
    "replanned",
    "to approve",
    "lines",
    "words",
    "built",
    "resumed",
    "resumes",
    "done",
)
#: The length table's columns after the length.
_LENGTH_COLUMNS = ("plans", "to approve", "as written")
#: How the tables name each way a plan went.
_HOW = {
    Outcome.PLANNER: "planner",
    Outcome.AS_WRITTEN: "as written",
    Outcome.REVISED: "revised",
    Outcome.REPLACED: "sent back",
    Outcome.DROPPED: "dropped",
    Outcome.WAITING: "waiting on you",
}
#: How the table names the level of a plan run from before canopy kept it.
_UNRECORDED = "unrecorded"


@click.command("plans")
@click.option(
    "--days",
    type=click.IntRange(min=1, max=spend.MAX_DAYS),
    default=DEFAULT_DAYS,
    show_default=True,
    metavar="N",
    help="How many local days to read, by when each plan was written, today's so far included.",
)
@click.option("--json", "as_json", is_flag=True, help="Print the report as one JSON object instead, every plan in it.")
@click.pass_context
def cmd_plans(click_ctx: click.Context, *, days: int, as_json: bool) -> int:
    """Measure how the ticket plans of the last days were approved, by the level the planner was offered.

    Each plan went one way: approved by its planner, on its word that it needs no review; by you as written, the
    ticket's first plan with no edit and no comment; revised, approved after you edited it, commented on it, or sent
    an earlier plan back; sent back, replaced by a newer plan; dropped, superseded with nothing after; or still waiting
    on you. The approved ones are grouped by the level of `policy.planner_may_approve` their plan run was offered, which
    the run records, and by how they went: how many were edited, commented on, or replaced a plan sent back, the median
    time from written to approved, their median length in the plan editor's lines and words, measured from the file as
    the planner wrote it, how many an implement followed (built), how many of those needed a resume, and every resume
    their tickets started after the approval. Then the plans you approved by length, with the median time you took.
    Feedback plans are not counted.
    """
    ctx = open_context(click_ctx)
    found = plan_report.report(ctx.conn, ctx.state_dir, datetime.now(UTC), days)
    level = ctx.config.policy.planner_may_approve
    if as_json:
        click.echo(json.dumps({**found.as_json(), "planner_may_approve": level}, indent=2))
    else:
        click.echo("\n".join(render(found, level)))
    return 0


def render(found: Plans, level: PlannerApproval) -> list[str]:
    """The report as `canopy plans` prints it: the approvals by level and how, then by length.

    `level` is where `policy.planner_may_approve` is now, which the last line names.

    Returns:
        Its lines, without line ends.
    """
    days, since = _plural(found.days, "day"), since_text(found.since)
    head = f"Plans written over {days}, since {since}: how they were approved, and what their PRs needed after."
    if not found.plans:
        return [head, "", "No plan was written in the window."]
    lines = [head, f"{_counts(found)}.", "", "Approved, by the level their planner was offered and how they went:"]
    if found.groups:
        rows = [(_level(g.level), _HOW[g.outcome], *_group_cells(g)) for g in found.groups]
        lines += _table(("level", "how", *_GROUP_COLUMNS), rows, left=2)
    else:
        lines.append("None was approved.")
    lines += ["", f"Approved by you, by length in the plan editor's lines ({plan_report.PAGE_LINES} a page):"]
    if found.lengths:
        lines += _table(("lines", *_LENGTH_COLUMNS), [(_bounds(n), *_length_cells(n)) for n in found.lengths], left=1)
    else:
        lines.append("None was measured.")
    return [
        *lines,
        "",
        "Built counts the plans an implement followed; resumed, those of them whose ticket then needed a resume. A",
        "ticket's resumes keep coming until it is done: done counts the plans whose resumes are final.",
        f"policy.planner_may_approve is {level} now.",
    ]


def _counts(found: Plans) -> str:
    """The window's plans in a few words: how many there were, how many were approved, and how many went each other way.

    Returns:
        The text, `6 plans: 3 approved, 1 by the planner; 1 sent back, 1 waiting on you`, the ways none went left out.
    """
    approved = f"{sum(found.count(o) for o in plan_report.APPROVED)} approved"
    if by_planner := found.count(Outcome.PLANNER):
        approved += f", {by_planner} by the planner"
    rest = [f"{n} {_HOW[o]}" for o in (Outcome.REPLACED, Outcome.DROPPED, Outcome.WAITING) if (n := found.count(o))]
    text = f"{_plural(len(found.plans), 'plan')}: {approved}"
    return f"{text}; {', '.join(rest)}" if rest else text


def _group_cells(g: Group) -> tuple[str, ...]:
    """A group's counts and medians as the table prints them, a missing median as `-`.

    Returns:
        Each cell after the level and how.
    """
    return (
        str(g.plans),
        str(g.edited),
        str(g.commented),
        str(g.replanned),
        # The planner approves a plan as it is recorded, so its time says nothing.
        _wait(None if g.outcome is Outcome.PLANNER else g.median_to_approve),
        _number(g.median_lines),
        _number(g.median_words),
        str(g.implemented),
        str(g.with_resume),
        str(g.resumes),
        str(g.done),
    )


def _length_cells(n: Length) -> tuple[str, ...]:
    """A length bucket's counts and median as the table prints them.

    Returns:
        Each cell after the length.
    """
    return (str(n.plans), _wait(n.median_to_approve), str(n.as_written))


def _table(heads: tuple[str, ...], rows: Collection[tuple[str, ...]], *, left: int) -> list[str]:
    """A table, its first `left` columns left-aligned and the rest right-aligned, each as wide as its widest cell.

    Returns:
        Its head, then a line per row, without trailing space.
    """
    widths = [max(len(h), *(len(row[i]) for row in rows)) for i, h in enumerate(heads)]

    def line(cells: tuple[str, ...]) -> str:
        aligned = [f"{c:<{w}}" if i < left else f"{c:>{w}}" for i, (c, w) in enumerate(zip(cells, widths, strict=True))]
        return "  ".join(aligned).rstrip()

    return [line(heads), *(line(row) for row in rows)]


def _level(level: PlannerApproval | None) -> str:
    """A level as the table names it: its value, or `unrecorded` for a run from before canopy kept it.

    Returns:
        The text.
    """
    return _UNRECORDED if level is None else str(level)


def _bounds(n: Length) -> str:
    """A length bucket's lines, `50-99`, or `300+` for the last.

    Returns:
        The text.
    """
    return f"{n.low}+" if n.high is None else f"{n.low}-{n.high - 1}"


def _wait(span: timedelta | None) -> str:
    """A median time to approve, `-` for none.

    Returns:
        The text.
    """
    return duration_text(None if span is None else span.total_seconds())


def _number(value: int | None) -> str:
    """A median count, `-` when nothing was measured.

    Returns:
        The text.
    """
    return "-" if value is None else str(value)


def _plural(n: int, noun: str) -> str:
    """`n` and `noun`, plural unless `n` is 1.

    Returns:
        The text, `1 day` or `30 days`.
    """
    return f"{n} {noun}{'s' if n != 1 else ''}"
