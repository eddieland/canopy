"""What each role's tool calls put into its context (ROADMAP M71, stage 0's measurement).

From the transcripts canopy keeps (§13), per role and per tool, over the runs that started in a window of local days
and ended (`spend.window`): the calls, the characters of what they returned, in total and at the median, each tool's
share of its role's characters, how many results the runtime said it cut and how many it said nothing of, and the reads
of a path the same run had read already; and per role, the characters each run's `status` calls sent (§41).

A role is a worker's or a planner's run kind, `review`, `task`, `epic-plan`, `chore`, or `overseer`. A call of the
runtime's shell counts as the program it runs, as `$ gh run view`: its first stage that does more than move or set up
the shell, the program named without its directory, and for a program whose subcommands differ in what they read, as
`gh`'s and git's do, the subcommand's words up to the first that is not one. Characters are of what the runtime printed
of each call, whole, read from each log up to the transcript's bound (`transcript.MAX_BYTES`): a run whose log holds
more is read that far and counted as cut. Read only; a run whose log is gone or refused, or that recorded no session,
is counted and not read. `canopy tool-results` prints it, or `--json` for `MEASUREMENTS.md`.
"""

from __future__ import annotations

import posixpath
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, LiteralString

from canopy.core import cards, db, hostgit, records, spend, sql
from canopy.core.vocab import RunKind
from canopy.runtime import report, transcript

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import datetime

    from canopy.runtime.implementation import Version
    from canopy.runtime.transcript import Use, Uses

#: The roles that are not a run kind: a review's run, a one-off task's, an epic's planner's, a chore's, and the
#: overseer's run in a tick.
REVIEW = "review"
TASK = "task"
EPIC_PLAN = "epic-plan"
CHORE = "chore"
OVERSEER = "overseer"
#: What a shell call's row is named by: this, then the program it runs; `?` for a command with none canopy can read.
SHELL_ROW = "$ "
UNREAD_PROGRAM = "?"
#: The programs a shell command's row names by their subcommands too, and how many words of them at most.
SUBCOMMAND_WORDS: Mapping[str, int] = {"gh": 2, hostgit.PROGRAM: 1}
#: The programs of a stage that only moves or sets up the shell, which a row passes over for the stage after it.
SETUP_PROGRAMS = frozenset({"cd", "pushd", "popd", "export", "set", "source", "."})
#: A word that is a subcommand: `run` or `log-failed`, not `123`, `main...HEAD`, or a path.
_SUBCOMMAND_RE = re.compile(r"[a-z][a-z0-9-]*")


@dataclass(frozen=True)
class ToolResult:
    """One tool's calls in one role: what they returned, and how much of it the runtime said it cut."""

    #: The tool as the runtime names it, or `$ ` and the program a shell call ran.
    tool: str
    calls: int
    #: The characters every call returned, the median call's, and the share of its role's they are; None for a role
    #: whose calls returned nothing.
    chars: int
    median: float
    share: float | None
    #: The results the runtime said it cut, and those it said nothing of.
    cut: int
    unknown: int
    #: The completed reads of a path its run had read already.
    repeated: int

    def as_json(self) -> dict[str, object]:
        """Return the tool's figures as one JSON object.

        Returns:
            `tool`, `calls`, `result_chars`, `median_chars`, `share`, `cut`, `cut_unknown`, and `repeated_reads`.
        """
        return {
            "tool": self.tool,
            "calls": self.calls,
            "result_chars": self.chars,
            "median_chars": self.median,
            "share": self.share,
            "cut": self.cut,
            "cut_unknown": self.unknown,
            "repeated_reads": self.repeated,
        }


@dataclass(frozen=True)
class RoleResults:
    """The runs of one role: what their calls returned, by tool, and what their `status` calls sent."""

    #: A worker's or a planner's run kind, or one of the roles this module names.
    role: str
    #: The runs that ended in the window, those whose log was read, and those among them read only to the bound.
    runs: int
    read: int
    cut_logs: int
    #: Every call of the read runs, the characters they returned, and the repeated reads among them.
    calls: int
    chars: int
    repeated: int
    #: The read runs that called `status`, its calls, the characters those sent, and the median run's.
    status_runs: int
    status_calls: int
    status_chars: int
    status_median: float | None
    #: Each tool the role's runs called, the most characters first.
    tools: Sequence[ToolResult] = ()

    def as_json(self) -> dict[str, object]:
        """Return the role's figures and its tools' as one JSON object.

        Returns:
            `role`, `runs`, `read`, `cut_logs`, `calls`, `result_chars`, `repeated_reads`, `status` (its `runs`,
            `calls`, `chars`, and `median_chars`), and `tools`.
        """
        return {
            "role": self.role,
            "runs": self.runs,
            "read": self.read,
            "cut_logs": self.cut_logs,
            "calls": self.calls,
            "result_chars": self.chars,
            "repeated_reads": self.repeated,
            "status": {
                "runs": self.status_runs,
                "calls": self.status_calls,
                "chars": self.status_chars,
                "median_chars": self.status_median,
            },
            "tools": [t.as_json() for t in self.tools],
        }


