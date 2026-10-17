"""Attempt limits and the fix-ci cooldown (DESIGN §8, §18, TRUST_MODEL T3).

Both are derived from `runs` and `run_slots` (D030), per unit: a ticket's work in one repository. Every run dispatched
for a ticket is an attempt of its kind in each repository it leased a slot in, whatever it ended as, and the counts
never reset: a unit at its limit waits for a human, who raises the limit in config or grants that unit more runs of
the kind with `canopy grant` (DESIGN §22). The fix-ci cooldown runs from the end of the latest fix-ci run that
covered the unit. `dispatch.py` enforces these; the overseer's state block shows them.

A split is not a unit's work: it creates tickets and changes no repository (DESIGN §18). Nor is a plan, which writes
down how the ticket will be done across every repository it touches (DESIGN §25). Their runs are counted per ticket,
and never in a unit's counts. The operator grants a ticket more plans (`grant_ticket`); a split's limit only config
raises.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, assert_never

from canopy.core import conversation, db
from canopy.core.vocab import RunKind

if TYPE_CHECKING:
    from canopy.core.config import Config

# A unit: a ticket key and a repository name; None for a slot recorded with no repository name.
Unit = tuple[str, str | None]

# The kinds that work in a unit, and every kind `canopy dispatch` takes. Typed as str, since the counts below key on
# `runs.kind` as read; a `click.Choice` takes them as `str(kind)`, since click matches an enum by its name.
KINDS: tuple[str, ...] = (RunKind.IMPLEMENT, RunKind.FIX_CI, RunKind.RESUME)
SPLIT = RunKind.SPLIT
PLAN = RunKind.PLAN
# The kinds whose runs are the ticket's, not a unit's: they work on no branch, and their attempts count per ticket.
TICKET_KINDS: tuple[str, ...] = (SPLIT, PLAN)
# The kinds counted per ticket that `canopy grant` takes: a split creates tickets in the tracker, so only config raises
# its limit.
TICKET_GRANT_KINDS: tuple[str, ...] = (PLAN,)
DISPATCH_KINDS: tuple[str, ...] = tuple(RunKind)


def limits(config: Config) -> dict[str, int]:
    """Return the most runs of each kind one unit may have, and for `split` and `plan`, one ticket."""
    return {kind: _limit(config, kind) for kind in RunKind}


def _limit(config: Config, kind: RunKind) -> int:
    p = config.policy
    match kind:
        case RunKind.IMPLEMENT:
            return p.max_implement_attempts
        case RunKind.FIX_CI:
            return p.max_fix_ci_attempts
        case RunKind.RESUME:
            return p.max_resume_attempts
        case RunKind.SPLIT:
            return p.max_split_attempts
        case RunKind.PLAN:
            return p.max_plan_attempts
        case _:
            assert_never(kind)


def unit_limits(config: Config, granted: Mapping[str, int]) -> dict[str, int]:
    """Return the most runs of each kind one unit may have: the policy's limit plus the runs granted it of that kind."""
    base = limits(config)
    return {kind: base[kind] + granted.get(kind, 0) for kind in KINDS}


def unit(key: str, repo: str | None) -> Unit:
    """Return how the counts below name `key`'s unit in `repo`."""
    return (key, repo)


def attempts(conn: sqlite3.Connection, *, ticket: str | None = None) -> dict[Unit, dict[str, int]]:
    """Return every unit's run count per kind, or only `ticket`'s units'.

    Kinds with no runs are 0; units with no runs are missing. One ticket's are counted from its own runs, so a page
    about it reads what it has run, not the journal's history.
    """
    counts: dict[Unit, dict[str, int]] = {}
    query = "SELECT r.ticket_key, s.repo, r.kind, count(DISTINCT r.id) FROM runs r JOIN run_slots s ON s.run_id = r.id "
    if ticket is None:
        rows = conn.execute(f"{query}WHERE r.kind NOT IN (?, ?) GROUP BY r.ticket_key, s.repo, r.kind", TICKET_KINDS)
    else:
        rows = conn.execute(
            f"{query}WHERE r.ticket_key = ? AND r.kind NOT IN (?, ?) GROUP BY r.ticket_key, s.repo, r.kind",
            (ticket, *TICKET_KINDS),
        )
    for row in rows:
        counts_of = counts.setdefault(unit(str(row[0]), row[1]), dict.fromkeys(KINDS, 0))
        counts_of[str(row[2])] += int(row[3])
    return counts


