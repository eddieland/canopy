"""The attention list: what needs a human, derived from the journal (DESIGN §14).

Attention items are decisions with action `attention:<reason>`, recorded every tick the cause holds: by the overseer
for what it reads in the world, and by the harness for runs that ended in a way a human must look at (`from_runs`). The
current list is therefore the items of the latest tick whose overseer finished; an item disappears when a tick no
longer records it. Rendering `attention.md`, diffing, and `notify.cmd` arrive in M3.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from canopy import db

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


@dataclass(frozen=True)
class Item:
    """One attention item: a ticket, why it needs a human, and since when."""

    ticket_key: str
    reason: str
    detail: str
    since: str  # created_at of the first tick in the unbroken run of ticks that recorded this item


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
        f"SELECT tick_id, ticket_key, action, rationale, created_at FROM decisions "  # noqa: S608
        f"WHERE action LIKE 'attention:%' AND tick_id IN ({','.join('?' * len(ticks))}) ORDER BY id",
        ticks,
    ).fetchall()
    by_tick: dict[int, dict[tuple[str, str], tuple[str, str]]] = {t: {} for t in ticks}
    for r in rows:
        item_id = (str(r["ticket_key"]), str(r["action"]).removeprefix(ACTION_PREFIX))
        by_tick[int(r["tick_id"])].setdefault(item_id, (str(r["rationale"]), str(r["created_at"])))

    latest = by_tick[ticks[0]]
    items: list[Item] = []
    for item_id, (detail, created_at) in sorted(latest.items()):
        since = created_at
        for tick_id in ticks[1:]:
            earlier = by_tick[tick_id].get(item_id)
            if earlier is None:
                break
            since = earlier[1]
        items.append(Item(item_id[0], item_id[1], detail, since))
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
