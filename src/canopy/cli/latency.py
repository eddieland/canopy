"""`canopy latency`: how long an external event waited for the tick that acted on it (DESIGN §39, ROADMAP M39)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import click

from canopy.cli.common import open_context
from canopy.cli.spend import since_text
from canopy.core import spend
from canopy.loop import latency

if TYPE_CHECKING:
    from collections.abc import Sequence

    from canopy.loop.latency import By, KindLatency, Latencies

#: The table's columns after the kind, each right-aligned to the widest of its heading and its values.
_COLUMNS: Final = ("items", "acted", "by poll", "not acted", "backfilled", "median", "p90", "from observed")
#: The seconds in a minute and in an hour.
_MINUTE, _HOUR = 60, 3600
#: How the table names each kind of item.
_KIND_NAMES: Final = {
    "review_comment": "review comment",
    "pr_comment": "PR comment",
    "check_run": "check run",
    "status_run": "status run",
}
#: How a split's table heads its first column.
_BY_HEADS: Final = {"day": "local day", "hour": "local hour"}


@click.command("latency")
@click.option(
    "--days",
    type=click.IntRange(min=1, max=spend.MAX_DAYS),
    default=spend.DEFAULT_DAYS,
    show_default=True,
    metavar="N",
    help="How many local days to read, by the item's time at its source, today's so far included.",
)
@click.option(
    "--by",
    type=click.Choice(latency.BY),
    help="Also split every kind together by the local day of the window, or by the local hour of the day across it.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Print the report as one JSON object instead, in seconds, with a row for each item.",
)
@click.pass_context
def cmd_latency(click_ctx: click.Context, *, days: int, by: By | None, as_json: bool) -> int:
    """Measure how long an external event waited for the tick that acted on it, per kind, over the last days.

    An external event is a tracker comment on a ticket, not a worker's, or a review, review comment, or PR comment of
    one of its PRs, with its time at the source. A check run or a commit status's run of such a PR counts too, but has
    no source time: only its wait from when canopy first observed it ended is known. The tick that acted on it is the
    first live tick that recorded a decision about its ticket, the harness's or the overseer's, after canopy first
    observed it; a cursor the harness moved and a refusal are no such decision. The latency runs to that tick's start,
    or to when its own read observed the item, if later. By poll counts the items whose tick a poll of the connectors
    woke; not acted on, the items no tick has. Backfilled counts apart, in no other column, the items canopy's first
    read of their kind on their PR or ticket first observed that were made before canopy observed any item of their
    kind, as when a release begins to read one.
    """
    ctx = open_context(click_ctx)
    found = latency.measure(ctx.conn, datetime.now(UTC), days, by)
    click.echo(json.dumps(found.as_json(), indent=2) if as_json else "\n".join(render(found)))
    return 0


def render(found: Latencies) -> list[str]:
    """The report as `canopy latency` prints it: a line per kind of item, then every kind together, then any split.

    Returns:
        Its lines, without line ends.
    """
    days = f"{found.days} day{'s' if found.days != 1 else ''}"
    head = f"External events over {days}, since {since_text(found.since)}: how long each waited for a tick to act."
    rows = [*found.kinds, found.total]
    lines = [head, "", *_table("kind", [_name(k) for k in rows], rows)]
    if found.by is not None:
        buckets = found.buckets
        lines.extend(["", *_table(_BY_HEADS[found.by], [b.at for b in buckets], [b.total for b in buckets])])
    lines.extend(
        [
            "",
            "Latency runs from the item's time at its source; from observed, from when canopy first observed it.",
            "A check or status run has no source time: its latency is unknown, and the total's reads the other kinds.",
            "Backfilled: made before canopy read its kind, and first observed by its first read; in no other column.",
        ],
    )
    return lines


def duration_text(seconds: float | None) -> str:
    """A duration to the second, as the reports print it: `45s`, `2m05s`, or `1h02m`.

    Returns:
        The text; `-` for none.
    """
    if seconds is None:
        return "-"
    sign, whole = ("-" if seconds < 0 else ""), round(abs(seconds))
    if whole < _MINUTE:
        return f"{sign}{whole}s"
    if whole < _HOUR:
        return f"{sign}{whole // _MINUTE}m{whole % _MINUTE:02d}s"
    return f"{sign}{whole // _HOUR}h{whole % _HOUR // _MINUTE:02d}m"


def _table(heading: str, names: Sequence[str], rows: Sequence[KindLatency]) -> list[str]:
    """A table of `rows`, each named in its first column, under `heading`, with its counts and durations after.

    Returns:
        Its heading line, then a line per row.
    """
    cells = [_cells(r) for r in rows]
    width = max(len(heading), *(len(n) for n in names))
    widths = [max(len(c), *(len(r[i]) for r in cells)) for i, c in enumerate(_COLUMNS)]
    lines = [f"{heading:<{width}}" + "".join(f"  {c:>{w}}" for c, w in zip(_COLUMNS, widths, strict=True))]
    lines.extend(
        f"{n:<{width}}" + "".join(f"  {v:>{w}}" for v, w in zip(r, widths, strict=True))
        for n, r in zip(names, cells, strict=True)
    )
    return lines


def _name(row: KindLatency) -> str:
    # The kind as the table names it.
    return _KIND_NAMES.get(row.kind, row.kind)


def _cells(row: KindLatency) -> tuple[str, ...]:
    # The row's values after its name, in `_COLUMNS`' order.
    return (
        str(row.items),
        str(row.acted),
        str(row.by_poll),
        str(row.not_acted),
        str(row.backfilled),
        duration_text(row.median),
        duration_text(row.p90),
        duration_text(row.observed_median),
    )
