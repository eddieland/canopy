"""The attention list: what needs a human, derived from the journal (DESIGN §14).

Attention items are decisions with action `attention:<reason>`, recorded every tick the cause holds: by the overseer
for what it reads in the world, and by the harness for runs that ended in a way a human must look at (`from_runs`). The
current list is therefore the items of the latest tick whose overseer finished; an item disappears when a tick no
longer records it. A tick that could not run the overseer because `canopy` does not work for it adds one item of its own
to that list, while it is the latest tick.

A chore's open findings are on the list too, from its latest `ok` run, and a chore whose latest run failed has a
`chore_failed` item the harness records each tick (DESIGN §19). Both are about a chore, named `chore:<name>` where a
ticket key would be, which no ticket key can equal. Only chores configured for this workspace are listed, and no
finding the operator dismissed (`listed`).

After every tick, `publish` rewrites `<state_dir>/attention.md` and hands the list to the notification sinks
(`canopy.notify`), each told about each open item once however many ticks it lasts (DESIGN §20).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NotRequired, TypedDict

from canopy.core import chore_view, conversation, db
from canopy.core.items import Item, age, fingerprint, one_line, subject
from canopy.infra import logs
from canopy.notify import deliver

if TYPE_CHECKING:
    from canopy.core.context import Context

ACTION_PREFIX = "attention:"
# Where a ticket key would be, an item about a chore names it so, and one about a PR with no ticket. A ticket key has
# no colon (DESIGN §17), so neither can equal one.
CHORE_PREFIX = "chore:"
PR_PREFIX = "pr:"
# Run statuses a human must look at, and the attention reason each one raises. `unknown` and `timeout` both mean the
# worker left no usable result line. `blocked` and `stopped` raise none: a blocked worker asked a question, which
# reaches the operator on the ticket or as `awaiting_reply`, and the operator stopped a stopped one (DESIGN §22).
RUN_REASONS = {
    "crashed": "crashed",
    "unpushed": "unpushed",
    "unknown": "unknown_result",
    "timeout": "unknown_result",
    "failed": "worker_failed",
}
# A tick that found `canopy` not working for the overseer closes with this status and raises this item (DESIGN §6).
UNAVAILABLE = "canopy_unavailable"
# What the harness records itself (`tick._record_harness_items`, and `UNAVAILABLE`), so the overseer does not.
HARNESS_REASONS = frozenset(
    {*RUN_REASONS.values(), "awaiting_reply", chore_view.FAILED_REASON, "repo_missing", UNAVAILABLE}
)
# How far back to look when working out how long an item has been open.
_HISTORY_TICKS = 1000
FILE_NAME = "attention.md"
# Kept importable from here: tests and the CLI name items through this module.
__all__ = [
    "ACTION_PREFIX",
    "CHORE_PREFIX",
    "FILE_NAME",
    "Item",
    "age",
    "current",
    "fingerprint",
    "keys",
    "listed",
    "subject",
]


def decided_about(decision: sqlite3.Row) -> str:
    """Name what a decision is about, for display: its ticket, `chore:<name>`, its repository, or `-` for the tick.

    Returns:
        The chore with its prefix, else the PR with its prefix when there is no ticket, else the ticket key, else the
        repository, else `-`.
    """
    if decision["chore"] is not None:
        return f"{CHORE_PREFIX}{decision['chore']}"
    if decision["ticket_key"] is None and decision["pr"] is not None:
        return f"{PR_PREFIX}{decision['pr']}"
    return str(decision["ticket_key"] or decision["repo"] or "-")


# An item is its ticket, its reason, and its repository if it has one.
_ItemId = tuple[str | None, str, str | None]


def keys(items: list[Item]) -> set[_ItemId]:
    """Each item's identity, as two lists are compared: its ticket, its reason, and its repository.

    Returns:
        The set of `(ticket_key, reason, repo)` tuples, one per distinct item.
    """
    return {(i.ticket_key, i.reason, i.repo) for i in items}


def _sort_key(item_id: _ItemId) -> tuple[str, str, str]:
    return (item_id[0] or "", item_id[1], item_id[2] or "")


def current(conn: sqlite3.Connection) -> list[Item]:
    """Return the current attention list, sorted by ticket key and reason."""
    ticks = [
        int(r[0])
        for r in conn.execute(
            "SELECT id FROM ticks WHERE status = 'ok' ORDER BY id DESC LIMIT ?",
            (_HISTORY_TICKS,),
        )
    ]
    if not ticks:
        return _unavailable(conn, None)
    # Only the placeholder count is interpolated; the tick ids are bound parameters.
    rows = conn.execute(
        f"SELECT tick_id, ticket_key, action, rationale, created_at, repo, chore, pr FROM decisions "  # noqa: S608
        f"WHERE action LIKE 'attention:%' AND tick_id IN ({','.join('?' * len(ticks))}) ORDER BY id",
        ticks,
    ).fetchall()
    by_tick: dict[int, dict[_ItemId, tuple[str, str]]] = {t: {} for t in ticks}
    for r in rows:
        key = None if r["ticket_key"] is None else str(r["ticket_key"])
        if r["chore"] is not None:
            key = f"{CHORE_PREFIX}{r['chore']}"
        elif key is None and r["pr"] is not None:
            key = f"{PR_PREFIX}{r['pr']}"
        repo = None if r["repo"] is None else str(r["repo"])
        item_id: _ItemId = (key, str(r["action"]).removeprefix(ACTION_PREFIX), repo)
        by_tick[int(r["tick_id"])].setdefault(item_id, (str(r["rationale"]), str(r["created_at"])))

    latest = by_tick[ticks[0]]
    items: list[Item] = []
    for item_id in sorted(latest, key=_sort_key):
        detail, since = latest[item_id]
        for tick_id in ticks[1:]:
            earlier = by_tick[tick_id].get(item_id)
            if earlier is None:
                break
            since = earlier[1]
        items.append(Item(item_id[0], item_id[1], detail, since, item_id[2]))
    return items + _unavailable(conn, ticks[0])


def _unavailable(conn: sqlite3.Connection, last_ok: int | None) -> list[Item]:
    """The `canopy_unavailable` item, while the latest ended tick closed so (DESIGN §6 step 5).

    That tick ran no overseer, so it leaves the list standing as a failed tick does, and adds this one item: the cause
    is canopy's own, and the operator hears of it at once rather than after `loop.failing`'s streak. It is gone at the
    first tick that ends otherwise.

    Returns:
        The item, open since the first tick of the streak after `last_ok`, or nothing.
    """
    latest = conn.execute("SELECT status FROM ticks WHERE status != 'running' ORDER BY id DESC LIMIT 1").fetchone()
    if latest is None or latest[0] != UNAVAILABLE:
        return []
    rows = conn.execute(
        "SELECT rationale, created_at FROM decisions WHERE action = ? AND tick_id > ? ORDER BY id",
        (f"{ACTION_PREFIX}{UNAVAILABLE}", last_ok or 0),
    ).fetchall()
    if not rows:
        return []
    return [Item(None, UNAVAILABLE, str(rows[-1]["rationale"]), str(rows[0]["created_at"]))]


class OpenItem(TypedDict):
    """An open item the overseer recorded: its ticket, or its PR when it has none, and its repository if it has one."""

    ticket: NotRequired[str | None]
    pr: NotRequired[str]
    repo: NotRequired[str]
    reason: str
    since: str


def for_overseer(conn: sqlite3.Connection) -> list[OpenItem]:
    """The open items the overseer recorded, for its state block (DESIGN §6 step 4, ROADMAP M28).

    An item stays open only while each tick records it again, so the overseer is shown what it would drop by leaving
    one out. Items the harness raises itself, and chores', are left out: the overseer never records those. So is
    every detail, which may quote a comment: the item's subject, reason, and age say which one it is.

    Returns:
        One object per item: its ticket, or its PR when it has no ticket; its repository when it has one; its reason;
        and since when it has been open.
    """
    found: list[OpenItem] = []
    for item in current(conn):
        key = item.ticket_key
        if item.reason in HARNESS_REASONS or (key is not None and key.startswith(CHORE_PREFIX)):
            continue
        found.append(
            {
                **(
                    {"pr": key.removeprefix(PR_PREFIX)}
                    if key is not None and key.startswith(PR_PREFIX)
                    else {"ticket": key}
                ),
                **({"repo": item.repo} if item.repo is not None else {}),
                "reason": item.reason,
                "since": item.since,
            }
        )
    return found


def listed(ctx: Context) -> list[Item]:
    """Return the attention list as it is shown and notified: `current`, with the chores this workspace runs.

    A chore deleted from the config, or one whose workspaces leave this one out, is not listed at all, nor is a finding
    the operator dismissed (DESIGN §19).
    """
    configured = set(chore_view.configured(ctx.config, ctx.workspace))
    items = [
        i
        for i in current(ctx.conn)
        if i.ticket_key is None
        or not i.ticket_key.startswith(CHORE_PREFIX)
        or i.ticket_key.removeprefix(CHORE_PREFIX) in configured
    ]
    findings = [
        Item(
            f"{CHORE_PREFIX}{f.chore}",
            f.finding.id,
            " ".join(part for part in (f.finding.title, f.finding.link or "") if part),
            f.since,
            finding=True,
        )
        for f in chore_view.open_findings(ctx.conn, ctx.config, ctx.workspace, starts=ctx.finding_starts)
        if not f.dismissed
    ]
    return items + findings


@dataclass(frozen=True)
class RunItem:
    """An attention item the harness raises for a run."""

    ticket_key: str
    reason: str
    detail: str


def from_runs(conn: sqlite3.Connection) -> list[RunItem]:
    """Return an item for each open ticket whose latest run ended in a status listed in RUN_REASONS.

    The cause holds until a newer run starts for the ticket, the ticket is marked done, or the operator forgets its
    work.
    """
    done = {str(r[0]) for r in conn.execute("SELECT key FROM tickets WHERE done = 1")}
    items: list[RunItem] = []
    for key, run in sorted(db.latest_runs(conn).items()):
        reason = RUN_REASONS.get(str(run["status"]))
        if reason is None or key in done:
            continue
        items.append(RunItem(key, reason, _detail(run)))
    return items


def _detail(run: sqlite3.Row) -> str:
    note = ""
    if run["result_json"]:
        try:
            result: object = json.loads(str(run["result_json"]))
        except json.JSONDecodeError:
            result = None
        if isinstance(result, dict):
            harness: object = result.get("harness")
            summary: object = result.get("summary")
            note = str(harness or summary or "")
    # A split works on no branch. The run is named as `canopy show` reads it, and as the web UI names it.
    what = f"{run['kind']}, {run['branch']}" if run["branch"] else str(run["kind"])
    text = f"run:{run['id']} ({what}) ended {run['status']}"
    if note:
        text += f": {note}"
    return f"{text}; log {run['log_path']}"[:2000]


def awaiting_detail(waiting: conversation.Awaiting) -> str:
    """The `awaiting_reply` item's detail: the question, and how to answer it (DESIGN §22).

    Returns:
        The message id and the question on one line, cut to 1800 characters, then the `canopy reply` to answer it.
    """
    text = f"message {waiting.message_id}: {one_line(waiting.question)}"
    return f"{text[:1800]}; answer with `canopy reply {waiting.key}`"


def render(items: list[Item], now: datetime) -> str:
    """Return `attention.md`: the items grouped by reason, one line each with key, age, and detail."""
    stamp = now.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = ["# canopy attention", ""]
    if not items:
        lines += [f"Nothing needs you. Updated {stamp}.", ""]
        return "\n".join(lines)
    count = f"{len(items)} item{'s' if len(items) != 1 else ''}"
    lines += [f"{count}, updated {stamp}. An item leaves this list when its cause is gone.", ""]
    reasons = [i for i in items if not i.finding]
    for reason in sorted({i.reason for i in reasons}):
        lines += [f"## {reason}", ""]
        lines += [f"- {i.subject}, {age(i.since, now)}: {one_line(i.detail)}" for i in reasons if i.reason == reason]
        lines.append("")
    # A section per chore after the ticket items: one line per finding, with its title, age, and link (DESIGN §19).
    findings = [i for i in items if i.finding]
    for chore in sorted({i.subject for i in findings}):
        lines += [f"## {chore}", ""]
        lines += [f"- {one_line(i.detail)}, {age(i.since, now)} ({i.reason})" for i in findings if i.subject == chore]
        lines.append("")
    return "\n".join(lines)


def publish(ctx: Context, log: logs.TickAdapter) -> None:
    """Rewrite `attention.md` and deliver to the notification sinks (DESIGN §6 step 7, §20).

    Failures are logged, never raised: the tick is already closed. A delivery that fails is tried again next tick.
    """
    items = write(ctx, log)
    dismissed = {
        fingerprint(f"{CHORE_PREFIX}{f.chore}", f.finding.id, None)
        for f in chore_view.open_findings(ctx.conn, ctx.config, ctx.workspace)
        if f.dismissed
    }
    try:
        deliver.publish(ctx, items, ctx.state_dir / FILE_NAME, log, dismissed=dismissed)
    except Exception as e:
        log.exception("notification failed", extra={"error": str(e)})


def write(ctx: Context, log: logs.TickAdapter) -> list[Item]:
    """Rewrite `attention.md` from the journal: after a tick, and after the operator dismisses a finding.

    A failure is logged, never raised.

    Returns:
        The list as written.
    """
    items = listed(ctx)
    path = ctx.state_dir / FILE_NAME
    try:
        logs.write_private(path, render(items, datetime.now(UTC)))
    except OSError as e:
        log.error("could not write the attention list", extra={"path": str(path), "error": str(e)})  # noqa: TRY400
    return items
