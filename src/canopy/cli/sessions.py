"""`canopy sessions [WORDS]`: every session the runtime keeps, listed and found by its title (DESIGN §13, M72).

The record is every session the agent runtime keeps, canopy's runs' and the operator's own. While `sessions.search` is
`titles`, the loop's read of it keeps each one's title, and this lists them from the journal, newest first, or finds
the newest whose title holds every word (`canopy.core.session_list`): those outside canopy, each with the command
that reopens it in the runtime, or, with `--canopy`, canopy's, each with the run that made it. At `text`, words are
found by the index of what each session said, did, and read, which the loop's wait keeps (`canopy.core.session_index`),
the best match first, each hit with a snippet of the message that held them.

`--sizes` measures the record instead, stage 0 of ROADMAP M72: its sessions, its text by part, and, for each cut of the
text, a trial index's size, build time, and search time beside a plain scan's (`canopy.core.session_sizes`).

Either reads what the operator's own sessions were about, in any directory, so only the operator runs it: never inside
a tick or a run (TRUST_MODEL T6), and no tool serves it to an agent (T1).
"""

from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING

import click

from canopy.cli.common import CliError, open_context
from canopy.core import conversation, db, session_index, session_list, session_search, session_sizes
from canopy.runtime import sessions as runtime_sessions
from canopy.runtime.report import count_text

if TYPE_CHECKING:
    from collections.abc import Sequence

    from canopy.core.context import Context
    from canopy.core.session_index import Progress as IndexProgress
    from canopy.core.session_list import Listed, Listing, MadeBy, Progress
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
#: What each table of canopy's runs is called, as a session's run is named.
RUN_LABELS: dict[str, str] = {
    "ticks": "tick",
    "runs": "run",
    "chore_runs": "chore run",
    "review_runs": "review",
    "task_runs": "task run",
    "epic_runs": "epic run",
}
#: What `canopy sessions` says while `sessions.search` keeps no title.
OFF = (
    'sessions.search is off: set it to "titles" in your private config, and the loop\'s next wait reads every '
    "session's title"
)
_NAME_WIDTH = 28
_COUNT_WIDTH = 10


@click.command("sessions")
@click.argument("words", nargs=-1)
@click.option("--canopy", "ours", is_flag=True, help="List canopy's own runs' sessions instead of those outside it.")
@click.option("--archived", is_flag=True, help="List the sessions the runtime archived too.")
@click.option(
    "--limit",
    type=click.IntRange(min=1, max=session_list.MAX_LISTED),
    default=session_list.LISTED,
    show_default=True,
    metavar="N",
    help="List at most N sessions, newest first.",
)
@click.option(
    "--sizes",
    is_flag=True,
    help="Measure the record instead: its sessions, its text by part, and a trial index of each cut, found by WORDS.",
)
@click.option("--json", "as_json", is_flag=True, help="Print the list, or the measurement, as one JSON object instead.")
@click.pass_context
def cmd_sessions(
    click_ctx: click.Context,
    *,
    words: tuple[str, ...],
    ours: bool,
    archived: bool,
    limit: int,
    sizes: bool,
    as_json: bool,
) -> int:
    """List every session the agent runtime keeps, newest first, or find the newest whose title holds every WORDS.

    Lists the sessions outside canopy, your own in any directory, each with the command that reopens it in the runtime;
    with --canopy, canopy's runs' instead, each with the run that made it. A subagent's session is listed under the
    one it ran for; one the runtime archived only with --archived; and one in a directory sessions.exclude names never.
    The loop's wait between ticks reads each session's title while sessions.search is "titles", and this says how far
    that read has come. At "text", the wait also keeps an index of what each session said, did, and read, and WORDS
    finds the sessions whose title and one message hold every word, the best match first, each with a snippet of the
    message read from the runtime's record, and how many more messages hold them.

    With --sizes, measures the runtime's whole record instead, read-only: how many sessions it keeps, canopy's by kind
    of run and the rest by directory; how many characters each part of their text holds; and, for each cut a search
    could index (said, did, read), a trial index built and removed in the state directory, with word positions and
    without: its size, how long it took to build, and how long it takes to find WORDS, beside a plain scan.

    Refused inside a tick or a run.

    Raises:
        CliError: run inside one of canopy's ticks or runs, sessions.search is off, or the record could not be
            measured.
    """
    try:
        conversation.check_operator()
    except conversation.Refused as r:
        raise CliError(f"sessions refused ({r.guard}): {r.reason}") from None
    ctx = open_context(click_ctx)
    if not sizes:
        return _list(ctx, words, ours=ours, archived=archived, limit=limit, as_json=as_json)
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


