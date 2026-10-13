"""Journal rows as the API's models: attention, runs, tickets and their conversations, chores, ticks, search hits.

Reads only. Every text that came from an agent or the tracker stays untrusted: control characters are dropped from
message bodies as `canopy show` drops them, run summaries are cut to one line, and the UI renders all of it as text.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import chore_result, chore_view, contract, conversation, db, items, search, transcript
from canopy.core.items import fingerprint
from canopy.serve.schema import (
    AttentionItem,
    ChoreDetail,
    ChoreFinding,
    ChoreRun,
    ChoreSummary,
    Comment,
    Decision,
    LastTick,
    Message,
    MessageKind,
    MessageSource,
    Run,
    RunState,
    SearchHit,
    SearchResults,
    Spend,
    SpendWindow,
    StartStatus,
    Tick,
    TickDetail,
    TicketDetail,
    TicketSummary,
    Transcript,
    TranscriptEntry,
    TranscriptError,
    TranscriptStep,
    TranscriptText,
    TranscriptTool,
    Unit,
)

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.context import Context
    from canopy.serve.backend import Backend

# How many runs that ended the runs list carries, after the running ones.
RECENT_RUNS = 50
# How many tickets the tickets list carries, by most recent activity.
TICKETS = 200
# A ticket's page: its latest runs and messages.
TICKET_RUNS = 10
TICKET_MESSAGES = 100
# A chore's page: its latest runs.
CHORE_RUNS = 10
# The ticks list, newest first, and a ticket's page: the latest decisions about it.
TICKS = 50
TICKET_DECISIONS = 20
SUMMARY_LENGTH = 300
# The windows the spend figures cover: the last day and the last 30.
SPEND_DAY_HOURS = 24
SPEND_MONTH_HOURS = 30 * 24
_CHORE = "chore:"
_PR = "pr:"
_STATES: dict[str, RunState] = {"running": "running", "blocked": "blocked", "done": "done", "stopped": "stopped"}
# A chore run that checked is done; every other ending raises `chore_failed` (DESIGN §19).
_CHORE_STATES: dict[str, RunState] = {"running": "running", "ok": "done"}
_SOURCES: dict[str, MessageSource] = {"worker": "worker", "operator": "operator", "tracker": "tracker"}
_KINDS: dict[str, MessageKind] = {"report": "report", "question": "question", "reply": "reply", "comment": "comment"}


def attention(backend: Backend, ctx: Context) -> list[AttentionItem]:
    """The attention list, as `canopy status` shows it."""
    found: list[AttentionItem] = []
    for item in backend.attention(ctx):
        key = item.ticket_key
        chore = key.removeprefix(_CHORE) if key is not None and key.startswith(_CHORE) else None
        ticket = key if key is not None and chore is None and not key.startswith(_PR) else None
        found.append(
            AttentionItem(
                id=fingerprint(item.ticket_key, item.reason, item.repo),
                subject=item.subject,
                ticket_key=ticket,
                chore=chore,
                repo=item.repo,
                reason=item.reason,
                detail=conversation.printable(item.detail),
                since=db.parse_time(item.since),
                finding=item.finding,
            )
        )
    return found


def spend(backend: Backend, ctx: Context) -> Spend:
    """What the last day and the last 30 days cost, by the backend's clock."""
    now = backend.clock()
    return Spend(day=_spent(ctx, now, SPEND_DAY_HOURS), month=_spent(ctx, now, SPEND_MONTH_HOURS))


def _spent(ctx: Context, now: datetime, hours: int) -> SpendWindow:
    since = now - timedelta(hours=hours)
    return SpendWindow(since=since, hours=hours, cost_usd=db.spent_since(ctx.conn, db.format_time(since)))


def last_tick(ctx: Context) -> LastTick:
    """The latest tick, and the newest message the latest `ok` tick read."""
    return LastTick(tick=tick(ctx), acknowledged=db.acknowledged_message_id(ctx.conn))


def tick(ctx: Context) -> Tick | None:
    """The latest tick, or None before the first."""
    row = db.last_tick(ctx.conn)
    if row is None:
        return None
    return tick_of(row, db.decision_count(ctx.conn, int(row["id"])))


def tick_of(row: sqlite3.Row, decisions: int) -> Tick:
    """A tick's row, and how many decisions it recorded."""
    return Tick(
        id=int(row["id"]),
        status=str(row["status"]),
        dry_run=bool(row["dry_run"]),
        started_at=db.parse_time(row["started_at"]),
        ended_at=db.parse_time(row["ended_at"]) if row["ended_at"] else None,
        summary=lines(str(row["summary"] or "")) or None,
        session_id=str(row["session_id"]) if row["session_id"] else None,
        cost_usd=float(row["cost_usd"]) if row["cost_usd"] is not None else None,
        decisions=decisions,
    )


