"""`canopy health`: how the agent runs of the last days ended, the newest failures, and what the guards refused."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, assert_never

import click

from canopy.cli.common import open_context
from canopy.cli.spend import cost_text
from canopy.core import health, spend

if TYPE_CHECKING:
    from collections.abc import Sequence

    from canopy.core.health import Failure, Health, Waiver

_KIND_WIDTH = 10
_WHAT_WIDTH = 18
_STATUS_WIDTH = 20
_COUNT_WIDTH = 7
_COST_WIDTH = 9
# The newest failures the text lists; `--json` lists `health.FAILURES`.
_FAILURES = 10


@click.command("health")
@click.option(
    "--days",
    type=click.IntRange(min=1, max=spend.MAX_DAYS),
    default=spend.DEFAULT_DAYS,
    show_default=True,
    metavar="N",
    help="How many UTC days to read, today's so far included.",
)
@click.option("--json", "as_json", is_flag=True, help="Print the report as one JSON object instead.")
@click.pass_context
def cmd_health(click_ctx: click.Context, *, days: int, as_json: bool) -> int:
    """Print how the ticks and runs of the last days ended, the newest failures, and what the guards refused.

    Each kind of run by how it ended and what that cost: the overseer's ticks, workers by kind, triages before a plan,
    chores by name, and reviews. Then the newest ticks and runs that failed, each with its id for `canopy decisions` or
    `canopy show`, the overseer's asks a guard refused, by guard, and the plans triage waived, with what came of each.
    """
    ctx = open_context(click_ctx)
    found = health.report(ctx.conn, datetime.now(UTC), days)
    if as_json:
        click.echo(json.dumps(dataclasses.asdict(found), sort_keys=True))
        return 0
    for line in render(found):
        click.echo(line)
    return 0


def render(found: Health) -> list[str]:
    """The report as `canopy health` prints it.

    Returns:
        Its lines, without line ends.
    """
    lines = [
        f"Runs over {found.days} day{'s' if found.days != 1 else ''}, since {found.since[:10]} UTC, by how they ended."
    ]
    if not found.outcomes:
        return [*lines, "", "No tick or run ended."]
    lines.extend(["", _line("kind", "what", "status", "runs", "spent")])
    lines.extend(
        _line(o.kind, o.what, o.status + (" !" if o.failed else ""), str(o.runs), cost_text(o.cost_usd))
        for o in found.outcomes
    )
    lines.extend(["", *_failures(found.failures), "", *_refusals(found)])
    if found.waivers:
        lines.extend(["", *_waivers(found.waivers)])
    return lines


def _line(kind: str, what: str, status: str, runs: str, spent: str) -> str:
    left = f"{kind:<{_KIND_WIDTH}}{what:<{_WHAT_WIDTH}}{status:<{_STATUS_WIDTH}}"
    return f"{left}{runs:>{_COUNT_WIDTH}}{spent:>{_COST_WIDTH}}"


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


# What names a failure to the command that shows it whole: a tick to `canopy decisions`, the rest to `canopy show`.
def _ref(f: Failure) -> str:
    match f.kind:
        case "overseer":
            return f"tick {f.id} ({f.what})"
        case "workers" | "triage":
            return f"run:{f.id} {f.what} of {f.subject}"
        case "chores":
            return f"chore:{f.what} run {f.id}"
        case "reviews":
            return f"review {f.id} of {f.subject}"
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


# Each waiver, with where it stands and what came of its ticket; none at all with triage off, so no line says so.
def _waivers(waivers: Sequence[Waiver]) -> list[str]:
    lines = ["Plans triage waived:"]
    for w in waivers:
        failed = sum(r.failed for r in w.runs)
        runs = f"{len(w.runs)} run{'s' if len(w.runs) != 1 else ''}" + (f", {failed} failed" if failed else "")
        state = [w.standing.replace("_", " "), *(["done"] if w.done else []), runs]
        if w.impact is not None:
            state.append(f"review {w.review_id} {w.impact}")
        lines.extend([f"  {w.ticket}  run:{w.run_id}  {', '.join(state)}", f"    {w.reason}"])
    return lines