def listed_lines(
    listing: Listing,
    *,
    ours: bool,
    words: Sequence[str],
    reopen: dict[str, str],
    text: bool = False,
) -> list[str]:
    """The list as `canopy sessions` prints it: a line for each session, and a line under it for its run or command.

    `reopen` is the command that reopens each session outside canopy, by its id. With `text`, the words were found by
    the index of what sessions said, and each hit has its snippet.

    Returns:
        Its lines, without line ends, how far the read has come last.
    """
    whose = "canopy's sessions" if ours else "Sessions outside canopy"
    holds = "that hold" if text else "whose title holds"
    heading = f"{whose} {holds} {' '.join(words)}" if words else whose
    order = "best match first" if text and words else "newest first"
    lines = [f"{heading}, {order}:" if listing.sessions else f"{heading}: none.", ""]
    for session in listing.sessions:
        lines.extend([*_session_lines(session, reopen, depth=0, flat=bool(words)), ""])
    if listing.more:
        lines.append(f"More match than these {len(listing.sessions)}: --limit lists up to {session_list.MAX_LISTED}.")
    lines.append(progress_line(listing.progress))
    return lines


def progress_line(progress: Progress) -> str:
    """How far the loop's read of the runtime's record has come, in a line.

    Returns:
        The line.
    """
    if progress.read_at is None:
        return "The loop has not read the runtime's sessions yet: it reads them while it waits between ticks."
    through = f"every session updated up to {_when(progress.through)}" if progress.through else "no session yet"
    said = f"Read {through}; last read {_when(progress.read_at)}"
    if progress.error is not None:
        said += f", which failed: {progress.error}"
    if not progress.current:
        said += ". Titles are not yet read as sessions.exclude says: the loop's next wait reads them from the first"
    return f"{said}."


def index_line(progress: IndexProgress | None) -> str:
    """How far the index of what sessions said has read the runtime's record, in a line.

    Returns:
        The line.
    """
    if progress is None:
        return "The index of sessions' text is not built yet: the loop's waits between ticks build it."
    if progress.read_at is None:
        return "The index of sessions' text is new: the loop's next wait reads the runtime's sessions into it."
    held = f"The index holds {_count(progress.sessions, 'session')}, {_bytes(progress.size_bytes)}"
    through = f"read up to {_when(progress.through)}" if progress.through else "none read yet"
    said = f"{held}, {through}; last read {_when(progress.read_at)}"
    if not progress.built:
        said += f"; still building, back to {_when(progress.back_to)}" if progress.back_to else "; still building"
    if progress.error is not None:
        said += f", which failed: {progress.error}"
    if progress.passed_over:
        said += f"; {_count(progress.passed_over, 'sandbox record')} passed over, canopy cannot read it"
    if not progress.current:
        said += ". It is not yet built as sessions.exclude says: the loop's next wait builds it again"
    return f"{said}."


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


