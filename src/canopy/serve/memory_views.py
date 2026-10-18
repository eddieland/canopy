"""Agent memory as the API sends it (DESIGN §28): each tier's mode in words, the notes, proposals, and lessons.

What a worker wrote is sent as the journal holds it, and the UI shows it as plain text with every hidden character
named, never as Markdown or a link.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, cast

from canopy.core import db, memory, memory_manage
from canopy.core.vocab import MemoryCited, MemoryMode
from canopy.serve.schema import (
    MemoryDigest,
    MemoryEntry,
    MemoryModeName,
    MemoryOrigin,
    MemoryOverview,
    MemoryProposal,
    MemoryRefusal,
    MemoryState,
    MemoryTier,
    RunMemory,
    RunMemoryModes,
    TicketMemory,
    TicketNotes,
)

if TYPE_CHECKING:
    from datetime import datetime

    from canopy.core import records
    from canopy.core.context import Context


def state(ctx: Context) -> MemoryState | None:
    """Agent memory's tiers, or None while both are off.

    Returns:
        The readout, each tier's mode in words, what reads each, and how many proposals wait on the operator: none
        while proposals are off, when no proposal shows.
    """
    settings = ctx.config.memory
    readout = memory.readout(settings)
    if readout is None:
        return None
    return MemoryState(
        readout=readout,
        tiers=memory.tiers(settings),
        ticket_notes=_tier(settings.ticket_notes, memory.notes_band(settings.ticket_notes)),
        lessons=_tier(settings.proposals, memory.lessons_band(settings.proposals)),
        proposals_waiting=0 if settings.proposals is MemoryMode.OFF else memory.pending_count(ctx.conn),
    )


def overview(ctx: Context) -> MemoryOverview:
    """Every tier's memory: the tickets with notes in force, the proposals waiting, the lessons, and what they serve.

    The notes are counted by ticket, not sent: a busy workspace holds thousands, and a ticket's own read lists them.

    Returns:
        The overview, with no digest of the lessons while proposals are off.
    """
    settings = ctx.config.memory
    digest = None
    if settings.proposals is not MemoryMode.OFF:
        found = memory.lessons_digest(ctx.conn, None, cite=False)
        digest = _digest(found, served=settings.proposals is MemoryMode.USE)
    return MemoryOverview(
        state=state(ctx),
        tickets=[_ticket_notes(t) for t in memory.ticket_notes(ctx.conn)],
        proposals=[_proposal(ctx, p) for p in memory.pending_proposals(ctx.conn)],
        lessons=[entry(ctx, m) for m in sorted(memory.active_lessons(ctx.conn), key=_review_order)],
        lessons_digest=digest,
        repos=[r.name for r in ctx.ws.repos],
    )


def ticket_memory(ctx: Context, key: str) -> TicketMemory | None:
    """One ticket's notes and what its next run would be served, or None if the journal has no record of the ticket.

    Returns:
        Every note of the ticket, and its digest while ticket notes are not off.
    """
    if db.get_ticket(ctx.conn, key) is None:
        return None
    mode = ctx.config.memory.ticket_notes
    digest = None
    if mode is not MemoryMode.OFF:
        digest = _digest(memory.ticket_digest(ctx.conn, key), served=mode is MemoryMode.USE)
    return TicketMemory(
        state=state(ctx),
        notes=[entry(ctx, m) for m in memory.notes(ctx.conn, key, every=True)],
        digest=digest,
    )


def run_memory(ctx: Context, run_id: int) -> RunMemory | None:
    """What a run wrote and read of memory, or None if there is no such run.

    Returns:
        The modes it was rendered under, what it wrote, what was rendered into it, and what it had refused.
    """
    if db.get_run(ctx.conn, run_id) is None:
        return None
    rendered = memory.run_memory(ctx.conn, run_id)
    if rendered is None:
        return RunMemory(rendered=None, wrote=[], read=[], refused=[])
    cited = memory.citations(ctx.conn, run_id)
    return RunMemory(
        rendered=RunMemoryModes(ticket_notes=_mode(rendered.ticket_notes), lessons=_mode(rendered.proposals)),
        wrote=[entry(ctx, m) for m in memory.written_by(ctx.conn, run_id)],
        read=[entry(ctx, m) for m in memory.read_by(ctx.conn, run_id)],
        used=[i for i, c in cited.items() if c is MemoryCited.USED],
        wrong=[i for i, c in cited.items() if c is MemoryCited.WRONG],
        refused=[MemoryRefusal(field=r.field, key=r.key, why=r.why) for r in memory.refused_of(rendered)],
    )


def entry(ctx: Context, m: records.Memory) -> MemoryEntry:
    """A memory as the API sends it.

    Returns:
        Its fields, its times as datetimes, the latest runs that relied on it, whether a private ticket's run wrote
        it, and for a lesson what it was promoted from.
    """
    return MemoryEntry(
        id=m.id,
        scope=m.scope.value,
        ticket_key=m.ticket_key,
        repo=m.repo,
        key=m.key,
        text=m.body,
        status=m.status.value,
        why=m.why,
        run_id=m.run_id,
        head=m.head,
        created_at=db.parse_time(m.created_at),
        use_count=m.use_count,
        last_used_at=_time(m.last_used_at),
        used_by=memory.used_by(ctx.conn, m.id) if m.use_count else [],
        review_at=_time(m.review_at),
        wrong_at=_time(m.wrong_at),
        wrong_run_id=m.wrong_run_id,
        promoted_from=m.promoted_from,
        origin=_origin(ctx, m.promoted_from),
        private=memory_manage.from_private_run(ctx.conn, m),
    )


def _origin(ctx: Context, source_id: int | None) -> MemoryOrigin | None:
    source = memory.get(ctx.conn, source_id) if source_id is not None else None
    if source is None:
        return None
    return MemoryOrigin(id=source.id, scope=source.scope.value, ticket_key=source.ticket_key, run_id=source.run_id)


def _tier(mode: MemoryMode, band: str) -> MemoryTier:
    return MemoryTier(mode=_mode(mode), words=memory.mode_words(mode), band=band)


def _mode(mode: MemoryMode) -> MemoryModeName:
    return cast("MemoryModeName", mode.value)


def _digest(found: memory.Digest, *, served: bool) -> MemoryDigest:
    return MemoryDigest(text=found.text, ids=list(found.ids), left_out=found.left_out, served=served)


def _review_order(lesson: records.Memory) -> tuple[bool, str, str]:
    # Reported wrong first, then by review date: what calls for the operator comes first, and the lessons longest since
    # vouched for, which the digest leaves out first, come before those it serves.
    return (lesson.wrong_at is None, lesson.review_at or "", lesson.key)


def _ticket_notes(found: memory.TicketNotes) -> TicketNotes:
    return TicketNotes(
        ticket_key=found.ticket_key,
        count=found.count,
        used=found.used,
        latest_at=db.parse_time(found.latest_at),
        title=found.title,
    )


def _proposal(ctx: Context, p: records.Memory) -> MemoryProposal:
    run = db.get_run(ctx.conn, p.run_id) if p.run_id is not None else None
    ticket = db.get_ticket(ctx.conn, p.ticket_key) if p.ticket_key is not None else None
    return MemoryProposal(
        entry=entry(ctx, p),
        run_kind=str(run["kind"]) if run is not None else None,
        run_status=str(run["status"]) if run is not None else None,
        private=bool(run["private"]) if run is not None else False,
        ticket_done=bool(ticket.done) if ticket is not None else False,
        expires_at=db.parse_time(p.created_at) + timedelta(days=memory.PROPOSAL_DAYS),
    )


def _time(stamp: str | None) -> datetime | None:
    return db.parse_time(stamp) if stamp is not None else None
