"""`canopy health`: how the agent runs of the last days ended, the newest failures and their causes, and refusals."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, assert_never

import click

from canopy.cli.common import open_context
from canopy.cli.spend import cost_text, since_text
from canopy.core import db, health, reports, spend

if TYPE_CHECKING:
    from collections.abc import Sequence

    from canopy.core.health import Cause, Duration, Failure, Health

_KIND_WIDTH = 10
_WHAT_WIDTH = 18
_STATUS_WIDTH = 20
_COUNT_WIDTH = 7
_COST_WIDTH = 9
_LENGTH_WIDTH = 9
# The newest failures the text lists; `--json` lists `health.FAILURES`.
_FAILURES = 10
# What the failures an agent's own words explained are counted as.
_OTHER = "other: an agent's summary, or no note"


@click.command("health")
@click.option(
    "--days",
    type=click.IntRange(min=1, max=spend.MAX_DAYS),
    default=spend.DEFAULT_DAYS,
    show_default=True,
    metavar="N",
    help="How many local days to read, today's so far included.",
)
@click.option("--json", "as_json", is_flag=True, help="Print the report as one JSON object instead.")
@click.pass_context
def cmd_health(click_ctx: click.Context, *, days: int, as_json: bool) -> int:
    """Print how the ticks and runs of the last days ended, the newest failures, and what the guards refused.

    Each kind of run by how it ended and what that cost: the overseer's ticks, workers by kind, plan runs, chores by
    name, and reviews. Then the newest ticks and runs that failed, each with its id for `canopy decisions` or
    `canopy show`, every failure by the harness's note on it, and the overseer's asks a guard refused, by guard. Between
    them, how long each sort of run took against its timeout.
    """
    ctx = open_context(click_ctx)
    if as_json:
        click.echo(reports.read_health(ctx, reports.Health(days=days)))
        return 0
    now = datetime.now(UTC)
    # One snapshot, so a run ending between the two reads is in both tables or neither.
    with db.read_snapshot(ctx.conn):
        found = health.report(ctx.conn, now, days)
        durations = health.durations(ctx.conn, now, days, ctx.config)
    for line in render(found, durations):
        click.echo(line)
    return 0


def render(found: Health, durations: Sequence[Duration] = ()) -> list[str]:
    """The report as `canopy health` prints it, with how long each sort of run took if `durations` holds any.

    Returns:
        Its lines, without line ends.
    """
    days = f"{found.days} day{'s' if found.days != 1 else ''}"
    lines = [f"Runs over {days}, since {since_text(found.since)}, by how they ended."]
    if not found.outcomes:
        return [*lines, "", "No tick or run ended."]
    lines.extend(["", _line("kind", "what", "status", "runs", "spent")])
    lines.extend(
        _line(o.kind, o.what, o.status + (" !" if o.failed else ""), str(o.runs), cost_text(o.cost_usd))
        for o in found.outcomes
    )
    if durations:
        lines.extend(["", *_durations(durations)])
    lines.extend(["", *_failures(found.failures)])
    if found.causes:
        lines.extend(["", *_causes(found.causes)])
    lines.extend(["", *_refusals(found)])
    return lines


def _line(kind: str, what: str, status: str, runs: str, spent: str) -> str:
    left = f"{kind:<{_KIND_WIDTH}}{what:<{_WHAT_WIDTH}}{status:<{_STATUS_WIDTH}}"
    return f"{left}{runs:>{_COUNT_WIDTH}}{spent:>{_COST_WIDTH}}"


# Each sort's lengths in minutes against its timeout, `-` for none; a median at three quarters of it or more is flagged.
def _durations(durations: Sequence[Duration]) -> list[str]:
    lines = [
        "How long they took, in minutes (! a median at three quarters of the timeout or more):",
        _length_line("kind", "what", "median", "p90", "longest", "timeouts", "limit"),
    ]
    for d in durations:
        limit = d.limit_minutes
        close = limit is not None and d.median_minutes >= health.BANDS[2] * limit
        lines.append(
            _length_line(
                d.kind,
                d.what,
                f"{d.median_minutes:.1f}" + (" !" if close else ""),
                f"{d.p90_minutes:.1f}",
                f"{d.longest_minutes:.1f}",
                str(d.timeouts),
                "-" if limit is None else str(limit),
            ),
        )
    return lines


def _length_line(kind: str, what: str, *numbers: str) -> str:
    return f"{kind:<{_KIND_WIDTH}}{what:<{_WHAT_WIDTH}}" + "".join(f"{n:>{_LENGTH_WIDTH}}" for n in numbers)


# The newest failures, each with what `canopy decisions` or `canopy show` takes to read it whole.
def _failures(failures: Sequence[Failure]) -> list[str]:
    if not failures:
        return ["No tick or run failed."]
    lines = ["Newest failures (! above):"]
    for f in failures[:_FAILURES]:
        lines.append(f"  {f.started_at[:16].replace('T', ' ')}  {_ref(f)}  {f.status}")
        if f.note:
            lines.append(f"    {f.note}")
    if len(failures) > _FAILURES:
        lines.append(f"  and {len(failures) - _FAILURES} more; --json lists up to {health.FAILURES}")
    return lines


# Every failure by the harness's note, the most first, each with its newest to read whole; the agents' own words last.
def _causes(causes: Sequence[Cause]) -> list[str]:
    lines = ["Failures by cause:"]
    for c in causes:
        note = c.note if c.note is not None else _OTHER
        lines.extend((f"  {c.runs:>{_COUNT_WIDTH - 2}}  {note}", f"    {', '.join(c.kinds)}; latest {_ref(c.latest)}"))
    return lines


# What names a failure to the command that shows it whole: a tick to `canopy decisions`, the rest to `canopy show`.
def _ref(f: Failure) -> str:
    match f.kind:
        case "overseer":
            return f"tick {f.id} ({f.what})"
        case "workers" | "plans":
            return f"run:{f.id} {f.what} of {f.subject}"
        case "chores":
            return f"chore:{f.what} run {f.id}"
        case "reviews":
            return f"review {f.id} of {f.subject}"
        case "tasks":
            return f"{f.subject} run {f.id}"
        case _:
            assert_never(f.kind)


def _refusals(found: Health) -> list[str]:
    if not found.refusals:
        return ["No guard refused anything."]
    lines = ["Refused by a guard:"]
    lines.extend(
        f"  {r.guard}: {r.decisions} time{'s' if r.decisions != 1 else ''} in {r.ticks} tick"
        f"{'s' if r.ticks != 1 else ''}, last in tick {r.last_tick}"
        for r in found.refusals
    )
    return lines
