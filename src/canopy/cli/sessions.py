"""`canopy sessions --sizes`: what the runtime's record of every session holds, before a search of it is built (M72).

The record is every session the agent runtime keeps, canopy's runs' and the operator's own (DESIGN §13). This measures
it, stage 0 of ROADMAP M72, so the operator can choose what a full-text index of it should hold: its sessions, its
text by part, and, for each cut of the text, a trial index's size, build time, and search time beside a plain scan's
(`canopy.core.session_sizes`). It reads every session's text, the operator's own in any directory among it, so only
the operator runs it: never inside a tick or a run (TRUST_MODEL T6), and no tool serves it to an agent.
"""

from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING

import click

from canopy.cli.common import CliError, open_context
from canopy.core import conversation, session_sizes
from canopy.runtime.report import count_text

if TYPE_CHECKING:
    from canopy.core.session_sizes import Found, Group, Sizes

#: What each kind of canopy's sessions is called in the text.
OWNER_LABELS: dict[session_sizes.Owner, str] = {
    "overseer": "overseer runs",
    "workers": "worker runs",
    "plans": "plan runs",
    "chores": "chore runs",
    "reviews": "review runs",
    "tasks": "task runs",
    "epics": "epic runs",
    "state_dir": "in the state directory",
}
_NAME_WIDTH = 28
_COUNT_WIDTH = 10


@click.command("sessions")
@click.argument("words", nargs=-1)
@click.option(
    "--sizes",
    is_flag=True,
    help="Measure the record: its sessions, its text by part, and a trial index of each cut, searched for WORDS.",
)
@click.option("--json", "as_json", is_flag=True, help="Print the measurement as one JSON object instead.")
@click.pass_context
def cmd_sessions(click_ctx: click.Context, *, words: tuple[str, ...], sizes: bool, as_json: bool) -> int:
    """Measure every session the agent runtime keeps, canopy's and the operator's own, before a search of them is built.

    With --sizes, reads the runtime's whole record, read-only: how many sessions it keeps, canopy's by kind of run and
    the rest by directory; how many characters each part of their text holds; and, for each cut a search could index
    (said, did, read), a trial index built and removed in the state directory, with word positions and without: its
    size, how long it took to build, and how long it takes to find WORDS, beside a plain scan of the record. Listing
    and finding sessions is not built yet. Refused inside a tick or a run.

    Raises:
        CliError: run inside one of canopy's ticks or runs, or the record could not be measured.
        click.UsageError: --sizes is not given.
    """
    try:
        conversation.check_operator()
    except conversation.Refused as r:
        raise CliError(f"sessions refused ({r.guard}): {r.reason}") from None
    if not sizes:
        raise click.UsageError("canopy sessions measures the runtime's record with --sizes; it lists none yet")
    ctx = open_context(click_ctx)
    found = session_sizes.measure(
        ctx.conn,
        version=ctx.config.runtime.version,
        state_dir=ctx.state_dir,
        query=" ".join(words),
    )
    if as_json:
        click.echo(json.dumps(dataclasses.asdict(found), indent=2))
    else:
        for line in render(found):
            click.echo(line)
    if found.status in {"failed", "unsupported"}:
        raise CliError(found.error or "the runtime's record could not be measured")
    return 0


def render(found: Sizes) -> list[str]:
    """The measurement as `canopy sessions --sizes` prints it.

    Returns:
        Its lines, without line ends; none when the record was neither found nor missing, which the error says.
    """
    match found.status:
        case "missing":
            return ["The runtime keeps no session yet."]
        case "failed" | "unsupported":
            return []
        case "found":
            pass
    lines = [
        f"The runtime's record: {_count(found.databases, 'database')}, {_bytes(found.record_bytes)}.",
        "",
        _row("canopy's sessions", "sessions", "subagents", "archived"),
        *(_group(OWNER_LABELS[session_sizes.OWNERS[n]], g) for n, g in enumerate(found.canopy)),
        "",
        _row("outside canopy, by directory", "sessions", "subagents", "archived"),
        *(_group(g.name, g) for g in found.outside),
        *(["none"] if not found.outside else []),
        "",
        *_passed(found),
        _row("text by part", "canopy's", "outside", "rows"),
        *(
            _row(t.part, count_text(t.canopy_chars), count_text(t.outside_chars), t.canopy_rows + t.outside_rows)
            for t in found.text
        ),
        "Characters of text, as the runtime keeps it.",
        "",
    ]
    searched = (
        f"Searched for {' '.join(found.words)}: how long it took, and in how many sessions a part held every word."
        if found.words
        else "Give words to time a search for them."
    )
    lines.extend([_row("trial index", "size", "build", "search", "found"), searched])
    for cut in found.cuts:
        lines.append(f"{cut.cut} ({', '.join(cut.parts)}): {count_text(cut.chars)} characters in {cut.rows} rows")
        for index in cut.indexes:
            name = "  with positions" if index.positions else "  without"
            lines.append(_row(name, _bytes(index.size_bytes), _took(index.build_seconds), *_search(index.found)))
        if cut.scan is not None:
            lines.append(_row("  plain scan, no index", "", "", *_search(cut.scan)))
    removes = "can" if found.contentless_delete else "cannot"
    lines.extend(
        ["", f"Built with SQLite {found.sqlite_version}, which {removes} remove a row from an index of no text."],
    )
    return lines


# What the measurement passed over, when it passed over anything.
def _passed(found: Sizes) -> list[str]:
    said = [
        f"{_count(found.earlier_only, 'session')} only in the earlier version's tables, not read"
        if found.earlier_only
        else "",
        f"{_count(found.skipped_sessions, 'session')} canopy cannot read" if found.skipped_sessions else "",
        f"{_count(found.skipped_rows, 'row')} of text canopy cannot read" if found.skipped_rows else "",
        f"{_count(found.passed_over, 'sandbox database')} canopy cannot read" if found.passed_over else "",
    ]
    told = [s for s in said if s]
    return [f"Passed over: {'; '.join(told)}.", ""] if told else []


def _group(name: str, group: Group) -> str:
    return _row(name, group.sessions, group.subagents, group.archived)


def _row(name: str, *values: object) -> str:
    return f"{name[:_NAME_WIDTH]:<{_NAME_WIDTH}}" + "".join(f"{v!s:>{_COUNT_WIDTH}}" for v in values)


# How long a search took, and how many sessions it found them in.
def _search(found: Found | None) -> tuple[str, str]:
    return ("", "") if found is None else (_took(found.seconds), str(found.sessions))


def _took(seconds: float) -> str:
    return f"{seconds * 1000:.0f}ms" if seconds < 1 else f"{seconds:.1f}s"


def _bytes(size: int) -> str:
    for unit, scale in (("GB", 1 << 30), ("MB", 1 << 20), ("kB", 1 << 10)):
        if size >= scale:
            return f"{size / scale:.1f}{unit}"
    return f"{size}B"


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"
