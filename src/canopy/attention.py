"""The attention list: what needs a human, derived from the journal (DESIGN §14).

The overseer records attention items as decisions with action `attention:<reason>` every tick the cause holds. The
current list is therefore the items of the latest tick whose overseer finished; an item disappears when a tick no
longer records it. Rendering `attention.md`, diffing, and `notify.cmd` arrive in M3.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

ACTION_PREFIX = "attention:"
# How far back to look when working out how long an item has been open.
_HISTORY_TICKS = 1000


@dataclass(frozen=True)
class Item:
    ticket_key: str
    reason: str
    detail: str
    since: str  # created_at of the first tick in the unbroken run of ticks that recorded this item


def current(conn: sqlite3.Connection) -> list[Item]:
    ticks = [
        int(r[0])
        for r in conn.execute(
            "SELECT id FROM ticks WHERE status = 'ok' ORDER BY id DESC LIMIT ?",
            (_HISTORY_TICKS,),
        )
    ]
    if not ticks:
        return []
    rows = conn.execute(
        f"SELECT tick_id, ticket_key, action, rationale, created_at FROM decisions "
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