@dataclass(frozen=True)
class ToolResults:
    """The runs that started in a window, `[since, until)`, and ended, by role, each log read to `bound` bytes."""

    since: str
    until: str
    days: int
    bound: int
    #: Each role a run of the window had: the run kinds in their vocabulary's order, then the others as named here.
    roles: Sequence[RoleResults] = ()

    def as_json(self) -> dict[str, object]:
        """Return the report as one JSON object.

        Returns:
            `since`, `until`, `days`, `log_bound_bytes`, and `roles`.
        """
        return {
            "since": self.since,
            "until": self.until,
            "days": self.days,
            "log_bound_bytes": self.bound,
            "roles": [r.as_json() for r in self.roles],
        }


def measure(conn: sqlite3.Connection, now: datetime, days: int, *, state_dir: Path, version: Version) -> ToolResults:
    """Measure the runs that started in the last `days` local days, today's so far included, and have ended.

    Each run's log is read as the runtime `version` prints it; an overseer's from its tick's output under `state_dir`.

    Returns:
        The figures per role a run of the window had, and per tool its runs called.
    """
    start, end = spend.window(now, days)
    since, until = db.format_time(start), db.format_time(end)
    measured: dict[str, list[Uses | None]] = defaultdict(list)
    for ran in _ran(conn, since, until):
        measured[ran.role].append(_read(ran, state_dir=state_dir, version=version))
    order = [str(k) for k in RunKind] + [REVIEW, TASK, EPIC_PLAN, CHORE, OVERSEER]
    roles = sorted(measured, key=lambda r: (order.index(r) if r in order else len(order), r))
    return ToolResults(
        since=since,
        until=until,
        days=days,
        bound=transcript.MAX_BYTES,
        roles=tuple(_summed(role, measured[role]) for role in roles),
    )


def row_of(use: Use) -> str:
    """The row a call counts under: its tool as canopy keeps a name, or for a shell call, the program it ran.

    Returns:
        The tool's name, or `$ ` and the program (`shell_program`), `?` when canopy cannot read one.
    """
    if use.command is None:
        return report.kept_name(use.tool)
    return report.kept_name(SHELL_ROW + (shell_program(use.command) or UNREAD_PROGRAM))


def shell_program(command: str) -> str | None:
    """The program a shell `command` runs, as its row names it: `gh run view` for `cd web && gh run view 7 --log`.

    The first stage that does more than move or set up the shell, or the first stage when none does; its program
    without its directory, and for a program in `SUBCOMMAND_WORDS`, the words after it that are subcommands, up to the
    first that is not one.

    Returns:
        The program and its subcommands, by spaces; None when the command has no stage canopy can read.
    """
    stages = report.shell_stages(command)
    if not stages:
        return None
    words = next((s for s in stages if _program(s) not in SETUP_PROGRAMS), stages[0])
    program = _program(words)
    named = [program]
    for word in words[1 : 1 + SUBCOMMAND_WORDS.get(program, 0)]:
        if not _SUBCOMMAND_RE.fullmatch(word):
            break
        named.append(word)
    return " ".join(named)


@dataclass(frozen=True)
class _Ran(records.View):
    """A run that ended in the window: its role, and where its session's events are."""

    role: str
    log_path: str
    session_id: str | None
    #: The tick an overseer's run was of, whose output holds its session; None for any other run.
    tick_id: int | None


#: A run in the window, by when it started, that has ended.
_WINDOW: LiteralString = "started_at >= ? AND started_at < ? AND ended_at IS NOT NULL"
#: The tables whose runs are of one role each, with a log of their own.
type _OneRole = Literal["review_runs", "task_runs", "epic_runs", "chore_runs"]


