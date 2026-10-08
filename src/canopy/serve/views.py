"""Journal rows as the API's models: the attention list, runs, tickets, and their conversations (DESIGN §22).

Reads only. Every text that came from an agent or the tracker stays untrusted: control characters are dropped from
message bodies as `canopy show` drops them, run summaries are cut to one line, and the UI renders all of it as text.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import contract, conversation, db
from canopy.core.items import fingerprint
from canopy.serve.schema import (
    AttentionItem,
    Comment,
    Message,
    MessageKind,
    MessageSource,
    Run,
    RunState,
    StartStatus,
    TicketDetail,
    TicketSummary,
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
SUMMARY_LENGTH = 300
_CHORE = "chore:"
_PR = "pr:"
_STATES: dict[str, RunState] = {"running": "running", "blocked": "blocked", "done": "done", "stopped": "stopped"}
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


def runs(ctx: Context) -> list[Run]:
    """Running runs, oldest first, then the ones that ended most recently, newest first."""
    running = db.running_runs(ctx.conn)
    slots = db.all_run_slots(ctx.conn, [int(r["id"]) for r in running])
    root = ctx.workspace.root
    return [
        *(run(r, [shown_path(str(s["slot_path"]), root) for s in slots[int(r["id"])]]) for r in running),
        *(run(r) for r in db.recent_runs(ctx.conn, RECENT_RUNS)),
    ]


def shown_path(path: str, root: Path) -> str:
    """A worktree's path as a page shows it: from the workspace root when under it, else whole.

    A workspace's pool paths then read as `.treehouse/web-3f9c2a1b/1/web`; a workspace of one's pool, under
    `~/.treehouse` by default, is shown whole.
    """
    found = Path(path)
    return str(found.relative_to(root)) if found.is_relative_to(root) else path


def run(row: sqlite3.Row, worktrees: list[str] | None = None) -> Run:
    """One run's row, with the worktrees it holds if it is running."""
    result = contract.stored_object(row["result_json"])
    said = str(result.get("harness") or result.get("summary") or "")
    summary = " ".join(conversation.printable(said).split())
    tokens = [
        row[c] for c in ("tokens_input", "tokens_output", "tokens_reasoning", "tokens_cache_read", "tokens_cache_write")
    ]
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
        summary=summary[:SUMMARY_LENGTH] or None,
        prs=contract.stored_prs(result),
        session_id=str(row["session_id"]) if row["session_id"] else None,
        cost_usd=float(row["cost_usd"]) if row["cost_usd"] is not None else None,
        tokens=sum(int(t) for t in tokens if t is not None) if any(t is not None for t in tokens) else None,
        worktrees=worktrees or [],
        log_path=str(row["log_path"]),
    )


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
        runs=[run(r) for r in db.runs_of(ctx.conn, key, TICKET_RUNS)],
        messages=[message(m) for m in db.messages_of(ctx.conn, conversation.TICKET, key, TICKET_MESSAGES)],
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
