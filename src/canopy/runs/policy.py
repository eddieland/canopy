"""Attempt limits and the fix-ci cooldown (DESIGN §8, §18, TRUST_MODEL T3).

Both are derived from `runs` and `run_slots` (D030), per unit: a ticket's work in one repository. Every run dispatched
for a ticket is an attempt of its kind in each repository it leased a slot in, whatever it ended as, and the counts
never reset: a unit at its limit waits for a human. The fix-ci cooldown runs from the end of the latest fix-ci run that
covered the unit. `dispatch.py` enforces these; the overseer's state block shows them.

In a workspace of one, a ticket has one unit whatever its repository was called when each run was made, so counts are
per ticket there, under the unit `None`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from canopy.core import db

if TYPE_CHECKING:
    from canopy.core.config import Config

# A unit: a ticket key and a repository name, or None for a workspace of one's only repository.
Unit = tuple[str, str | None]

KINDS = ("implement", "fix-ci", "resume")


def limits(config: Config) -> dict[str, int]:
    """Return the most runs of each kind one ticket may have."""
    p = config.policy
    return {"implement": p.max_implement_attempts, "fix-ci": p.max_fix_ci_attempts, "resume": p.max_resume_attempts}


def unit(key: str, repo: str | None, *, single: bool) -> Unit:
    """Return how the counts below name `key`'s unit in `repo`."""
    return (key, None if single else repo)


def attempts(conn: sqlite3.Connection, *, single: bool) -> dict[Unit, dict[str, int]]:
    """Return every unit's run count per kind. Kinds with no runs are 0; units with no runs are missing."""
    counts: dict[Unit, dict[str, int]] = {}
    rows = conn.execute(
        "SELECT r.ticket_key, s.repo, r.kind, count(DISTINCT r.id) FROM runs r JOIN run_slots s ON s.run_id = r.id "
        "GROUP BY r.ticket_key, s.repo, r.kind"
    )
    for row in rows:
        counts_of = counts.setdefault(unit(str(row[0]), row[1], single=single), dict.fromkeys(KINDS, 0))
        counts_of[str(row[2])] += int(row[3])
    return counts


def unit_attempts(conn: sqlite3.Connection, key: str, repo: str | None, *, single: bool) -> dict[str, int]:
    """Return one unit's run count per kind."""
    return attempts(conn, single=single).get(unit(key, repo, single=single), dict.fromkeys(KINDS, 0))


def fix_ci_cooldowns(conn: sqlite3.Connection, config: Config, now: datetime, *, single: bool) -> dict[Unit, datetime]:
    """Return, by unit, when fix-ci may next run, for units still inside the cooldown."""
    window = timedelta(minutes=config.policy.fix_ci_cooldown_minutes)
    until: dict[Unit, datetime] = {}
    rows = conn.execute(
        "SELECT r.ticket_key, s.repo, max(r.ended_at) FROM runs r JOIN run_slots s ON s.run_id = r.id "
        "WHERE r.kind = 'fix-ci' AND r.ended_at IS NOT NULL GROUP BY r.ticket_key, s.repo"
    )
    for row in rows:
        ends = db.parse_time(str(row[2])) + window
        name = unit(str(row[0]), row[1], single=single)
        if ends > now and (name not in until or ends > until[name]):
            until[name] = ends
    return until


def blocked(
    name: str, kind: str, *, counts: Mapping[str, int], limit: int, cooldown_until: datetime | None
) -> tuple[str, str] | None:
    """Return the guard and reason that stop a `kind` run for unit `name` now, or None if neither does.

    `name` is how the reason names the unit: the ticket key, followed by the repository in a workspace of several.
    """
    if counts.get(kind, 0) >= limit:
        return "attempt_limit", f"{name} has had {counts.get(kind, 0)} {kind} runs and the limit is {limit}"
    if kind == "fix-ci" and cooldown_until is not None:
        return "cooldown", f"fix-ci for {name} may run again after {db.format_time(cooldown_until)}"
    return None
