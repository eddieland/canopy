"""`canopy gc`: what canopy keeps of its own history and caches, and what a pass would remove (DESIGN §26)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import click

from canopy.cli.common import CliError, open_context
from canopy.cli.render import report_json
from canopy.core import conversation
from canopy.loop import gc

if TYPE_CHECKING:
    from canopy.loop.gc import Report

_NAME_WIDTH = 20
_UNIT_WIDTH = 12
_COUNT_WIDTH = 9
_SIZE_WIDTH = 11


@click.command("gc")
@click.option("--dry-run", is_flag=True, help="Report what a pass would remove, and remove nothing.")
@click.option("--json", "as_json", is_flag=True, help="Print the report as one JSON object instead.")
@click.pass_context
def cmd_gc(click_ctx: click.Context, *, dry_run: bool, as_json: bool) -> int:
    """Report what canopy keeps of its own history, and what a pass with your `[retention]` would remove.

    For each kind: how many there are and their size, then how many a pass would remove and theirs, and the rule that
    removes them. A live tick runs the pass once a day, removing the files the report counts, and rotates canopy.log;
    by hand, only the dry run is built yet, and it removes nothing (ROADMAP M47).

    Raises:
        UsageError: `--dry-run` is not given.
        CliError: it runs inside one of canopy's ticks or runs.
    """
    try:
        conversation.check_operator()
    except conversation.Refused as r:
        raise CliError(f"gc refused ({r.guard}): {r.reason}") from None
    if not dry_run:
        raise click.UsageError(
            "only `canopy gc --dry-run` is built yet; the loop's live ticks run the pass once a day",
        )
    ctx = open_context(click_ctx)
    report = gc.measure(ctx, datetime.now(UTC))
    if as_json:
        click.echo(report_json(dataclasses.asdict(report)))
        return 0
    for line in render(report):
        click.echo(line)
    return 0


def render(report: Report) -> list[str]:
    """The report as `canopy gc --dry-run` prints it.

    Returns:
        Its lines, without line ends.
    """
    lines = [
        f"What canopy keeps, at {report.at[:16].replace('T', ' ')} UTC, and what a pass would remove.",
        "",
        _line("kind", "unit", "count", "size", "removes", "frees", "by"),
    ]
    lines.extend(
        _line(
            k.name,
            k.unit,
            str(k.count),
            size_text(k.size),
            str(k.removable),
            size_text(k.removable_size),
            k.rule,
        )
        for k in report.kinds
    )
    lines.extend(["", f"The journal is {size_text(report.journal_size)}."])
    lines.extend(report.notes)
    lines.append("Nothing was removed: this is a dry run.")
    return lines


def size_text(size: int) -> str:
    """A size in bytes as a person reads it: `812 B`, `3.4 KiB`, `1.2 GiB`.

    Returns:
        The size in the largest binary unit it reaches, to one decimal place past bytes.
    """
    if size < gc.KIB:
        return f"{size} B"
    value, units = size / gc.KIB, ["KiB", "MiB", "GiB"]
    while value >= gc.KIB and len(units) > 1:
        value /= gc.KIB
        units.pop(0)
    return f"{value:.1f} {units[0]}"


# The cells of a row: kind, unit, count, size, how many a pass removes, their size, and by what rule.
def _line(*cells: str) -> str:
    name, unit, count, size, removes, removes_size, rule = cells
    left = f"{name:<{_NAME_WIDTH}}{unit:<{_UNIT_WIDTH}}{count:>{_COUNT_WIDTH}}{size:>{_SIZE_WIDTH}}"
    return f"{left}{removes:>{_COUNT_WIDTH}}{removes_size:>{_SIZE_WIDTH}}  {rule}"
