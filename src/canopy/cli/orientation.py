"""`canopy orientation`: how much of each run went to finding its way before its work (ROADMAP M70, stage 0)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import click

from canopy.cli.common import open_context
from canopy.cli.spend import since_text
from canopy.core import orientation, spend

if TYPE_CHECKING:
    from canopy.core.orientation import Orientation, RoleOrientation

#: How many days the report reads unless told otherwise: the two weeks the milestone's gate is measured over.
DEFAULT_DAYS = 14
#: The table's columns after the role and the repository, as its head names them.
_COLUMNS = ("runs", "read", "anchored", "calls", "before", "searches", "share", "spend")


@click.command("orientation")
@click.option(
    "--days",
    type=click.IntRange(min=1, max=spend.MAX_DAYS),
    default=DEFAULT_DAYS,
    show_default=True,
    metavar="N",
    help="How many local days to read, by when each run started, today's so far included.",
)
@click.option("--json", "as_json", is_flag=True, help="Print the report as one JSON object instead.")
@click.pass_context
def cmd_orientation(click_ctx: click.Context, *, days: int, as_json: bool) -> int:
    """Measure, per role and repository, what the runs of the last days spent before reaching their work.

    Each ended run's transcript is read for its anchor: for a worker's or a task's run, the first read of a file its
    first edit changed, or the edit when it read none first; for a plan run, the first read of a file its plan names;
    for a review, the first read of a file its diff changes. Before counts the tool calls ahead of the anchor, searches
    the grep and glob calls and shell searches among them, share what part of the run's calls they are, and spend what
    its model calls had cost by then; each is the median of the anchored runs. Read counts the runs whose transcript
    could be read. The gate is stage 1's: a repository's median worker run spends more than a quarter of its calls,
    or more than three searches, before its anchor.
    """
    ctx = open_context(click_ctx)
    found = orientation.measure(
        ctx.conn,
        datetime.now(UTC),
        days,
        state_dir=ctx.state_dir,
        version=ctx.config.runtime.version,
    )
    click.echo(json.dumps(found.as_json(), indent=2) if as_json else "\n".join(render(found)))
    return 0


def render(found: Orientation) -> list[str]:
    """The report as `canopy orientation` prints it: a line per role and repository, then the gate per repository.

    Returns:
        Its lines, without line ends.
    """
    days = f"{found.days} day{'s' if found.days != 1 else ''}"
    head = (
        f"Orientation over {days}, since {since_text(found.since)}, by role and repository: medians before the anchor."
    )
    if not found.roles:
        return [head, "", "No run started and ended in the window."]
    rows = [(r.role, r.repo, *_cells(r)) for r in found.roles]
    heads = ("role", "repository", *_COLUMNS)
    widths = [max(len(h), *(len(row[i]) for row in rows)) for i, h in enumerate(heads)]
    lines = [head, "", _line(heads, widths)]
    lines += [_line(row, widths) for row in rows]
    share, searches = f"{orientation.GATE_SHARE:.0%}", orientation.GATE_SEARCHES
    lines += [
        "",
        f"Gate: a median worker run over {share} of its calls, or over {searches} searches, before its anchor.",
    ]
    if not found.gates:
        lines.append("No worker run in the window.")
    for g in found.gates:
        if g.share is None:
            lines.append(f"{g.repo}: no worker run anchored")
            continue
        verdict = "over the gate" if g.passed else "under the gate"
        runs = f"{g.anchored} run{'s' if g.anchored != 1 else ''}"
        searches = f"{_number(g.searches)} search{'es' if g.searches != 1 else ''}"
        lines.append(f"{g.repo}: {verdict}, a median share of {g.share:.0%} and {searches}, over {runs}")
    return lines


def _cells(r: RoleOrientation) -> tuple[str, ...]:
    """A role's counts and medians as the table prints them, a missing median as `-`.

    Returns:
        Each cell after the role and the repository.
    """
    share = f"{r.share:.0%}" if r.share is not None else "-"
    spent = f"${r.spent:.2f}" if r.spent is not None else "-"
    return (
        str(r.runs),
        str(r.read),
        str(r.anchored),
        _number(r.calls),
        _number(r.before),
        _number(r.searches),
        share,
        spent,
    )


def _number(value: float | None) -> str:
    """A median as the table prints it: whole when it is, else to one place; `-` when there is none.

    Returns:
        The text.
    """
    if value is None:
        return "-"
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def _line(cells: tuple[str, ...], widths: list[int]) -> str:
    """One line of the table, the role and the repository left-aligned and the rest right-aligned.

    Returns:
        The line, without trailing space.
    """
    left = [f"{c:<{w}}" for c, w in zip(cells[:2], widths[:2], strict=True)]
    right = [f"{c:>{w}}" for c, w in zip(cells[2:], widths[2:], strict=True)]
    return "  ".join(left + right).rstrip()
