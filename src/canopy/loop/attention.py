"""The attention list: what needs a human, derived from the journal (DESIGN §14).

Attention items are decisions with action `attention:<reason>`, recorded every tick the cause holds: by the overseer
for what it reads in the world, and by the harness for runs that ended in a way a human must look at (`from_runs`). The
current list is therefore the items of the latest tick whose overseer finished; an item disappears when a tick no
longer records it.

After every tick, `publish` rewrites `<state_dir>/attention.md` and, when `notify.cmd` is set, pipes it what changed
since the last notification. The `notifications` table holds the items already notified that are still open, so an
open item is notified once however many ticks it lasts.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from canopy.core import db
from canopy.core.config import notify_words
from canopy.infra import logs, procs

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.core.context import Context

ACTION_PREFIX = "attention:"
# Run statuses a human must look at, and the attention reason each one raises. `unknown` and `timeout` both mean the
# worker left no usable result line.
RUN_REASONS = {
    "crashed": "crashed",
    "unpushed": "unpushed",
    "unknown": "unknown_result",
    "timeout": "unknown_result",
    "failed": "worker_failed",
}
# How far back to look when working out how long an item has been open.
_HISTORY_TICKS = 1000
FILE_NAME = "attention.md"
NOTIFY_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class Item:
    """One attention item: a ticket or a repository, why it needs a human, and since when.

    An item about a repository, such as `repo_missing`, has `repo` set and no ticket key.
    """

    ticket_key: str | None
    reason: str
    detail: str
    since: str  # created_at of the first tick in the unbroken run of ticks that recorded this item
    repo: str | None = None

    @property
    def subject(self) -> str:
        """What the item is about, for display: `PROJ-1`, `api`, or `PROJ-1 (api)`."""
        return subject(self.ticket_key, self.repo)


def subject(ticket_key: str | None, repo: str | None) -> str:
    """Name an item's ticket, its repository, or both, for display."""
    if ticket_key is None:
        return repo or "-"
    return f"{ticket_key} ({repo})" if repo else ticket_key


# An item is its ticket, its reason, and its repository if it has one.
_ItemId = tuple[str | None, str, str | None]


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
        return []
    # Only the placeholder count is interpolated; the tick ids are bound parameters.
    rows = conn.execute(
        f"SELECT tick_id, ticket_key, action, rationale, created_at, repo FROM decisions "  # noqa: S608
        f"WHERE action LIKE 'attention:%' AND tick_id IN ({','.join('?' * len(ticks))}) ORDER BY id",
        ticks,
    ).fetchall()
    by_tick: dict[int, dict[_ItemId, tuple[str, str]]] = {t: {} for t in ticks}
    for r in rows:
        key = None if r["ticket_key"] is None else str(r["ticket_key"])
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
    return items


@dataclass(frozen=True)
class RunItem:
    """An attention item the harness raises for a run."""

    ticket_key: str
    reason: str
    detail: str