def ticks(ctx: Context) -> list[Tick]:
    """The latest ticks, newest first."""
    return [tick_of(row, int(row["decisions"])) for row in db.recent_ticks(ctx.conn, TICKS)]


def tick_detail(ctx: Context, tick_id: int) -> TickDetail | None:
    """One tick and its decisions, as `canopy decisions ID` prints them, or None if there is no such tick."""
    row = db.get_tick(ctx.conn, tick_id)
    if row is None:
        return None
    rows = db.decisions_for_tick(ctx.conn, tick_id)
    output = tick_output(ctx, tick_id)
    return TickDetail(
        tick=tick_of(row, len(rows)),
        decisions=[decision(d) for d in rows],
        output_path=shown_path(str(output), ctx.workspace.root) if output.exists() else None,
    )


def tick_output(ctx: Context, tick_id: int) -> Path:
    """Where a tick's overseer output is (DESIGN §6)."""
    return ctx.state_dir / "ticks" / f"{tick_id}.log"


def tick_transcript(ctx: Context, tick_id: int) -> Transcript | None:
    """The overseer's session in a tick's output, or None if there is no such tick."""
    row = db.get_tick(ctx.conn, tick_id)
    if row is None:
        return None
    return session_transcript(tick_output(ctx, tick_id), row["session_id"])


def run_detail(ctx: Context, run_id: int) -> Run | None:
    """One run, with the worktrees it holds if it is running, or None if there is no such run."""
    row = db.get_run(ctx.conn, run_id)
    if row is None:
        return None
    root = ctx.workspace.root
    held = db.all_run_slots(ctx.conn, [run_id] if row["status"] == "running" else []).get(run_id, [])
    return run(row, root, [shown_path(str(s["slot_path"]), root) for s in held])


def run_transcript(ctx: Context, run_id: int) -> Transcript | None:
    """A run's session in its log, or None if there is no such run."""
    row = db.get_run(ctx.conn, run_id)
    if row is None:
        return None
    return session_transcript(Path(str(row["log_path"])), row["session_id"])


def session_transcript(path: Path, session: object) -> Transcript:
    """The events of the session the journal recorded, read back from the file they were printed to (DESIGN §22)."""
    if not isinstance(session, str) or not session:
        return Transcript(status="no_session")
    found = transcript.read(path, session)
    if found is None:
        return Transcript(status="no_log", session_id=session)
    return Transcript(
        status="read",
        session_id=session,
        entries=[transcript_entry(e) for e in found.entries],
        truncated=found.truncated,
        unreadable=found.unreadable,
    )


def transcript_entry(entry: transcript.Entry) -> TranscriptEntry:
    """One entry of a transcript as the API sends it."""
    match entry:
        case transcript.Text():
            return TranscriptText(at=entry.at, text=entry.text, reasoning=entry.reasoning, cut=entry.cut)
        case transcript.ToolCall():
            return TranscriptTool(
                at=entry.at,
                tool=entry.tool,
                status=entry.status,
                title=entry.title,
                input=entry.input,
                output=entry.output,
                duration_ms=entry.duration_ms,
                cut=entry.cut,
            )
        case transcript.Step():
            return TranscriptStep(at=entry.at, reason=entry.reason, cost_usd=entry.cost_usd, tokens=entry.tokens)
        case transcript.Error():
            return TranscriptError(at=entry.at, name=entry.name, message=entry.message)


def decision(row: sqlite3.Row) -> Decision:
    """One decision, named as `canopy decisions` names it, its rationale with its line breaks."""
    chore = str(row["chore"]) if row["chore"] is not None else None
    pr = str(row["pr"]) if row["pr"] is not None else None
    key = str(row["ticket_key"]) if row["ticket_key"] is not None else None
    repo = str(row["repo"]) if row["repo"] is not None else None
    if chore is not None:
        subject = f"{_CHORE}{chore}"
    elif key is None and pr is not None:
        subject = f"{_PR}{pr}"
    else:
        subject = items.subject(key, repo)
    return Decision(
        id=int(row["id"]),
        tick_id=int(row["tick_id"]),
        at=db.parse_time(str(row["created_at"])),
        subject=subject,
        ticket_key=key,
        repo=repo,
        chore=chore,
        pr=pr,
        action=str(row["action"]),
        rationale=lines(str(row["rationale"])),
    )