def grants(conn: sqlite3.Connection) -> dict[Unit, dict[str, int]]:
    """Return the runs of each kind the operator granted each unit past its policy limit. Units without are missing."""
    granted: dict[Unit, dict[str, int]] = {}
    rows = conn.execute("SELECT ticket_key, repo, kind, sum(runs) FROM attempt_grants GROUP BY ticket_key, repo, kind")
    for row in rows:
        granted.setdefault(unit(str(row[0]), str(row[1])), {})[str(row[2])] = int(row[3])
    return granted


@dataclass(frozen=True)
class Granted:
    """What `grant` recorded: the unit's repository, and its runs and limit of the kind now."""

    repo: str
    runs: int
    limit: int


def grant(conn: sqlite3.Connection, config: Config, key: str, kind: str, *, repo: str | None, runs: int) -> Granted:
    """Grant `key`'s unit in `repo` `runs` more runs of `kind` than the policy allows (DESIGN §22). Operator only.

    `repo` may be omitted when the ticket has had runs in one repository only. Every run still counts (D030): a grant
    raises the unit's limit, and the next dispatch of that kind sees it.

    Raises:
        Refused: `inside_run` inside one of canopy's own ticks or runs, `bad_kind` for a kind with no unit limit (a
            split's is the ticket's, and only config raises it), `unknown` for a ticket canopy has no record of,
            `unknown_repo` for a repository the ticket has had no runs in, or none named when it has had them in
            several.

    Returns:
        The unit's repository, named or found, and its runs of `kind` and its limit for them with the grant counted.
    """
    conversation.check_operator()
    if kind not in KINDS:
        raise conversation.Refused("bad_kind", f"{kind} is not one of {', '.join(KINDS)}")
    if db.get_ticket(conn, key) is None:
        raise conversation.Refused("unknown", f"canopy has no record of {key}, so it has no attempts to grant past")
    # Every repository the ticket has had runs in, including those `canopy forget` dropped the units of.
    worked = sorted(str(r) for k, r in attempts(conn, ticket=key) if k == key and r is not None)
    if repo is None:
        if len(worked) != 1:
            where = f"it has had runs in {', '.join(worked)}" if worked else "it has had no runs"
            raise conversation.Refused("unknown_repo", f"name the repository with --repo: {where}")
        repo = worked[0]
    elif repo not in worked:
        raise conversation.Refused("unknown_repo", f"{key} has had no runs in {repo}")
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO attempt_grants (ticket_key, repo, kind, runs, granted_at) VALUES (?, ?, ?, ?, ?)",
            (key, repo, kind, runs, db.now()),
        )
    name = unit(key, repo)
    limit = unit_limits(config, grants(conn).get(name, {}))[kind]
    return Granted(repo=repo, runs=unit_attempts(conn, key, repo)[kind], limit=limit)


@dataclass(frozen=True)
class TicketGranted:
    """What `grant_ticket` recorded: the ticket's runs and limit of the kind now."""

    runs: int
    limit: int