def from_runs(conn: sqlite3.Connection) -> list[RunItem]:
    """Return an item for each open ticket whose latest run ended in a status listed in RUN_REASONS.

    The cause holds until a newer run starts for the ticket or the ticket is marked done.
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
    text = f"run {run['id']} ({run['kind']}, {run['branch']}) ended {run['status']}"
    if note:
        text += f": {note}"
    return f"{text}; log {run['log_path']}"[:2000]


def age(timestamp: str, now: datetime | None = None) -> str:
    """Return how long ago `timestamp` was, in its largest whole unit: `3d`, `2h`, `5m`, `40s`."""
    seconds = max(0, int(((now or datetime.now(UTC)) - db.parse_time(timestamp)).total_seconds()))
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def _one_line(text: str) -> str:
    return " ".join(text.split())


def render(items: list[Item], now: datetime) -> str:
    """Return `attention.md`: the items grouped by reason, one line each with key, age, and detail."""
    stamp = now.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = ["# canopy attention", ""]
    if not items:
        lines += [f"Nothing needs you. Updated {stamp}.", ""]
        return "\n".join(lines)
    count = f"{len(items)} item{'s' if len(items) != 1 else ''}"
    lines += [f"{count}, updated {stamp}. An item leaves this list when its cause is gone.", ""]
    for reason in sorted({i.reason for i in items}):
        lines += [f"## {reason}", ""]
        lines += [f"- {i.subject}, {age(i.since, now)}: {_one_line(i.detail)}" for i in items if i.reason == reason]
        lines.append("")
    return "\n".join(lines)


def fingerprint(ticket_key: str | None, reason: str, repo: str | None = None) -> str:
    """Identify an item across ticks. The detail is left out: rewording it does not make a new item.

    An item without a repository has the fingerprint it had before items could have one, so none is notified again.
    """
    text = f"{ticket_key or ''}\0{reason}" + (f"\0{repo}" if repo is not None else "")
    return hashlib.sha256(text.encode()).hexdigest()


def _fingerprint(item: Item) -> str:
    return fingerprint(item.ticket_key, item.reason, item.repo)


@dataclass(frozen=True)
class Diff:
    """What changed since the last notification: new items, and notified items whose cause is gone."""

    added: list[Item]
    resolved: list[tuple[str, str]]  # (subject, reason)
    resolved_fingerprints: list[str]

    def __bool__(self) -> bool:
        """Whether anything changed."""
        return bool(self.added or self.resolved)

    def text(self, path: Path) -> str:
        """Return the notification: one line per change, then where the full list is."""
        lines = [f"canopy attention: {len(self.added)} new, {len(self.resolved)} resolved"]
        lines += [f"+ {i.subject} {i.reason}: {_one_line(i.detail)}" for i in self.added]
        lines += [f"- {name} {reason}" for name, reason in self.resolved]
        lines.append(f"Full list: {path}")
        return "\n".join(lines) + "\n"


def diff(conn: sqlite3.Connection, items: list[Item]) -> Diff:
    """Compare `items` with the open items already notified."""
    notified = {
        str(r[0]): (subject(r[1], r[3]), str(r[2]))
        for r in conn.execute("SELECT fingerprint, ticket_key, reason, repo FROM notifications")
    }
    now_open = {_fingerprint(i) for i in items}
    added = [i for i in items if _fingerprint(i) not in notified]
    gone = sorted((item, fp) for fp, item in notified.items() if fp not in now_open)
    return Diff(added, [item for item, _ in gone], [fp for _, fp in gone])


def mark_sent(conn: sqlite3.Connection, change: Diff) -> None:
    """Record a notified diff: its new items become notified, its resolved items are forgotten."""
    ts = db.now()
    with db.transaction(conn):
        conn.executemany(
            "DELETE FROM notifications WHERE fingerprint = ?", [(fp,) for fp in change.resolved_fingerprints]
        )
        conn.executemany(
            "INSERT OR REPLACE INTO notifications (fingerprint, ticket_key, reason, repo, sent_at) "
            "VALUES (?, ?, ?, ?, ?)",
            [(_fingerprint(i), i.ticket_key, i.reason, i.repo, ts) for i in change.added],
        )


def publish(ctx: Context, log: logs.TickAdapter) -> None:
    """Rewrite `attention.md` and, if `notify.cmd` is set and something changed, notify (DESIGN §6 step 7).

    Failures are logged, never raised: the tick is already closed. A notification that fails is sent again next tick,
    since nothing is marked sent until the command succeeds.
    """
    items = current(ctx.conn)
    path = ctx.state_dir / FILE_NAME
    try:
        logs.write_private(path, render(items, datetime.now(UTC)))
    except OSError as e:
        log.error("could not write the attention list", extra={"path": str(path), "error": str(e)})  # noqa: TRY400
    argv = notify_words(ctx.config.notify.cmd)
    if not argv:
        return
    change = diff(ctx.conn, items)
    if not change:
        return
    fields = {"added": len(change.added), "resolved": len(change.resolved), "cmd": argv[0]}
    try:
        result = ctx.runner.run(argv, cwd=ctx.repo_root, stdin=change.text(path), timeout=NOTIFY_TIMEOUT_SECONDS)
    except procs.ProcError as e:
        log.warning("notify command could not start", extra={**fields, "error": str(e)})
        return
    if not result.ok:
        status = "timed out" if result.timed_out else f"exited {result.returncode}"
        log.warning("notify command failed", extra={**fields, "status": status, "stderr": result.stderr[-500:]})
        return
    mark_sent(ctx.conn, change)
    log.info("notified", extra=fields)
