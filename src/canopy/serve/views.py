"""Journal rows as the API's models: attention, runs, tickets and their conversations, chores, ticks, search hits.

Reads only. Every text that came from an agent or the tracker stays untrusted: control characters are dropped from
message bodies as `canopy show` drops them, run summaries are cut to one line, and the UI renders all of it as text.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, assert_never

from canopy.core import (
    chore_result,
    chore_view,
    contract,
    conversation,
    db,
    items,
    notice,
    pause,
    records,
    search,
    transcript,
)
from canopy.core import spend as spending
from canopy.core.items import fingerprint
from canopy.core.vocab import ChoreRunStatus, RunStatus
from canopy.serve.schema import (
    AttentionItem,
    ChoreDetail,
    ChoreFinding,
    ChoreRun,
    ChoreRunDetail,
    ChoreRunFinding,
    ChoreSpend,
    ChoreSpendWindow,
    ChoreSummary,
    Comment,
    CostTotal,
    Decision,
    LastTick,
    Limit,
    LoopState,
    Message,
    MessageKind,
    MessageSource,
    NoticeChannel,
    Pause,
    PauseChannel,
    Run,
    RunActivity,
    RunState,
    SearchHit,
    SearchResults,
    Spend,
    SpendBreakdown,
    SpendCosts,
    SpendDay,
    SpendPullRequest,
    SpendTicket,
    SpendTicks,
    SpendTool,
    SpendUnpriced,
    SpendWindow,
    SpendWoken,
    StartStatus,
    Tick,
    TickDetail,
    TicketDetail,
    TicketSummary,
    TickOutput,
    Transcript,
    TranscriptEntry,
    TranscriptError,
    TranscriptPrompt,
    TranscriptStep,
    TranscriptText,
    TranscriptTokens,
    TranscriptTool,
    Unit,
    WorkerNotice,
)

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.context import Context
    from canopy.serve import backend as served
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
_SOURCES: dict[str, MessageSource] = {"worker": "worker", "operator": "operator", "tracker": "tracker"}
_PAUSE_CHANNELS: dict[str, PauseChannel] = {"loop": "loop", "cli": "cli", "web": "web"}
_NOTICE_CHANNELS: dict[str, NoticeChannel] = {"cli": "cli", "web": "web"}
_KINDS: dict[str, MessageKind] = {"report": "report", "question": "question", "reply": "reply", "comment": "comment"}


def attention(backend: Backend, ctx: Context) -> list[AttentionItem]:
    """The attention list, as `canopy status` shows it.

    Returns:
        One item per entry, its subject split into a ticket key or a chore name, with the ticket's title, and its
        detail without control characters.
    """
    found: list[AttentionItem] = []
    for item in backend.attention(ctx):
        key = item.ticket_key
        chore = key.removeprefix(_CHORE) if key is not None and key.startswith(_CHORE) else None
        pr = key.removeprefix(_PR) if key is not None and key.startswith(_PR) else None
        ticket = key if key is not None and chore is None and pr is None else None
        row = db.get_ticket(ctx.conn, ticket) if ticket is not None else None
        found.append(
            AttentionItem(
                id=fingerprint(item.ticket_key, item.reason, item.repo),
                subject=item.subject,
                ticket_key=ticket,
                ticket_title=_title(row.title) if row is not None else None,
                chore=chore,
                repo=item.repo,
                reason=item.reason,
                detail=conversation.printable(item.detail),
                since=db.parse_time(item.since),
                finding=item.finding,
                pr=pr,
            )
        )
    return found


def spend(backend: Backend, ctx: Context) -> Spend:
    """What the last day and the last 30 days cost, by the backend's clock, and what everything ever cost.

    Returns:
        The cost the journal recorded in each window, with the window's start, and its total.
    """
    now = backend.clock()
    return Spend(
        day=_spent(ctx, now, SPEND_DAY_HOURS),
        month=_spent(ctx, now, SPEND_MONTH_HOURS),
        total_usd=db.spent_ever(ctx.conn),
    )


def _spent(ctx: Context, now: datetime, hours: int) -> SpendWindow:
    since = now - timedelta(hours=hours)
    return SpendWindow(since=since, hours=hours, cost_usd=db.spent_since(ctx.conn, db.format_time(since)))


def spend_breakdown(backend: Backend, ctx: Context, days: int) -> SpendBreakdown:
    """What the last `days` UTC days cost, by the backend's clock, as `canopy spend --days` prints it.

    Returns:
        The breakdown, with the newest idle ticks in the window.
    """
    found = spending.breakdown(ctx.conn, backend.clock(), days)
    return SpendBreakdown(
        since=db.parse_time(found.since),
        days=found.days,
        per_day=[SpendDay(day=d.day, costs=_spend_costs(d.costs), done=d.done) for d in found.per_day],
        totals=_spend_costs(found.totals),
        ticks=[SpendTicks(group=g.group, ticks=g.ticks, cost_usd=g.cost_usd) for g in found.ticks],
        woken=[SpendWoken(by=w.by, ticks=w.ticks, cost_usd=w.cost_usd) for w in found.woken],
        unpriced=[SpendUnpriced(kind=u.kind, runs=u.runs, unpriced=u.unpriced) for u in found.unpriced],
        idle_share=found.idle_share,
        idle_ticks=[
            tick_of(row, int(row["decisions"])) for row in spending.idle_ticks(ctx.conn, found.since, found.until)
        ],
        done=found.done,
        per_done=found.per_done,
        tickets=[
            SpendTicket(
                key=t.key,
                title=t.title,
                runs=t.runs,
                reviews=t.reviews,
                cost_usd=t.cost_usd,
                done=t.done,
                done_at=db.parse_time(t.done_at) if t.done_at is not None else None,
            )
            for t in found.tickets
        ],
        pull_requests=[
            SpendPullRequest(
                url=p.url, ticket_key=p.ticket, phase=p.phase, runs=p.runs, reviews=p.reviews, cost_usd=p.cost_usd
            )
            for p in found.pull_requests
        ],
        tools=[
            SpendTool(
                kind=t.kind,
                tool=t.tool,
                runs=t.runs,
                calls=t.calls,
                errors=t.errors,
                result_chars=t.result_chars,
                est_tokens=t.est_tokens,
            )
            for t in found.tools
        ],
    )


def _spend_costs(costs: spending.Costs) -> SpendCosts:
    return SpendCosts(
        overseer=costs.overseer,
        idle=costs.idle,
        dry_run=costs.dry_run,
        workers=costs.workers,
        chores=costs.chores,
        reviews=costs.reviews,
        total=costs.total,
    )


def last_tick(ctx: Context) -> LastTick:
    """The latest tick, and the newest message the latest `ok` tick read.

    Returns:
        The latest tick, None before the first, and the message's id, None before an `ok` tick recorded one.
    """
    return LastTick(tick=tick(ctx), acknowledged=db.acknowledged_message_id(ctx.conn))


def loop_state(ctx: Context) -> LoopState:
    """Whether the operator paused the loop, since when, and through which channel, and the notice to workers in force.

    Returns:
        No pause while the loop runs, and no notice without one in force. A pause's channel the schema does not know
        reads as `loop`, and a notice's as `cli`.
    """
    held = pause.paused(ctx.conn)
    paused = None
    if held is not None:
        paused = Pause(since=db.parse_time(held.since), channel=_PAUSE_CHANNELS.get(held.channel, "loop"))
    told = notice.current(ctx.conn)
    if told is None:
        return LoopState(paused=paused)
    worker_notice = WorkerNotice(
        text=told.text,
        since=db.parse_time(told.set_at),
        lapses_at=db.parse_time(told.lapses_at),
        channel=_NOTICE_CHANNELS.get(told.channel, "cli"),
    )
    return LoopState(paused=paused, notice=worker_notice)


def tick(ctx: Context) -> Tick | None:
    """The latest tick, or None before the first.

    Returns:
        The tick, with how many decisions it recorded.
    """
    row = db.last_tick(ctx.conn)
    if row is None:
        return None
    return tick_of(row, db.decision_count(ctx.conn, int(row["id"])))


def tick_of(row: sqlite3.Row, decisions: int) -> Tick:
    """A tick's row, and how many decisions it recorded.

    Returns:
        The tick as the API sends it, its summary laid out as a page shows it and None when empty.
    """
    return Tick(
        id=int(row["id"]),
        status=str(row["status"]),
        dry_run=bool(row["dry_run"]),
        started_at=db.parse_time(row["started_at"]),
        ended_at=db.parse_time(row["ended_at"]) if row["ended_at"] else None,
        summary=lines(str(row["summary"] or "")) or None,
        session_id=str(row["session_id"]) if row["session_id"] else None,
        cost_usd=float(row["cost_usd"]) if row["cost_usd"] is not None else None,
        new_tokens=new_tokens(row),
        peak_context=int(row["tokens_peak_context"]) if row["tokens_peak_context"] is not None else None,
        decisions=decisions,
        idle=None if row["idle"] is None else bool(row["idle"]),
        woken_by=str(row["woken_by"]) if row["woken_by"] is not None else None,
    )


def ticks(ctx: Context) -> list[Tick]:
    """The latest ticks, newest first.

    Returns:
        At most `TICKS` ticks, each with how many decisions it recorded.
    """
    return [tick_of(row, int(row["decisions"])) for row in db.recent_ticks(ctx.conn, TICKS)]


def tick_detail(ctx: Context, tick_id: int) -> TickDetail | None:
    """One tick and its decisions, as `canopy decisions ID` prints them, or None if there is no such tick.

    Returns:
        The tick, its decisions, and its output's path from the workspace root, None when the file is missing.
    """
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
    return session_transcript(tick_output(ctx, tick_id), row["session_id"])


def tick_raw_output(ctx: Context, tick_id: int) -> TickOutput | None:
    """The end of a tick's output as written, or None if there is no such tick.

    Returns:
        The tail, without control characters, or a `no_output` status when the file is missing or not a regular file.
    """
    if db.get_tick(ctx.conn, tick_id) is None:
        return None
    found = transcript.tail(tick_output(ctx, tick_id))
    if found is None:
        return TickOutput(status="no_output")
    return TickOutput(status="read", text=found.text, size=found.size, truncated=found.truncated)


def run_detail(ctx: Context, run_id: int) -> Run | None:
    """One run, with the worktrees it holds if it is running, or None if there is no such run.

    Returns:
        The run, the worktrees' paths from the workspace root.
    """
    row = db.get_run(ctx.conn, run_id)
    if row is None:
        return None
    root = ctx.workspace.root
    held = db.all_run_slots(ctx.conn, [run_id] if row["status"] == "running" else []).get(run_id, [])
    return run(row, root, [shown_path(str(s["slot_path"]), root) for s in held])


def run_transcript(ctx: Context, run_id: int) -> Transcript | None:
    """A run's session in its log, or None if there is no such run.

    Returns:
        The transcript, its status saying whether the run recorded a session and whether its log could be read.
    """
    row = db.get_run(ctx.conn, run_id)
    if row is None:
        return None
    return session_transcript(Path(str(row["log_path"])), row["session_id"])


def session_transcript(path: Path, session: object) -> Transcript:
    """The events of the session the journal recorded, read back from the file they were printed to (DESIGN §22).

    Returns:
        The entries read, with status `no_session` when the journal recorded no session, or `no_log` when the file is
        missing or not a regular file; and the prompt kept beside the file, whatever the status.
    """
    kept = transcript.prompt(transcript.prompt_path(path))
    prompt = TranscriptPrompt(text=kept.text, truncated=kept.truncated) if kept is not None else None
    if not isinstance(session, str) or not session:
        return Transcript(status="no_session", prompt=prompt)
    found = transcript.read(path, session)
    if found is None:
        return Transcript(status="no_log", session_id=session, prompt=prompt)
    return Transcript(
        status="read",
        session_id=session,
        entries=[transcript_entry(e) for e in found.entries],
        truncated=found.truncated,
        unreadable=found.unreadable,
        prompt=prompt,
    )


def transcript_entry(entry: transcript.Entry) -> TranscriptEntry:
    """One entry of a transcript as the API sends it.

    Returns:
        The model for the entry's kind: text, a tool call, a step, or an error.
    """
    match entry:
        case transcript.Text():
            return TranscriptText(
                at=entry.at, text=entry.text, reasoning=entry.reasoning, cut=entry.cut, call=entry.call
            )
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
                call=entry.call,
            )
        case transcript.Step():
            t = entry.tokens
            return TranscriptStep(
                at=entry.at,
                reason=entry.reason,
                cost_usd=entry.cost_usd,
                tokens=t.total if t is not None else None,
                split=TranscriptTokens(**vars(t)) if t is not None else None,
                call=entry.call,
            )
        case transcript.Error():
            return TranscriptError(at=entry.at, name=entry.name, message=entry.message, call=entry.call)


def decision(row: records.Decision) -> Decision:
    """One decision, named as `canopy decisions` names it, its rationale with its line breaks.

    Returns:
        The decision, its subject `chore:NAME` for a chore, `pr:URL` for a PR with no ticket, else the ticket's.
    """
    if row.chore is not None:
        subject = f"{_CHORE}{row.chore}"
    elif row.ticket_key is None and row.pr is not None:
        subject = f"{_PR}{row.pr}"
    else:
        subject = items.subject(row.ticket_key, row.repo)
    return Decision(
        id=row.id,
        tick_id=row.tick_id,
        at=db.parse_time(row.created_at),
        subject=subject,
        ticket_key=row.ticket_key,
        repo=row.repo,
        chore=row.chore,
        pr=row.pr,
        action=row.action,
        rationale=lines(row.rationale),
    )


def runs(ctx: Context) -> list[Run]:
    """Running runs, oldest first, then the ones that ended most recently, the one that ended last first.

    Returns:
        The running runs with the worktrees they hold, then at most `RECENT_RUNS` that ended.
    """
    running = db.running_runs(ctx.conn, "runs")
    slots = db.all_run_slots(ctx.conn, [int(r["id"]) for r in running])
    root = ctx.workspace.root
    return [
        *(run(r, root, [shown_path(str(s["slot_path"]), root) for s in slots[int(r["id"])]]) for r in running),
        *(run(r, root) for r in db.recent_runs(ctx.conn, RECENT_RUNS)),
    ]


def shown_path(path: str, root: Path) -> str:
    """A worktree's path as a page shows it: from the workspace root when under it, else whole.

    A workspace's pool paths then read as `.treehouse/web-3f9c2a1b/1/web`.

    Returns:
        `path` relative to `root`, or unchanged when it is outside it.
    """
    found = Path(path)
    return str(found.relative_to(root)) if found.is_relative_to(root) else path


def run(row: sqlite3.Row, root: Path, worktrees: list[str] | None = None) -> Run:
    """One run's row, with the worktrees it holds if it is running, its paths from the workspace `root`.

    Returns:
        The run as the API sends it. A status it does not know reads as `failed`.
    """
    result = contract.stored_object(row["result_json"])
    status = str(row["status"])
    return Run(
        id=int(row["id"]),
        ticket_key=str(row["ticket_key"]),
        ticket_title=_title(row["ticket_title"]),
        kind=str(row["kind"]),
        status=status,
        state=_run_state(status),
        private=bool(row["private"]),
        branch=str(row["branch"]) or None,
        started_at=db.parse_time(str(row["started_at"])),
        ended_at=db.parse_time(str(row["ended_at"])) if row["ended_at"] else None,
        summary=said(row),
        prs=contract.stored_prs(result),
        session_id=str(row["session_id"]) if row["session_id"] else None,
        cost_usd=float(row["cost_usd"]) if row["cost_usd"] is not None else None,
        new_tokens=new_tokens(row),
        peak_context=int(row["tokens_peak_context"]) if row["tokens_peak_context"] is not None else None,
        worktrees=worktrees or [],
        log_path=shown_path(str(row["log_path"]), root),
        activity=_activity(row) if status == "running" else None,
    )


def _activity(row: sqlite3.Row) -> RunActivity | None:
    if row["activity_tool"] is None or row["activity_at"] is None:
        return None
    return RunActivity(
        tool=str(row["activity_tool"]), did=str(row["activity"] or ""), at=db.parse_time(str(row["activity_at"]))
    )


def _run_state(status: str) -> RunState:
    """What the web UI colors a run that has `status` as (DESIGN §22).

    Returns:
        The run's state. A status canopy does not know reads as `failed`.
    """
    try:
        known = RunStatus(status)
    except ValueError:
        return "failed"
    match known:
        case RunStatus.RUNNING:
            return "running"
        case RunStatus.BLOCKED:
            return "blocked"
        case RunStatus.DONE:
            return "done"
        case RunStatus.STOPPED:
            return "stopped"
        case RunStatus.FAILED | RunStatus.UNKNOWN | RunStatus.UNPUSHED | RunStatus.CRASHED | RunStatus.TIMEOUT:
            return "failed"
        case _:
            assert_never(known)


def new_tokens(row: sqlite3.Row | records.Row) -> int | None:
    """A run's, a chore run's, or a tick's tokens, every kind but cache reads; None when the runtime reported none.

    Cache reads are left out: each model call reads again what the calls before it were sent, so their sum grows with
    the number of calls. The peak context says how large that grew.

    Returns:
        The sum of the counts the runtime reported, a missing one counting as none.
    """
    values = records.columns(row)
    found = [values[c] for c in ("tokens_input", "tokens_output", "tokens_reasoning", "tokens_cache_write")]
    return sum(int(t) for t in found if t is not None) if any(t is not None for t in found) else None


def said(row: sqlite3.Row | records.Row) -> str | None:
    """What a run's or a chore run's result says, the harness's note first, with its line breaks, and cut.

    Returns:
        At most `SUMMARY_LENGTH` characters, or None when the result says nothing.
    """
    note = contract.stored_note(contract.stored_object(records.columns(row)["result_json"]))
    return lines(note)[:SUMMARY_LENGTH].rstrip() or None


def lines(text: str) -> str:
    """Agent-written text as a page lays it out: control characters dropped, line breaks kept, trailing space cut.

    Returns:
        The text, without blank lines at its start or end.
    """
    return "\n".join(line.rstrip() for line in conversation.printable(text).splitlines()).strip("\n")


def _title(value: object) -> str | None:
    """A ticket's title on one line. `canopy ticket set` stored it so; this keeps a page from relying on that.

    Returns:
        The title, its whitespace collapsed and control characters dropped, or None when it is missing or empty.
    """
    return " ".join(conversation.printable(str(value)).split()) or None if value else None


def tickets(ctx: Context) -> list[TicketSummary]:
    """The journal's tickets, most recent activity first.

    Returns:
        At most `TICKETS` tickets, as the tickets list shows them.
    """
    return [summary(ctx.conn, row) for row in db.recent_tickets(ctx.conn, TICKETS)]


def summary(conn: sqlite3.Connection, row: sqlite3.Row) -> TicketSummary:
    """A ticket row, with `active_at` as `db.recent_tickets` adds it, as the tickets list shows it.

    Returns:
        The ticket, with whether it was started privately, the question it awaits, and its running run, if any.
    """
    key = str(row["key"])
    record = conversation.start_of(conn, key)
    status: StartStatus | None = None
    if record is not None:
        status = "started" if conversation.is_started(record) else "stopped"
    waiting = conversation.latest_question(conn, key) if status == "started" else None
    running = db.running_run_of(conn, key)
    return TicketSummary(
        key=key,
        title=_title(row["title"]),
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


def ticket(backend: Backend, ctx: Context, key: str) -> TicketDetail | None:
    """One ticket, as `canopy show` prints it, or None if the journal has no record of it.

    Returns:
        The ticket, its units, its limits, and its latest runs, messages, and decisions.
    """
    rows = db.recent_tickets(ctx.conn, 1, key=key)
    if not rows:
        return None
    [row] = rows
    units = [
        Unit(
            repo=str(u["repo"]) if u["repo"] else None,
            pr_url=str(u["pr_url"]) if u["pr_url"] else None,
            phase=str(u["phase"]) if u["phase"] else None,
        )
        for u in db.units(ctx.conn, key)
    ]
    reviews = [
        (u.repo, found)
        for u in units
        if u.pr_url is not None and (found := backend.review_limit(ctx, u.pr_url)) is not None
    ]
    return TicketDetail(
        ticket=summary(ctx.conn, row),
        units=units,
        limits=[limit(found) for found in backend.limits(ctx, key)]
        + [limit(found, repo=repo) for repo, found in reviews],
        runs=[run(r, ctx.workspace.root) for r in db.runs_of(ctx.conn, key, TICKET_RUNS)],
        messages=[message(m) for m in db.messages_of(ctx.conn, conversation.TICKET, key, TICKET_MESSAGES)],
        decisions=[decision(d) for d in db.decisions_about(ctx.conn, key, TICKET_DECISIONS)],
        cost=_ticket_cost(ctx.conn, key),
    )


def _ticket_cost(conn: sqlite3.Connection, key: str) -> CostTotal:
    row = db.ticket_cost(conn, key)
    cost = row["cost_usd"]
    return CostTotal(
        runs=int(row["runs"]),
        reviews=int(row["reviews"]),
        priced=int(row["priced"]),
        cost_usd=float(cost) if cost is not None else None,
    )


def limit(found: served.Limit, *, repo: str | None = None) -> Limit:
    """A limit the backend found, as the API sends it; `repo` names the unit whose PR a review limit is on.

    Returns:
        The limit, its repository `repo` when the backend's names none.
    """
    return Limit.model_validate(
        {
            "kind": found.kind,
            "repo": found.repo or repo,
            "pr_url": found.pr_url,
            "runs": found.runs,
            "granted": found.granted,
            "limit": found.limit,
        }
    )


def message(row: sqlite3.Row) -> Message:
    """One message, its body without control characters.

    Returns:
        The message as the API sends it, with the tracker comment it came from, if any. A source or kind the schema
        does not know reads as a tracker comment.
    """
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
        latest_note_id=db.latest_message_of(conn, conversation.CHORE, state.name),
        spend=ChoreSpend(
            day=_chore_spent(conn, state.name, now, SPEND_DAY_HOURS),
            month=_chore_spent(conn, state.name, now, SPEND_MONTH_HOURS),
        ),
    )


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
    return ChoreRunDetail(
        chore=name,
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
    )


def chore_run_transcript(ctx: Context, name: str, run_id: int) -> Transcript | None:
    """A chore run's session in its log, or None if chore `name` has no such run.

    Returns:
        The transcript, its status saying whether the run recorded a session and whether its log could be read.
    """
    row = _chore_run_of(ctx.conn, name, run_id)
    if row is None:
        return None
    return session_transcript(Path(row.log_path), row.session_id)


def _chore_run_of(conn: sqlite3.Connection, name: str, run_id: int) -> records.ChoreRun | None:
    row = db.get_chore_run(conn, run_id)
    return row if row is not None and row.chore == name else None


def found(ctx: Context, query: str) -> SearchResults:
    """The journal's rows holding every word of `query` (DESIGN §22, Search). Raises search.BadQueryError.

    Returns:
        The words searched for, the hits, and the sources that had more hits than were read.
    """
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
