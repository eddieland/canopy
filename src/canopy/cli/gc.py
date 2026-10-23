"""`canopy gc`: what canopy keeps of its own history and caches, and what a pass would remove (DESIGN §26)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import click

from canopy.cli.common import CliError, open_context
from canopy.core import conversation, reports
from canopy.loop import gc, git_gc, vacuum

if TYPE_CHECKING:
    from canopy.core.context import Context
    from canopy.loop.gc import Report

_NAME_WIDTH = 20
_UNIT_WIDTH = 12
_COUNT_WIDTH = 9
_SIZE_WIDTH = 11


@click.command("gc")
@click.option("--dry-run", is_flag=True, help="Report what a pass would remove, and remove nothing.")
@click.option("--json", "as_json", is_flag=True, help="Print the dry run's report as one JSON object instead.")
@click.option("--vacuum", "vacuum_journal", is_flag=True, help="Give the journal's free pages back to its disk.")
@click.option("--git", "git_objects", is_flag=True, help="Pack the primary clones' loose objects and small packs.")
@click.pass_context
def cmd_gc(click_ctx: click.Context, *, dry_run: bool, as_json: bool, vacuum_journal: bool, git_objects: bool) -> int:
    """Report what canopy keeps of its own history, and what a pass with your `[retention]` would remove.

    For each kind: how many there are and their size, then how many a pass would remove and theirs, and the rule that
    removes them. A live tick runs the pass once a day, removing the files and the journal's rows the report counts,
    and rotates canopy.log. By hand, `--dry-run` removes nothing, and `--vacuum` shrinks the journal by its free pages:
    it runs only while no tick is running and no run is live, and when the disk has room for a copy of the journal.
    `--git` packs each primary clone's loose objects and combines its small packs, pruning nothing, and skips a
    repository while a slot of its pool is leased; a dispatch waits for it (ROADMAP M47).

    Raises:
        UsageError: not exactly one of `--dry-run`, `--vacuum`, and `--git` is given.
        CliError: it runs inside one of canopy's ticks or runs, `--vacuum` cannot run now, or git failed in a clone.
    """
    try:
        conversation.check_operator()
    except conversation.Refused as r:
        raise CliError(f"gc refused ({r.guard}): {r.reason}") from None
    if dry_run + vacuum_journal + git_objects != 1:
        raise click.UsageError(
            "give one of `--dry-run`, `--vacuum`, and `--git`; the loop's live ticks run the pass once a day",
        )
    ctx = open_context(click_ctx)
    if git_objects:
        return _git(ctx)
    if vacuum_journal:
        return _vacuum(ctx)
    report = gc.measure(ctx, datetime.now(UTC))
    if as_json:
        click.echo(reports.report_json(dataclasses.asdict(report)))
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


def _git(ctx: Context) -> int:
    """`--git`, printing what it came to in each primary clone.

    Returns:
        0, when git failed in no clone.

    Raises:
        CliError: git failed in a clone.
    """
    done = git_gc.maintain(ctx)
    for repo in done:
        click.echo(f"{repo.repo}: {repo.outcome}: {repo.detail}")
    failed = sum(r.outcome == "failed" for r in done)
    if failed:
        raise CliError(f"git failed in {failed} of {len(done)} primary clones; see above")
    return 0


def _vacuum(ctx: Context) -> int:
    """`--vacuum`, printing the journal's size before and after.

    Returns:
        0, once the journal is vacuumed.

    Raises:
        CliError: it cannot run now.
    """
    try:
        done = vacuum.vacuum(ctx)
    except vacuum.RefusedError as e:
        raise CliError(f"gc --vacuum refused: {e}") from None
    click.echo(f"The journal was {size_text(done.before)}, and is {size_text(done.after)}.")
    if not done.checkpointed:
        click.echo("A reader holds its WAL: it shrinks the rest of the way once the reader lets go.")
    return 0


# The cells of a row: kind, unit, count, size, how many a pass removes, their size, and by what rule.
def _line(*cells: str) -> str:
    name, unit, count, size, removes, removes_size, rule = cells
    left = f"{name:<{_NAME_WIDTH}}{unit:<{_UNIT_WIDTH}}{count:>{_COUNT_WIDTH}}{size:>{_SIZE_WIDTH}}"
    return f"{left}{removes:>{_COUNT_WIDTH}}{removes_size:>{_SIZE_WIDTH}}  {rule}"
