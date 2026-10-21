"""Chores as the API sends them (DESIGN §19): each chore's summary, its page, and one chore run with its session.

A chore's findings and its runs' results are an agent's text: control characters are dropped, and the UI renders them
as text.
"""

from __future__ import annotations

import math
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, assert_never

from canopy.core import chore_result, chore_view, contract, conversation, db
from canopy.core.vocab import ChoreRunStatus
from canopy.serve.schema import (
    ChoreDetail,
    ChoreFinding,
    ChoreRun,
    ChoreRunDetail,
    ChoreRunFinding,
    ChoreSpend,
    ChoreSpendWindow,
    ChoreSummary,
)
from canopy.serve.transcript_views import removed_after, session_transcript
from canopy.serve.views import (
    SPEND_DAY_HOURS,
    SPEND_MONTH_HOURS,
    lines,
    message,
    models_served,
    new_tokens,
    said,
    shown_path,
    ticket_title,
)

if TYPE_CHECKING:
    import sqlite3
    from datetime import datetime

    from canopy.core import records
    from canopy.core.config import Chore
    from canopy.core.context import Context
    from canopy.serve.backend import Backend
    from canopy.serve.schema import RunState, Transcript

#: A chore's page: its latest runs.
CHORE_RUNS = 10
#: The most of a chore's prompt read for its title: its first line, cut here.
_CHORE_TITLE_READ = 500


def chores(backend: Backend, ctx: Context) -> list[ChoreSummary]:
    """Each configured chore, as `canopy status` lists it: none when `capacity.max_chores` is 0 (DESIGN §19).

    Returns:
        Each chore's summary, by name, as of the backend's clock.
    """
    now = backend.clock()
    root = ctx.workspace.root
    return [
        chore_summary(ctx.conn, s, now, root)
        for s in chore_view.states(ctx.conn, ctx.config, ctx.workspace, starts=ctx.finding_starts)
    ]


def chore(backend: Backend, ctx: Context, name: str) -> ChoreDetail | None:
    """One chore, as `canopy show chore:NAME` prints it, or None if it is not defined for this workspace.

    A chore defined while `capacity.max_chores` is 0 has a page, as `canopy reply chore:NAME` takes a note to it.

    Returns:
        The chore's summary, its latest runs, and its notes.
    """
    defined = chore_view.defined(ctx.config, ctx.workspace)
    if name not in defined:
        return None
    state = chore_view.state_of(ctx.conn, name, defined[name], starts=ctx.finding_starts)
    return ChoreDetail(
        chore=chore_summary(ctx.conn, state, backend.clock(), ctx.workspace.root),
        runs=[chore_run(r, ctx.workspace.root) for r in state.runs[:CHORE_RUNS]],
        notes=[message(m) for m in db.messages_of(ctx.conn, conversation.CHORE, name, conversation.CHORE_NOTES)],
    )


def chore_summary(conn: sqlite3.Connection, state: chore_view.ChoreState, now: datetime, root: Path) -> ChoreSummary:
    """A chore's state as its line in `canopy status` and the head of `canopy show chore:NAME` say it.

    Returns:
        The chore's schedule, its running and latest ended runs, when it is next due, its open findings, and what its
        runs cost in the last day and the last 30 days.
    """
    defined = state.chore
    running = state.running
    latest = state.latest_ended
    return ChoreSummary(
        name=state.name,
        title=_chore_title(defined),
        every_minutes=defined.every_minutes,
        days=list(defined.days),
        hours=defined.hours,
        timezone=defined.timezone,
        when=defined.when or None,
        running=chore_run(running, root) if running is not None else None,
        latest=chore_run(latest, root) if latest is not None else None,
        due_at=state.due_at(now),
        findings=[
            ChoreFinding(
                id=f.finding.id,
                title=conversation.printable(f.finding.title),
                detail=conversation.printable(f.finding.detail),
                link=f.finding.link,
                since=db.parse_time(f.since),
                dismissed=f.dismissed,
            )
            for f in state.findings()
        ],
        max_findings=defined.max_findings,
        more_findings=state.more_findings(),
        latest_note_id=db.latest_message_of(conn, conversation.CHORE, state.name),
        spend=ChoreSpend(
            day=_chore_spent(conn, state.name, now, SPEND_DAY_HOURS),
            month=_chore_spent(conn, state.name, now, SPEND_MONTH_HOURS),
        ),
    )


