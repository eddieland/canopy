"""Attempt limits and the fix-ci cooldown (DESIGN §8, TRUST_MODEL T3).

Both are derived from `runs` (D030). Every run dispatched for a ticket is an attempt of its kind, whatever it ended as,
and the counts never reset: a ticket at its limit waits for a human. The fix-ci cooldown runs from the end of the
ticket's latest fix-ci run. `dispatch.py` enforces these; the overseer's state block shows them.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from canopy.core import db

if TYPE_CHECKING:
    from canopy.core.config import Config

KINDS = ("implement", "fix-ci", "resume")


def limits(config: Config) -> dict[str, int]:
    """Return the most runs of each kind one ticket may have."""
    p = config.policy
    return {"implement": p.max_implement_attempts, "fix-ci": p.max_fix_ci_attempts, "resume": p.max_resume_attempts}


def attempts(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
    """Return every ticket's run count per kind, by ticket key. Kinds with no runs are 0."""
    counts: dict[str, dict[str, int]] = {}
    for row in conn.execute("SELECT ticket_key, kind, count(*) FROM runs GROUP BY ticket_key, kind"):
        counts.setdefault(str(row[0]), dict.fromkeys(KINDS, 0))[str(row[1])] = int(row[2])
    return counts


def ticket_attempts(conn: sqlite3.Connection, key: str) -> dict[str, int]:
    """Return one ticket's run count per kind."""
    return attempts(conn).get(key, dict.fromkeys(KINDS, 0))


def fix_ci_cooldowns(conn: sqlite3.Connection, config: Config, now: datetime) -> dict[str, datetime]:
    """Return, by ticket key, when fix-ci may next run, for tickets still inside the cooldown."""
    window = timedelta(minutes=config.policy.fix_ci_cooldown_minutes)
    until: dict[str, datetime] = {}
    rows = conn.execute(
        "SELECT ticket_key, max(ended_at) FROM runs WHERE kind = 'fix-ci' AND ended_at IS NOT NULL GROUP BY ticket_key"
    )
    for row in rows:
        ends = db.parse_time(str(row[1])) + window
        if ends > now:
            until[str(row[0])] = ends
    return until


def blocked(
    key: str, kind: str, *, counts: Mapping[str, int], limit: int, cooldown_until: datetime | None
) -> tuple[str, str] | None:
    """Return the guard and reason that stop a `kind` run for `key` now, or None if neither does."""
    if counts.get(kind, 0) >= limit:
        return "attempt_limit", f"{key} has had {counts.get(kind, 0)} {kind} runs and the limit is {limit}"
    if kind == "fix-ci" and cooldown_until is not None:
        return "cooldown", f"fix-ci for {key} may run again after {db.format_time(cooldown_until)}"
    return None