def runs(ctx: Context) -> list[Run]:
    """Running runs, oldest first, then the ones that ended most recently, newest first."""
    running = db.running_runs(ctx.conn)
    slots = db.all_run_slots(ctx.conn, [int(r["id"]) for r in running])
    root = ctx.workspace.root
    return [
        *(run(r, root, [shown_path(str(s["slot_path"]), root) for s in slots[int(r["id"])]]) for r in running),
        *(run(r, root) for r in db.recent_runs(ctx.conn, RECENT_RUNS)),
    ]


def shown_path(path: str, root: Path) -> str:
    """A worktree's path as a page shows it: from the workspace root when under it, else whole.

    A workspace's pool paths then read as `.treehouse/web-3f9c2a1b/1/web`.
    """
    found = Path(path)
    return str(found.relative_to(root)) if found.is_relative_to(root) else path


def run(row: sqlite3.Row, root: Path, worktrees: list[str] | None = None) -> Run:
    """One run's row, with the worktrees it holds if it is running, its paths from the workspace `root`."""
    result = contract.stored_object(row["result_json"])
    status = str(row["status"])
    return Run(
        id=int(row["id"]),
        ticket_key=str(row["ticket_key"]),
        kind=str(row["kind"]),
        status=status,
        state=_STATES.get(status, "failed"),
        private=bool(row["private"]),
        branch=str(row["branch"]) or None,
        started_at=db.parse_time(str(row["started_at"])),
        ended_at=db.parse_time(str(row["ended_at"])) if row["ended_at"] else None,
        summary=said(row),
        prs=contract.stored_prs(result),
        session_id=str(row["session_id"]) if row["session_id"] else None,
        cost_usd=float(row["cost_usd"]) if row["cost_usd"] is not None else None,
        tokens=tokens(row),
        worktrees=worktrees or [],
        log_path=shown_path(str(row["log_path"]), root),
    )


def tokens(row: sqlite3.Row) -> int | None:
    """A run's or a chore run's tokens of every kind, or None when the runtime reported none."""
    found = [
        row[c] for c in ("tokens_input", "tokens_output", "tokens_reasoning", "tokens_cache_read", "tokens_cache_write")
    ]
    return sum(int(t) for t in found if t is not None) if any(t is not None for t in found) else None


def said(row: sqlite3.Row) -> str | None:
    """What a run's or a chore run's result says, the harness's note first, with its line breaks, and cut."""
    result = contract.stored_object(row["result_json"])
    return lines(str(result.get("harness") or result.get("summary") or ""))[:SUMMARY_LENGTH].rstrip() or None


def lines(text: str) -> str:
    """Agent-written text as a page lays it out: control characters dropped, line breaks kept, trailing space cut."""
    return "\n".join(line.rstrip() for line in conversation.printable(text).splitlines()).strip("\n")


def tickets(ctx: Context) -> list[TicketSummary]:
    """The journal's tickets, most recent activity first."""
    return [summary(ctx.conn, row) for row in db.recent_tickets(ctx.conn, TICKETS)]


def summary(conn: sqlite3.Connection, row: sqlite3.Row) -> TicketSummary:
    """A ticket row, with `active_at` as `db.recent_tickets` adds it, as the tickets list shows it."""
    key = str(row["key"])
    record = conversation.start_of(conn, key)
    status: StartStatus | None = None
    if record is not None:
        status = "started" if record["status"] == "started" else "stopped"
    waiting = conversation.latest_question(conn, key) if status == "started" else None
    running = db.running_run_of(conn, key)
    return TicketSummary(
        key=key,
        private=record is not None,
        start=status,
        phase=str(row["phase"]) if row["phase"] else None,
        last_decision=db.last_decision_of(conn, key),
        done=bool(row["done"]),
        branch=str(row["branch"]) if row["branch"] else None,
        active_at=db.parse_time(str(row["active_at"])),
        latest_message_id=db.latest_message_of(conn, conversation.TICKET, key),
        awaiting=int(waiting["id"]) if waiting is not None else None,
        running_run=int(running["id"]) if running is not None else None,
    )


def ticket(ctx: Context, key: str) -> TicketDetail | None:
    """One ticket, as `canopy show` prints it, or None if the journal has no record of it."""
    rows = db.recent_tickets(ctx.conn, 1, key=key)
    if not rows:
        return None
    [row] = rows
    return TicketDetail(
        ticket=summary(ctx.conn, row),
        units=[
            Unit(
                repo=str(u["repo"]) if u["repo"] else None,
                pr_url=str(u["pr_url"]) if u["pr_url"] else None,
                phase=str(u["phase"]) if u["phase"] else None,
            )
            for u in db.units(ctx.conn, key)
        ],
        runs=[run(r, ctx.workspace.root) for r in db.runs_of(ctx.conn, key, TICKET_RUNS)],
        messages=[message(m) for m in db.messages_of(ctx.conn, conversation.TICKET, key, TICKET_MESSAGES)],
        decisions=[decision(d) for d in db.decisions_about(ctx.conn, key, TICKET_DECISIONS)],
    )


