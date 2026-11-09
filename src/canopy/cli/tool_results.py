"""`canopy tool-results`: what each role's tool calls put into its context (ROADMAP M71, stage 0)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import click

from canopy.cli.common import open_context
from canopy.cli.spend import since_text
from canopy.core import spend, tool_results
from canopy.runtime.report import count_text

if TYPE_CHECKING:
    from canopy.core.tool_results import RoleResults, ToolResult, ToolResults

#: How many days the report reads unless told otherwise: the two weeks the milestone measures over.
DEFAULT_DAYS = 14
#: A tool's columns, as the table's head names them.
_HEADS = ("tool", "calls", "chars", "median", "share", "cut", "unknown", "repeated")
_MIB = 1024 * 1024


@click.command("tool-results")
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
def cmd_tool_results(click_ctx: click.Context, *, days: int, as_json: bool) -> int:
    """Measure, per role and tool, what the tool calls of the last days' runs returned into their context.

    Each ended run's transcript is read: per tool, its calls, the characters they returned in total and at the median,
    and the share of the role's characters that is; cut counts the results the runtime said it cut, unknown those it
    said nothing of, and repeated the reads of a path the same run had read already. A shell call counts as the program
    it runs, as `$ gh run view`. Per role, the characters its runs' `status` calls sent. A log is read to the
    transcript's bound, which the report names, and a run whose log holds more is counted as cut.
    """
    ctx = open_context(click_ctx)
    found = tool_results.measure(
        ctx.conn,
        datetime.now(UTC),
        days,
        state_dir=ctx.state_dir,
        version=ctx.config.runtime.version,
    )
    click.echo(json.dumps(found.as_json(), indent=2) if as_json else "\n".join(render(found)))
    return 0


def render(found: ToolResults) -> list[str]:
    """The report as `canopy tool-results` prints it: per role, a line of its figures, then a line per tool.

    Returns:
        Its lines, without line ends.
    """
    days = f"{found.days} day{'s' if found.days != 1 else ''}"
    lines = [
        f"Tool results over {days}, since {since_text(found.since)}, by role and tool: the characters calls returned.",
        f"Each log is read to its first {_bytes(found.bound)}; a run whose log holds more is read that far, as cut.",
    ]
    if not found.roles:
        return [*lines, "", "No run started and ended in the window."]
    for role in found.roles:
        lines += ["", *_role(role)]
    return lines


def _role(role: RoleResults) -> list[str]:
    """One role's lines: its runs, its calls, its `status` calls, and its tools' table.

    Returns:
        The lines.
    """
    runs = f"{_count(role.runs, 'run')}, {role.read} read"
    if role.cut_logs:
        runs += f", {role.cut_logs} of them to the bound"
    lines = [f"{role.role}: {runs}; {_count(role.calls, 'call')} returned {count_text(role.chars)} characters."]
    if role.status_runs:
        median = count_text(round(role.status_median)) if role.status_median is not None else "-"
        lines.append(
            f"  status: {_count(role.status_calls, 'call')} in {_count(role.status_runs, 'run')} sent "
            f"{count_text(role.status_chars)} characters, a median of {median} a run.",
        )
    if not role.tools:
        return lines
    rows = [_cells(t) for t in role.tools]
    widths = [max(len(h), *(len(row[i]) for row in rows)) for i, h in enumerate(_HEADS)]
    lines += ["  " + _line(_HEADS, widths)]
    lines += ["  " + _line(row, widths) for row in rows]
    return lines


def _cells(tool: ToolResult) -> tuple[str, ...]:
    """A tool's figures as the table prints them.

    Returns:
        Each cell, the tool's name first.
    """
    share = f"{tool.share:.0%}" if tool.share is not None else "-"
    return (
        tool.tool,
        str(tool.calls),
        count_text(tool.chars),
        count_text(round(tool.median)),
        share,
        str(tool.cut),
        str(tool.unknown),
        str(tool.repeated),
    )


def _line(cells: tuple[str, ...], widths: list[int]) -> str:
    """One line of a tool table, the tool left-aligned and the rest right-aligned.

    Returns:
        The line, without trailing space.
    """
    right = [f"{c:>{w}}" for c, w in zip(cells[1:], widths[1:], strict=True)]
    return "  ".join([f"{cells[0]:<{widths[0]}}", *right]).rstrip()


def _count(n: int, noun: str) -> str:
    """A count and its noun, plural unless one.

    Returns:
        `1 run`, `3 runs`.
    """
    return f"{n} {noun}{'s' if n != 1 else ''}"


def _bytes(n: int) -> str:
    """A log's bound for a person: in MiB when it is a whole number of them, else in bytes.

    Returns:
        `32 MiB`, or `5000 bytes`.
    """
    return f"{n // _MIB} MiB" if n >= _MIB and n % _MIB == 0 else f"{n} bytes"