def _ran(conn: sqlite3.Connection, since: str, until: str) -> list[_Ran]:
    """Every run that started in `[since, until)` and has ended, of every role.

    Returns:
        The runs, a worker's or a planner's by its kind.
    """
    worker = (
        sql.select("kind AS role, log_path, session_id, NULL AS tick_id").from_("runs").where(_WINDOW, since, until)
    )
    tables: Iterable[tuple[_OneRole, str]] = (
        ("review_runs", REVIEW),
        ("task_runs", TASK),
        ("epic_runs", EPIC_PLAN),
        ("chore_runs", CHORE),
    )
    each = [worker]
    each += [
        sql.select("? AS role, log_path, session_id, NULL AS tick_id", role).from_(table).where(_WINDOW, since, until)
        for table, role in tables
    ]
    each.append(
        sql.select("? AS role, '' AS log_path, session_id, tick_id", OVERSEER)
        .from_("overseer_runs")
        .where(_WINDOW, since, until),
    )
    return records.fetch_all(conn, _Ran, sql.union(*each, every=True))


def _read(ran: _Ran, *, state_dir: Path, version: Version) -> Uses | None:
    """The calls of one run's session, from its log or its tick's output; None when there is none to read.

    Returns:
        The calls, and whether the log held more than was read; or None.
    """
    if ran.session_id is None:
        return None
    log = state_dir / "ticks" / f"{ran.tick_id}.log" if ran.tick_id is not None else Path(ran.log_path)
    return transcript.uses(log, ran.session_id, version=version)


def _summed(role: str, runs: Sequence[Uses | None]) -> RoleResults:
    """The figures of one role's runs, and of each tool they called.

    Returns:
        Them, the tools the most characters first, past `report.MAX_TOOLS` tools counted as `report.OTHER_TOOLS`.
    """
    read = [r for r in runs if r is not None]
    by_tool: dict[str, list[Use]] = defaultdict(list)
    repeated: dict[str, int] = defaultdict(int)
    status: list[list[Use]] = []
    for run in read:
        seen: set[str] = set()
        for use in run.calls:
            row = row_of(use)
            if row not in by_tool and len(by_tool) >= report.MAX_TOOLS:
                row = report.OTHER_TOOLS
            by_tool[row].append(use)
            if _rereads(use, seen):
                repeated[row] += 1
        if called := [u for u in run.calls if u.tool == cards.tool_name()]:
            status.append(called)
    chars = sum(u.result_chars for uses in by_tool.values() for u in uses)
    tools = sorted(
        (_tool(row, uses, chars, repeated[row]) for row, uses in by_tool.items()),
        key=lambda t: (-t.chars, t.tool),
    )
    sent = [sum(u.input_chars for u in called) for called in status]
    return RoleResults(
        role=role,
        runs=len(runs),
        read=len(read),
        cut_logs=sum(1 for r in read if r.truncated),
        calls=sum(t.calls for t in tools),
        chars=chars,
        repeated=sum(t.repeated for t in tools),
        status_runs=len(status),
        status_calls=sum(len(called) for called in status),
        status_chars=sum(sent),
        status_median=float(statistics.median(sent)) if sent else None,
        tools=tuple(tools),
    )


def _rereads(use: Use, seen: set[str]) -> bool:
    """Whether `use` is a completed read of a path in `seen`, the paths its run read before it; adds the ones it reads.

    Returns:
        True when it reads one again.
    """
    if not use.completed or use.touch.act != "read":
        return False
    paths = {posixpath.normpath(p) for p in use.touch.paths}
    again = not paths.isdisjoint(seen)
    seen.update(paths)
    return again


def _tool(row: str, uses: Sequence[Use], role_chars: int, repeated: int) -> ToolResult:
    """One tool's figures in its role, whose calls returned `role_chars` characters.

    Returns:
        Them.
    """
    chars = sum(u.result_chars for u in uses)
    return ToolResult(
        tool=row,
        calls=len(uses),
        chars=chars,
        median=float(statistics.median(u.result_chars for u in uses)),
        share=chars / role_chars if role_chars else None,
        cut=sum(1 for u in uses if u.cut is True),
        unknown=sum(1 for u in uses if u.cut is None),
        repeated=repeated,
    )


def _program(words: Sequence[str]) -> str:
    """The program a stage runs, without its directory.

    Returns:
        Its name.
    """
    return words[0].rsplit("/", 1)[-1]
