"""Ticks as the API sends them (DESIGN §6): the latest, the list, and one tick with its decisions and its output.

A tick's summary is the overseer's text, laid out as a page shows it, and its output is read back as a transcript or as
written, as a run's log is.
"""

from __future__ import annotations

from itertools import starmap
from typing import TYPE_CHECKING

from canopy.core import db, run_models
from canopy.core.vocab import TickStatus
from canopy.serve.schema import LastTick, Tick, TickDetail
from canopy.serve.transcript_views import raw_output, removed_after, session_transcript
from canopy.serve.views import activity, decision, lines, models_served, new_tokens, shown_path

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.core import gc_passes, records
    from canopy.core.context import Context
    from canopy.serve.schema.transcript import RawOutput, Transcript

#: The ticks list, newest first.
TICKS = 50


def last_tick(ctx: Context) -> LastTick:
    """The latest tick, and the newest message the latest `ok` tick read.

    Returns:
        The latest tick, None before the first, and the message's id, None before an `ok` tick recorded one.
    """
    return LastTick(tick=tick(ctx), acknowledged=db.acknowledged_message_id(ctx.conn))


def tick(ctx: Context) -> Tick | None:
    """The latest tick, or None before the first.

    Returns:
        The tick, with how many decisions it recorded.
    """
    row = db.last_tick(ctx.conn)
    if row is None:
        return None
    return tick_of(row, db.decision_count(ctx.conn, row.id))


def tick_of(row: records.Tick, decisions: int) -> Tick:
    """A tick's row, and how many decisions it recorded.

    Returns:
        The tick as the API sends it, its summary laid out as a page shows it and None when empty.
    """
    return Tick(
        id=row.id,
        status=row.status,
        dry_run=row.dry_run,
        started_at=db.parse_time(row.started_at),
        ended_at=db.parse_time(row.ended_at) if row.ended_at else None,
        summary=lines(row.summary or "") or None,
        session_id=row.session_id or None,
        cost_usd=row.cost_usd,
        new_tokens=new_tokens(row),
        peak_context=row.tokens_peak_context,
        decisions=decisions,
        idle=row.idle,
        woken_by=row.woken_by,
        canopy_version=row.canopy_version,
        activity=activity(row) if row.status is TickStatus.RUNNING else None,
    )


def ticks(ctx: Context, *, idle: bool = False) -> list[Tick]:
    """The latest ticks, newest first, or the latest live ticks the loop found idle when `idle` is set.

    Returns:
        At most `TICKS` ticks, each with how many decisions it recorded.
    """
    return list(starmap(tick_of, db.recent_ticks(ctx.conn, TICKS, idle=idle)))


def tick_detail(ctx: Context, tick_id: int) -> TickDetail | None:
    """One tick and its decisions, as `canopy decisions ID` prints them, or None if there is no such tick.

    Returns:
        The tick, its decisions, its output's path from the workspace root, None when the file is missing, and the
        ids of the ticks either side of it.
    """
    row = db.get_tick(ctx.conn, tick_id)
    if row is None:
        return None
    rows = db.decisions_for_tick(ctx.conn, tick_id)
    output = tick_output(ctx, tick_id)
    previous_id, next_id = db.tick_neighbours(ctx.conn, tick_id)
    return TickDetail(
        tick=tick_of(row, len(rows)),
        decisions=[decision(d) for d in rows],
        output_path=shown_path(str(output), ctx.workspace.root) if output.exists() else None,
        previous_id=previous_id,
        next_id=next_id,
        models=models_served(ctx.conn, "ticks", tick_id, ended=row.ended_at is not None, session_id=row.session_id),
        model=row.model,
    )


def tick_output(ctx: Context, tick_id: int) -> Path:
    """Where a tick's overseer output is (DESIGN §6).

    Returns:
        The path under the state directory. The file may not exist.
    """
    return ctx.state_dir / "ticks" / f"{tick_id}.log"


def tick_transcript(ctx: Context, tick_id: int) -> Transcript | None:
    """The overseer's session in a tick's output, or None if there is no such tick.

    Returns:
        The transcript, its status saying whether the tick recorded a session and whether its output could be read.
    """
    row = db.get_tick(ctx.conn, tick_id)
    if row is None:
        return None
    output = tick_output(ctx, tick_id)
    removed = removed_after(ctx.conn, output, row.ended_at, _tick_rule(row))
    return session_transcript(
        output,
        row.session_id,
        removed,
        run_models.replies_of(ctx.conn, "ticks", tick_id),
        version=ctx.config.runtime.version,
    )


def tick_raw_output(ctx: Context, tick_id: int) -> RawOutput | None:
    """The end of a tick's output as written, or None if there is no such tick.

    Returns:
        The tail, without control characters, or a `no_output` status when the file is missing or not a regular file.
    """
    row = db.get_tick(ctx.conn, tick_id)
    if row is None:
        return None
    output = tick_output(ctx, tick_id)
    return raw_output(output, removed_after(ctx.conn, output, row.ended_at, _tick_rule(row)))


def _tick_rule(row: records.Tick) -> gc_passes.Rule:
    # A tick that did not close `ok` keeps its files as long as a run, since the operator debugs those (DESIGN §26).
    return "tick_files_days" if row.status is TickStatus.OK else "run_files_days"