def message(row: sqlite3.Row) -> Message:
    """One message, its body without control characters."""
    source = str(row["source"])
    kind = str(row["kind"])
    comment = None
    if row["comment_id"] is not None:
        comment = Comment(
            id=str(row["comment_id"]),
            author=str(row["author"]),
            at=str(row["commented_at"]),
            truncated=bool(row["truncated"]),
        )
    return Message(
        id=int(row["id"]),
        at=db.parse_time(str(row["at"])),
        # Anything the schema does not know is shown as the least trusted: a tracker comment.
        source=_SOURCES.get(source, "tracker"),
        kind=_KINDS.get(kind, "comment"),
        channel=str(row["channel"]),
        run_id=int(row["run_id"]) if row["run_id"] is not None else None,
        answers=int(row["answers"]) if row["answers"] is not None else None,
        body=conversation.printable(str(row["body"])),
        comment=comment,
    )


def chores(backend: Backend, ctx: Context) -> list[ChoreSummary]:
    """Each configured chore, as `canopy status` lists it: none when `capacity.max_chores` is 0 (DESIGN §19)."""
    now = backend.clock()
    return [chore_summary(ctx.conn, s, now) for s in chore_view.states(ctx.conn, ctx.config, ctx.workspace)]


def chore(backend: Backend, ctx: Context, name: str) -> ChoreDetail | None:
    """One chore, as `canopy show chore:NAME` prints it, or None if it is not defined for this workspace.

    A chore defined while `capacity.max_chores` is 0 has a page, as `canopy reply chore:NAME` takes a note to it.
    """
    defined = chore_view.defined(ctx.config, ctx.workspace)
    if name not in defined:
        return None
    state = chore_view.state_of(ctx.conn, name, defined[name])
    return ChoreDetail(
        chore=chore_summary(ctx.conn, state, backend.clock()),
        runs=[chore_run(r) for r in state.runs[:CHORE_RUNS]],
        notes=[message(m) for m in db.messages_of(ctx.conn, conversation.CHORE, name, conversation.CHORE_NOTES)],
    )


def chore_summary(conn: sqlite3.Connection, state: chore_view.ChoreState, now: datetime) -> ChoreSummary:
    """A chore's state as its line in `canopy status` and the head of `canopy show chore:NAME` say it."""
    defined = state.chore
    running = state.running
    latest = state.latest_ended
    return ChoreSummary(
        name=state.name,
        every_minutes=defined.every_minutes,
        days=list(defined.days),
        hours=defined.hours,
        timezone=defined.timezone,
        when=defined.when or None,
        running=chore_run(running) if running is not None else None,
        latest=chore_run(latest) if latest is not None else None,
        due_at=state.due_at(now),
        findings=[
            ChoreFinding(
                id=f.finding.id,
                title=conversation.printable(f.finding.title),
                detail=conversation.printable(f.finding.detail),
                link=f.finding.link,
                since=db.parse_time(f.since),
            )
            for f in state.findings()
        ],
        latest_note_id=db.latest_message_of(conn, conversation.CHORE, state.name),
    )


def chore_run(row: sqlite3.Row) -> ChoreRun:
    """One chore run's row."""
    status = str(row["status"])
    parsed = chore_result.stored(row["result_json"]) if status == "ok" else None
    return ChoreRun(
        id=int(row["id"]),
        status=status,
        state=_CHORE_STATES.get(status, "failed"),
        started_at=db.parse_time(str(row["started_at"])),
        ended_at=db.parse_time(str(row["ended_at"])) if row["ended_at"] else None,
        summary=said(row),
        findings=len(parsed.findings) if parsed is not None else 0,
        session_id=str(row["session_id"]) if row["session_id"] else None,
        cost_usd=float(row["cost_usd"]) if row["cost_usd"] is not None else None,
        tokens=tokens(row),
        log_path=str(row["log_path"]),
    )


def found(ctx: Context, query: str) -> SearchResults:
    """The journal's rows holding every word of `query` (DESIGN §22, Search). Raises search.BadQueryError."""
    result = search.search(ctx.conn, query)
    return SearchResults(
        words=list(result.words),
        hits=[
            SearchHit(
                source=h.source,
                at=db.parse_time(h.at),
                snippet=h.snippet,
                ticket_key=h.ticket_key,
                chore=h.chore,
                run_id=h.run_id,
                tick_id=h.tick_id,
                label=h.label,
            )
            for h in result.hits
        ],
        more=list(result.more),
    )