# The list, printed, or as JSON; the command's exit status.
def _list(ctx: Context, words: Sequence[str], *, ours: bool, archived: bool, limit: int, as_json: bool) -> int:
    search = ctx.config.sessions
    if search.search == "off":
        raise CliError(OFF)
    version = ctx.config.runtime.version
    text = session_index.effective(search.search, version=version) == "text"
    why = session_index.why_titles(version=version) if search.search == "text" else None
    listing = session_list.listing(
        ctx.conn,
        whose="canopy" if ours else "outside",
        state_dir=ctx.state_dir,
        exclude=search.exclude,
        words=words,
        archived=archived,
        limit=limit,
        text=version if text else None,
    )
    index = session_index.progress(ctx.state_dir, search.exclude) if text else None
    reopen = {
        s.session_id: runtime_sessions.reopen(s.session_id, s.directory, version=version)
        for s in _every(listing.sessions)
        if not ours
    }
    if as_json:
        found = {
            "search": "text" if text else "titles",
            "why_titles": why,
            "sessions": [_as_json(s, reopen) for s in listing.sessions],
            "more": listing.more,
            "progress": dataclasses.asdict(listing.progress),
            "index": dataclasses.asdict(index) if index is not None else None,
        }
        click.echo(json.dumps(found, indent=2))
    else:
        for line in listed_lines(listing, ours=ours, words=words, reopen=reopen, text=text):
            click.echo(line)
        if text:
            click.echo(index_line(index))
        if why is not None:
            click.echo(f"{why}.")
    return 0


def _every(sessions: Sequence[Listed]) -> list[Listed]:
    return [each for s in sessions for each in (s, *_every(s.subagents))]


# A session as `--json` prints it: its fields, the command that reopens one outside canopy, and its subagents'.
def _as_json(session: Listed, reopen: dict[str, str]) -> dict[str, object]:
    made = session.made_by
    shown = {f.name: getattr(session, f.name) for f in dataclasses.fields(session)}
    return {
        **shown,
        "made_by": {"table": made.table, "run_id": made.run_id} if made is not None else None,
        "hit": dataclasses.asdict(session.hit) if session.hit is not None else None,
        "reopen": reopen.get(session.session_id),
        "subagents": [_as_json(s, reopen) for s in session.subagents],
    }


# A session's lines: when it started, what it cost, and its title; then the command that reopens it, in its directory,
# or its run and where it ran; then its subagents', indented under it. One found by words names the one it ran for.
def _session_lines(session: Listed, reopen: dict[str, str], *, depth: int, flat: bool) -> list[str]:
    indent = "    " * depth
    title = session.title or "(no title)"
    archived = " (archived)" if session.archived else ""
    lines = [f"{indent}{_when(session.started_at)}  ${session.cost_usd:.2f}  {title}{archived}"]
    if session.hit is not None:
        lines.extend(f"{indent}    {line}" for line in _hit_lines(session.hit))
    if session.session_id in reopen:
        lines.append(f"{indent}    {reopen[session.session_id]}")
    else:
        made = f"{_run(session.made_by)}, " if session.made_by is not None else ""
        lines.append(f"{indent}    {made}session {session.session_id} in {session.directory}")
    if flat and session.parent_id is not None:
        lines.append(f"{indent}    a subagent's, for session {session.parent_id}")
    for below in session.subagents:
        lines.extend(_session_lines(below, reopen, depth=depth + 1, flat=flat))
    return lines


# A hit's snippet, its words marked, and what else it says: how many more messages hold the words, and whether the
# session was indexed in part.
def _hit_lines(hit: session_search.Hit) -> list[str]:
    lines = [f'"{session_search.marked_text(hit.snippet)}"'] if hit.snippet else []
    said = []
    if hit.more:
        said.append(f"{_count(hit.more, 'more message')} {'holds' if hit.more == 1 else 'hold'} them")
    if hit.cut:
        said.append("indexed in part: past its bound, words are not found")
    if said:
        lines.append(f"({'; '.join(said)})")
    return lines


def _run(made: MadeBy) -> str:
    return f"{RUN_LABELS[made.table]} {made.run_id}"


# A journal time as the operator's clock reads it, to the minute.
def _when(stamp: str | None) -> str:
    return db.parse_time(stamp).astimezone().strftime("%Y-%m-%d %H:%M") if stamp else "?"


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
