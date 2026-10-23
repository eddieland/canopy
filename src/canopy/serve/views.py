"""Journal rows as the API's models: attention, the loop's state, runs, tickets and their conversations, decisions.

It also holds what the other views share: a run's models, and the text helpers that lay out what an agent wrote.

Reads only. Every text that came from an agent or the tracker stays untrusted: control characters are dropped from
message bodies as `canopy show` drops them, run summaries are cut but keep their line breaks, and the UI renders all of
it as text.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, assert_never

from canopy.core import (
    contract,
    conversation,
    db,
    items,
    notice,
    pause,
    personas,
    plans,
    records,
    run_models,
)
from canopy.core.items import fingerprint
from canopy.core.vocab import ModelsRead, ReviewRunStatus, RunStatus
from canopy.serve import draft_views, memory_views
from canopy.serve.persona_schema import AgentPersona, PersonaChoice
from canopy.serve.schema import (
    AttentionItem,
    Capacity,
    Comment,
    CostTotal,
    Decision,
    Limit,
    LoopState,
    Message,
    MessageKind,
    MessageSource,
    ModelsServed,
    NoticeChannel,
    Pause,
    PauseChannel,
    Run,
    RunActivity,
    RunsSince,
    RunState,
    ServedModel,
    StartStatus,
    TicketSummary,
    WorkerNotice,
)
from canopy.serve.ticket_schema import TicketDetail, TicketForget, Unit
from canopy.serve.transcript_views import raw_output, removed_after, session_transcript

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence
    from datetime import datetime

    from canopy.core.context import Context
    from canopy.serve import backend as served
    from canopy.serve.backend import Backend
    from canopy.serve.transcript_schema import RawOutput, Transcript

# How many runs that ended the runs list carries, after the running ones.
RECENT_RUNS = 50
# How many tickets the tickets list carries, by most recent activity.
TICKETS = 200
# A ticket's page: its latest runs, messages, and decisions.
TICKET_RUNS = 10
TICKET_MESSAGES = 100
TICKET_DECISIONS = 20
SUMMARY_LENGTH = 300
# The windows the spend figures and a chore's spend cover: the last day and the last 30.
SPEND_DAY_HOURS = 24
SPEND_MONTH_HOURS = 30 * 24
_CHORE = "chore:"
_PR = "pr:"
# A one-off task's item (DESIGN §36): no ticket, chore, or PR, but the task's own page.
_TASK = "task:"
_SOURCES: dict[str, MessageSource] = {
    "worker": "worker",
    "operator": "operator",
    "tracker": "tracker",
    "canopy": "canopy",
}
_PAUSE_CHANNELS: dict[str, PauseChannel] = {"loop": "loop", "cli": "cli", "web": "web"}
_NOTICE_CHANNELS: dict[str, NoticeChannel] = {"cli": "cli", "web": "web"}
_KINDS: dict[str, MessageKind] = {
    "report": "report",
    "question": "question",
    "reply": "reply",
    "comment": "comment",
    "note": "note",
}


def attention(backend: Backend, ctx: Context) -> list[AttentionItem]:
    """The attention list, as `canopy status` shows it.

    Returns:
        One item per entry, its subject split into a ticket key, a chore name, a PR, or a task's id, with the ticket's
        title, and its detail without control characters.
    """
    found: list[AttentionItem] = []
    for item in backend.attention(ctx):
        key = item.ticket_key
        chore = key.removeprefix(_CHORE) if key is not None and key.startswith(_CHORE) else None
        pr = key.removeprefix(_PR) if key is not None and key.startswith(_PR) else None
        task = int(key.removeprefix(_TASK)) if key is not None and key.startswith(_TASK) else None
        ticket = key if key is not None and chore is None and pr is None and task is None else None
        row = db.get_ticket(ctx.conn, ticket) if ticket is not None else None
        found.append(
            AttentionItem(
                id=fingerprint(item.ticket_key, item.reason, item.repo),
                subject=item.subject,
                ticket_key=ticket,
                ticket_title=ticket_title(row.title) if row is not None else None,
                chore=chore,
                repo=item.repo,
                reason=item.reason,
                detail=conversation.printable(item.detail),
                since=db.parse_time(item.since),
                finding=item.finding,
                pr=pr,
                task=task,
            ),
        )
    return found


def loop_state(ctx: Context) -> LoopState:
    """Whether the operator paused the loop, and how, the notice to workers, memory's tiers, and what may run at once.

    Returns:
        No pause while the loop runs, and no notice without one in force. A pause's channel the schema does not know
        reads as `loop`, and a notice's as `cli`.
    """
    held = pause.paused(ctx.conn)
    paused = None
    if held is not None:
        paused = Pause(since=db.parse_time(held.since), channel=_PAUSE_CHANNELS.get(held.channel, "loop"))
    remembered = memory_views.state(ctx)
    limits = ctx.config.capacity
    capacity = Capacity(workers=limits.max_workers, reviews=limits.max_reviews, chores=limits.max_chores)
    told = notice.current(ctx.conn)
    if told is None:
        return LoopState(capacity=capacity, paused=paused, memory=remembered)
    worker_notice = WorkerNotice(
        text=told.text,
        since=db.parse_time(told.set_at),
        lapses_at=db.parse_time(told.lapses_at),
        channel=_NOTICE_CHANNELS.get(told.channel, "cli"),
    )
    return LoopState(capacity=capacity, paused=paused, notice=worker_notice, memory=remembered)


def run_raw_output(ctx: Context, run_id: int) -> RawOutput | None:
    """The end of a run's log as written, its setup commands' output and its worker's stderr included (DESIGN §22).

    Returns:
        The tail, without control characters, or a `no_output` status when the log is missing or not a regular file;
        None if there is no such run.
    """
    row = db.get_run(ctx.conn, run_id)
    if row is None:
        return None
    log = Path(str(row["log_path"]))
    return raw_output(log, removed_after(ctx.conn, log, row["ended_at"], "run_files_days"))


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
    served = models_served(ctx.conn, "runs", run_id, ended=row["ended_at"] is not None, session_id=row["session_id"])
    return run(row, root, [shown_path(str(s.slot_path), root) for s in held], served)


def models_served(
    conn: sqlite3.Connection,
    table: run_models.RunTable,
    run_id: int,
    *,
    ended: bool,
    session_id: str | None,
) -> ModelsServed:
    """Which models served a run, as canopy last read them from its session (DESIGN §13, Each agent's model).

    Returns:
        The models when its session was read, else why there are none to show yet, or ever.
    """
    read = run_models.reads_of(conn, table, [run_id]).get(run_id)
    return _served(read, run_models.of_run(conn, table, run_id), ended=ended, session_id=session_id)


def run_transcript(ctx: Context, run_id: int) -> Transcript | None:
    """A run's session in its log, or None if there is no such run.

    Returns:
        The transcript, its status saying whether the run recorded a session and whether its log could be read.
    """
    row = db.get_run(ctx.conn, run_id)
    if row is None:
        return None
    log = Path(str(row["log_path"]))
    return session_transcript(log, row["session_id"], removed_after(ctx.conn, log, row["ended_at"], "run_files_days"))


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
        decider=row.decider.value if row.decider is not None else None,
    )


def runs(ctx: Context) -> list[Run]:
    """Running runs, oldest first, then the ones that ended most recently, the one that ended last first.

    Returns:
        The running runs with the worktrees they hold, then at most `RECENT_RUNS` that ended.
    """
    running = db.running_runs(ctx.conn, "runs")
    recent = db.recent_runs(ctx.conn, RECENT_RUNS)
    slots = db.all_run_slots(ctx.conn, [int(r["id"]) for r in running])
    ended = [int(r["id"]) for r in recent]
    reads, models = run_models.reads_of(ctx.conn, "runs", ended), run_models.of_runs(ctx.conn, "runs", ended)
    root = ctx.workspace.root
    running_models = ModelsServed(status="running")
    return [
        *(
            run(r, root, [shown_path(str(s.slot_path), root) for s in slots[int(r["id"])]], running_models)
            for r in running
        ),
        *(
            run(r, root, models=_served(reads.get(i), models[i], ended=True, session_id=r["session_id"]))
            for i, r in zip(ended, recent, strict=True)
        ),
    ]


def runs_since(ctx: Context, since: datetime) -> RunsSince:
    """What the runs did since `since`: how many ended, and how many PRs they opened.

    A PR counts as opened when a run that ended since names it and no run that ended before does, so a resume naming
    its ticket's PR again opens nothing.

    Returns:
        The counts, from every run the journal holds, not only the recent ones the runs list carries.
    """
    cut = db.format_time(since)
    ended = 0
    named_before: set[str] = set()
    named_since: set[str] = set()
    for row in db.ended_run_results(ctx.conn):
        prs = contract.stored_prs(contract.stored_object(row["result_json"]))
        if str(row["ended_at"]) >= cut:
            ended += 1
            named_since.update(prs)
        else:
            named_before.update(prs)
    return RunsSince(ended=ended, prs_opened=len(named_since - named_before))


def shown_path(path: str, root: Path) -> str:
    """A worktree's path as a page shows it: from the workspace root when under it, else whole.

    A workspace's pool paths then read as `.treehouse/web-3f9c2a1b/1/web`.

    Returns:
        `path` relative to `root`, or unchanged when it is outside it.
    """
    found = Path(path)
    return str(found.relative_to(root)) if found.is_relative_to(root) else path


def run(row: sqlite3.Row, root: Path, worktrees: list[str] | None = None, models: ModelsServed | None = None) -> Run:
    """One run's row, with the worktrees it holds if it is running, its paths from the workspace `root`.

    On the run's own page it carries `models`, the models that served it.

    Returns:
        The run as the API sends it. A status it does not know reads as `failed`.
    """
    result = contract.stored_object(row["result_json"])
    status = str(row["status"])
    return Run(
        id=int(row["id"]),
        ticket_key=str(row["ticket_key"]),
        ticket_title=ticket_title(row["ticket_title"]),
        kind=str(row["kind"]),
        reasons=list(db.reasons_in(row)),
        status=status,
        state=run_state(status),
        private=bool(row["private"]),
        ticket_stopped=bool(row["ticket_stopped"]),
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
        persona=str(row["persona"]) if row["persona"] is not None else None,
        persona_digest=str(row["persona_digest"]) if row["persona_digest"] is not None else None,
        models=models,
    )


def _served(
    read: records.RunModelRead | None,
    models: Sequence[records.RunModel],
    *,
    ended: bool,
    session_id: str | None,
) -> ModelsServed:
    """What a run's last read of its session for its models, `read`, and the `models` it found, show (DESIGN §13).

    Returns:
        The models when the read found them, else why there are none to show yet, or ever.
    """
    if read is None and not ended:
        return ModelsServed(status="running")
    if models:
        # Shown whatever the last read: a read again keeps them while it is due, fails, or finds the session gone.
        return ModelsServed(
            status="found",
            models=[ServedModel(model=m.model, replies=m.replies, cost_usd=m.cost_usd) for m in models],
        )
    if read is None:
        return ModelsServed(status="unread" if session_id else "no_session")
    match read.status:
        case ModelsRead.FOUND:
            return ModelsServed(status="found")
        case ModelsRead.MISSING:
            return ModelsServed(status="missing")
        case ModelsRead.FAILED:
            return ModelsServed(status="failed", error=read.error)
        case _:
            assert_never(read.status)


def _activity(row: sqlite3.Row) -> RunActivity | None:
    if row["activity_tool"] is None or row["activity_at"] is None:
        return None
    return RunActivity(
        tool=str(row["activity_tool"]),
        did=str(row["activity"] or ""),
        at=db.parse_time(str(row["activity_at"])),
    )


def run_state(status: str) -> RunState:
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


def review_state(status: ReviewRunStatus) -> RunState:
    """What the web UI colors a review run that has `status` as, a revision of a review's draft among them.

    Returns:
        The run's state: every ending but `done` is failed.
    """
    match status:
        case ReviewRunStatus.RUNNING:
            return "running"
        case ReviewRunStatus.DONE:
            return "done"
        case ReviewRunStatus.FAILED | ReviewRunStatus.UNKNOWN | ReviewRunStatus.TIMEOUT | ReviewRunStatus.CRASHED:
            return "failed"
        case _:
            assert_never(status)


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


def ticket_title(value: object) -> str | None:
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
        The ticket, with whether it was started privately, the question it awaits, its running run, if any, and
        whether its plan waits on the operator.
    """
    key = str(row["key"])
    record = conversation.start_of(conn, key)
    status: StartStatus | None = None
    if record is not None:
        status = "started" if conversation.is_started(record) else "stopped"
    # A public ticket's questions are on the tracker, but for a planner's, which canopy holds (DESIGN §25).
    waiting = conversation.latest_question(conn, key) if status == "started" else None
    if record is None:
        waiting = plans.question(conn, key)
    running = db.running_run_of(conn, key)
    ticket = db.get_ticket(conn, key)
    return TicketSummary(
        key=key,
        title=ticket_title(row["title"]),
        private=record is not None,
        start=status,
        phase=str(row["phase"]) if row["phase"] else None,
        last_decision=db.last_decision_of(conn, key),
        done=bool(row["done"]),
        branch=str(row["branch"]) if row["branch"] else None,
        active_at=db.parse_time(str(row["active_at"])),
        latest_message_id=db.latest_message_of(conn, conversation.TICKET, key),
        awaiting=waiting.id if waiting is not None else None,
        running_run=running.id if running is not None else None,
        plan_waits=ticket is not None and plans.waits(conn, ticket),
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
            repo=str(u.repo) if u.repo else None,
            pr_url=str(u.pr_url) if u.pr_url else None,
            phase=str(u.phase) if u.phase else None,
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
        forgets=[forget(f) for f in db.forgets_of(ctx.conn, key)],
        decisions=[decision(d) for d in db.decisions_about(ctx.conn, key, TICKET_DECISIONS)],
        cost=_ticket_cost(ctx.conn, key),
        drafts=draft_views.of_ticket(ctx.conn, key),
        personas=[agent_persona(n) for n in personas.next_for(ctx.conn, ctx.config, key)],
        persona_names=[p.name for p in personas.listed(ctx.config)],
    )


def agent_persona(found: personas.Next) -> AgentPersona:
    """The persona one of a ticket's agents writes in at its next run, as the API sends it.

    Returns:
        The agent, its persona, where that comes from, the persona of its next run alone, if one is chosen, and why
        its run would refuse the one it gets, if it would.
    """
    return AgentPersona(
        agent=found.agent,
        persona=found.name,
        source=found.source,
        error=found.error,
        once=found.once,
        several=list(found.several),
    )


def persona_choice(found: personas.Listed) -> PersonaChoice:
    """A persona a run could get, as the API sends it, its error worded as `canopy personas` words it.

    Returns:
        Its name, whether it is the operator's, the agents it is the default for, why a run would refuse it, and
        its description.
    """
    return PersonaChoice(
        name=found.name,
        yours=found.yours,
        defaults=list(found.defaults),
        error=found.error,
        description=found.description,
    )


def forget(found: records.Forget) -> TicketForget:
    """One forget of a ticket, as the API sends it.

    Returns:
        The forget, its PRs decoded from the journal's JSON.
    """
    return TicketForget(
        at=db.parse_time(found.at),
        channel=found.channel,
        run_id=found.run_id,
        message_id=found.message_id,
        branch=found.branch,
        prs=json.loads(found.prs) if found.prs is not None else None,
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
        },
    )


def message(row: records.Message) -> Message:
    """One message, its body without control characters.

    Returns:
        The message as the API sends it, with the tracker comment it came from, if any. A source or kind the schema
        does not know reads as a tracker comment.
    """
    comment = None
    if row.comment_id is not None:
        comment = Comment(
            id=row.comment_id,
            author=str(row.author),
            at=str(row.commented_at),
            truncated=row.truncated,
        )
    return Message(
        id=row.id,
        at=db.parse_time(row.at),
        # Anything the schema does not know is shown as the least trusted: a tracker comment.
        source=_SOURCES.get(row.source, "tracker"),
        kind=_KINDS.get(row.kind, "comment"),
        channel=row.channel,
        run_id=row.run_id,
        task_run_id=row.task_run_id,
        answers=row.answers,
        body=conversation.printable(row.body),
        comment=comment,
    )