def _chore_title(chore: Chore) -> str | None:
    """The heading a chore's prompt opens with, `# Dependency advisories`, as the chore's title.

    Returns:
        The heading's text on one line, or None when the prompt's first line is no `# ` heading or cannot be read.
    """
    try:
        with chore.prompt.open(encoding="utf-8") as f:
            first = f.readline(_CHORE_TITLE_READ)
    except (OSError, UnicodeDecodeError):
        return None
    return ticket_title(first.removeprefix("# ")) if first.startswith("# ") else None


def _chore_spent(conn: sqlite3.Connection, name: str, now: datetime, hours: int) -> ChoreSpendWindow:
    since = db.format_time(now - timedelta(hours=hours))
    runs, costs = db.chore_costs_since(conn, name, since)
    if not costs:
        return ChoreSpendWindow(hours=hours, runs=runs, priced=0)
    total = sum(costs)
    # Nearest rank: the smallest cost at least 99% of the runs did not exceed.
    p99 = costs[math.ceil(0.99 * len(costs)) - 1]
    return ChoreSpendWindow(
        hours=hours,
        runs=runs,
        priced=len(costs),
        cost_usd=total,
        mean_usd=total / len(costs),
        p99_usd=p99,
        max_usd=costs[-1],
    )


def chore_run(row: records.ChoreRun, root: Path) -> ChoreRun:
    """One chore run's row, its log's path from the workspace `root`.

    Returns:
        The run as the API sends it, `done` only when it ended `ok`, with its findings counted then.
    """
    parsed = chore_result.stored(row.result_json) if row.status is ChoreRunStatus.OK else None
    return ChoreRun(
        id=row.id,
        status=row.status,
        state=_chore_state(row.status),
        started_at=db.parse_time(row.started_at),
        ended_at=db.parse_time(row.ended_at) if row.ended_at else None,
        summary=said(row),
        findings=len(parsed.findings) if parsed is not None else 0,
        more_findings=parsed.more_findings if parsed is not None else 0,
        session_id=row.session_id or None,
        cost_usd=row.cost_usd,
        new_tokens=new_tokens(row),
        peak_context=row.tokens_peak_context,
        log_path=shown_path(row.log_path, root),
    )


def _chore_state(status: ChoreRunStatus) -> RunState:
    """What the web UI colors a chore run that has `status` as.

    Returns:
        The run's state: a chore run that checked is done, and every other ending, which raises `chore_failed`
        (DESIGN §19), is failed.
    """
    match status:
        case ChoreRunStatus.RUNNING:
            return "running"
        case ChoreRunStatus.OK:
            return "done"
        case ChoreRunStatus.FAILED | ChoreRunStatus.UNKNOWN | ChoreRunStatus.TIMEOUT | ChoreRunStatus.CRASHED:
            return "failed"
        case _:
            assert_never(status)


def chore_run_detail(ctx: Context, name: str, run_id: int) -> ChoreRunDetail | None:
    """One run of chore `name`, or None if it has no such run. A chore deleted from the config keeps its runs.

    Returns:
        The run, its summary, the harness's note, and its findings, the findings only when it ended `ok`.
    """
    row = _chore_run_of(ctx.conn, name, run_id)
    if row is None:
        return None
    stored = contract.stored_object(row.result_json)
    parsed = chore_result.stored(row.result_json) if row.status is ChoreRunStatus.OK else None
    defined = chore_view.defined(ctx.config, ctx.workspace).get(name)
    return ChoreRunDetail(
        chore=name,
        title=_chore_title(defined) if defined is not None else None,
        run=chore_run(row, ctx.workspace.root),
        summary=lines(str(stored.get("summary") or "")) or None,
        note=lines(str(stored.get("harness") or "")) or None,
        findings=[
            ChoreRunFinding(
                id=f.id,
                title=conversation.printable(f.title),
                detail=conversation.printable(f.detail),
                link=f.link,
            )
            for f in (parsed.findings if parsed is not None else [])
        ],
        models=models_served(
            ctx.conn,
            "chore_runs",
            run_id,
            ended=row.ended_at is not None,
            session_id=row.session_id or None,
        ),
    )


def chore_run_transcript(ctx: Context, name: str, run_id: int) -> Transcript | None:
    """A chore run's session in its log, or None if chore `name` has no such run.

    Returns:
        The transcript, its status saying whether the run recorded a session and whether its log could be read.
    """
    row = _chore_run_of(ctx.conn, name, run_id)
    if row is None:
        return None
    log = Path(row.log_path)
    return session_transcript(log, row.session_id, removed_after(ctx.conn, log, row.ended_at, "run_files_days"))


def _chore_run_of(conn: sqlite3.Connection, name: str, run_id: int) -> records.ChoreRun | None:
    row = db.get_chore_run(conn, run_id)
    return row if row is not None and row.chore == name else None