def grant_ticket(conn: sqlite3.Connection, config: Config, key: str, kind: str, *, runs: int) -> TicketGranted:
    """Grant `key` `runs` more runs of `kind`, a kind counted per ticket, than the policy allows (DESIGN §25).

    Operator only, as `grant` is. Every run still counts (D030): a grant raises the ticket's limit.

    Returns:
        The ticket's runs of `kind`, and its limit for them with the grant counted.

    Raises:
        Refused: `inside_run` inside one of canopy's own ticks or runs, `bad_kind` for a kind the operator cannot
            grant per ticket, `unknown` for a ticket canopy has no record of.
    """
    conversation.check_operator()
    if kind not in TICKET_GRANT_KINDS:
        raise conversation.Refused("bad_kind", f"{kind} is not one of {', '.join(TICKET_GRANT_KINDS)}")
    if db.get_ticket(conn, key) is None:
        raise conversation.Refused("unknown", f"canopy has no record of {key}, so it has no attempts to grant past")
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO ticket_grants (ticket_key, kind, runs, granted_at) VALUES (?, ?, ?, ?)",
            (key, kind, runs, db.now()),
        )
    return TicketGranted(runs=ticket_attempts(conn, kind).get(key, 0), limit=ticket_limit(conn, config, key, kind))


def ticket_limit(conn: sqlite3.Connection, config: Config, key: str, kind: str) -> int:
    """Return the most runs of `kind`, a kind counted per ticket, that `key` may have: the policy's plus its grants."""
    return limits(config)[kind] + ticket_grants(conn, kind).get(key, 0)


def ticket_grants(conn: sqlite3.Connection, kind: str) -> dict[str, int]:
    """Return the runs of `kind` the operator granted each ticket past its policy limit. Tickets without are missing."""
    rows = conn.execute("SELECT ticket_key, sum(runs) FROM ticket_grants WHERE kind = ? GROUP BY ticket_key", (kind,))
    return {str(r[0]): int(r[1]) for r in rows}


def ticket_attempts(conn: sqlite3.Connection, kind: str) -> dict[str, int]:
    """Return each ticket's count of `kind` runs, a kind counted per ticket, whatever they ended as.

    Tickets with no such run are missing.
    """
    rows = conn.execute("SELECT ticket_key, count(*) FROM runs WHERE kind = ? GROUP BY ticket_key", (kind,))
    return {str(r[0]): int(r[1]) for r in rows}


def unit_attempts(conn: sqlite3.Connection, key: str, repo: str | None) -> dict[str, int]:
    """Return one unit's run count per kind."""
    return attempts(conn, ticket=key).get(unit(key, repo), dict.fromkeys(KINDS, 0))


def fix_ci_cooldowns(conn: sqlite3.Connection, config: Config, now: datetime) -> dict[Unit, datetime]:
    """Return, by unit, when fix-ci may next run, for units still inside the cooldown.

    Returns:
        Each unit whose last fix-ci run ended less than the cooldown before `now`, with when the cooldown ends.
    """
    window = timedelta(minutes=config.policy.fix_ci_cooldown_minutes)
    until: dict[Unit, datetime] = {}
    rows = conn.execute(
        "SELECT r.ticket_key, s.repo, max(r.ended_at) FROM runs r JOIN run_slots s ON s.run_id = r.id "
        "WHERE r.kind = 'fix-ci' AND r.ended_at IS NOT NULL GROUP BY r.ticket_key, s.repo"
    )
    for row in rows:
        ends = db.parse_time(str(row[2])) + window
        name = unit(str(row[0]), row[1])
        if ends > now and (name not in until or ends > until[name]):
            until[name] = ends
    return until


def blocked(
    name: str, kind: str, *, counts: Mapping[str, int], limit: int, cooldown_until: datetime | None
) -> tuple[str, str] | None:
    """Return the guard and reason that stop a `kind` run for unit `name` now, or None if neither does.

    `name` is how the reason names the unit: the ticket key, followed by its repository.
    """
    if counts.get(kind, 0) >= limit:
        return "attempt_limit", f"{name} has had {counts.get(kind, 0)} {kind} runs and the limit is {limit}"
    if kind == RunKind.FIX_CI and cooldown_until is not None:
        return "cooldown", f"fix-ci for {name} may run again after {db.format_time(cooldown_until)}"
    return None
