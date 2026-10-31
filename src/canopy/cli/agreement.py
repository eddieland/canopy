"""`canopy agreement`: how the derivation agreed with the overseer over the last days (DESIGN §30, §37; ROADMAP M38)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import click

from canopy.cli.common import open_context
from canopy.cli.spend import since_text
from canopy.core import spend
from canopy.infra import text
from canopy.loop import agreement

if TYPE_CHECKING:
    from canopy.loop.agreement import Agreement

#: The rows table's count columns after the row.
_ROW_COUNTS = ("decisions", "agree", "disagree", "situations", "disagreeing")
#: The sources table's columns after the source.
_SOURCE_COLUMNS = ("kind", "tick runs", "poll runs", "failed", "median s", "s per tick")
#: How many of the sources table's columns are words, the source's name and its kind, aligned left.
_WORDS = 2


@click.command("agreement")
@click.option(
    "--days",
    type=click.IntRange(min=1, max=spend.MAX_DAYS),
    default=spend.DEFAULT_DAYS,
    show_default=True,
    metavar="N",
    help="How many local days to read, today's so far included.",
)
@click.option("--json", "as_json", is_flag=True, help="Print the agreement as one JSON object instead.")
@click.pass_context
def cmd_agreement(click_ctx: click.Context, *, days: int, as_json: bool) -> int:
    """Count, per row of the phase table, how the derivation agreed with the overseer over the last days.

    A row moves into the harness only on a day of the loop that shows the derivation right on it, each disagreement
    read and attributed. This reads the live ticks of the window that closed ok and ran their overseer: per row, the
    tickets compared, how many agreed and disagreed, and the distinct tickets (situations), a floor, since one PR
    decided each tick is one. Each disagreement is listed once per ticket and reason, with the ticks it held across
    and the overseer's rationale, for the operator to say which side was right. A ticket with a stale subject is
    counted apart. Then each connector source's runs and seconds.
    """
    ctx = open_context(click_ctx)
    found = agreement.agreement(ctx.conn, datetime.now(UTC), days)
    click.echo(json.dumps(found.as_json(), indent=2) if as_json else "\n".join(render(found)))
    return 0


def render(found: Agreement) -> list[str]:
    """The agreement as `canopy agreement` prints it: the rows, the disagreements, then the sources.

    A rationale is the overseer's text, which read tickets and PRs: shown as data, made printable on a line of its own,
    whole, since attributing a disagreement reads all of it.

    Returns:
        Its lines, without line ends.
    """
    head = (
        f"The derivation against the overseer over {_counted(found.days, 'day')}, since {since_text(found.since)}: "
        f"{_counted(found.ticks, 'tick')} compared, {_counted(found.decisions, 'ticket decision')}."
    )
    lines = [head, ""]
    if not found.rows and not found.stale:
        lines.append("No live tick of the window that ran its overseer derived a ticket.")
    else:
        lines.extend(_rows(found))
        lines.append(
            f"Stale, counted apart: {_counted(found.stale, 'decision')} on {_counted(found.stale_tickets, 'ticket')}.",
        )
    lines.append("")
    lines.extend(_disagreements(found))
    lines.append("")
    lines.extend(_sources(found))
    return lines


def _counted(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _rows(found: Agreement) -> list[str]:
    width = max([len("row"), *(len(r.row) for r in found.rows)])
    lines = [f"{'row':<{width}}" + "".join(f"  {h}" for h in _ROW_COUNTS)]
    lines.extend(
        f"{r.row:<{width}}"
        + "".join(
            f"  {n:>{len(h)}}"
            for h, n in zip(_ROW_COUNTS, (r.decisions, r.agrees, r.disagrees, r.situations, r.disagreeing), strict=True)
        )
        for r in found.rows
    )
    return lines


def _disagreements(found: Agreement) -> list[str]:
    if not found.disagreements:
        return ["No disagreement."]
    lines = ["Disagreements, newest first: the ticket, its rows, the ticks, and why; the overseer's rationale below."]
    for d in found.disagreements:
        ticks = f"tick {d.last_tick}" if d.ticks == 1 else f"ticks {d.first_tick}-{d.last_tick} ({d.ticks})"
        rationale = " ".join(text.printable(d.rationale).split()) or "(no rationale)"
        lines.extend([f"  {d.ticket_key}  {', '.join(d.rows)}  {ticks}: {d.why}", f"      {rationale}"])
    return lines


def _sources(found: Agreement) -> list[str]:
    if not found.sources:
        return ["No connector ran in the window."]
    rows = [
        (
            s.source,
            s.kind,
            str(s.tick_runs),
            str(s.poll_runs),
            str(s.failed),
            "-" if s.median_seconds is None else f"{s.median_seconds:.1f}",
            "-" if s.seconds_per_tick is None else f"{s.seconds_per_tick:.1f}",
        )
        for s in found.sources
    ]
    table = [("source", *_SOURCE_COLUMNS), *rows]
    widths = [max(len(row[i]) for row in table) for i in range(len(table[0]))]
    # The source and its kind are words, read from the left; the rest are numbers, lined up on the right.
    return [
        "  ".join(
            cell.ljust(w) if i < _WORDS else cell.rjust(w) for i, (cell, w) in enumerate(zip(row, widths, strict=True))
        )
        for row in table
    ]
