"""Attempt limits and the CI cooldown (DESIGN §8, §18, TRUST_MODEL T3).

Both are derived from `runs` and `run_slots` (D030), per unit: a ticket's work in one repository. Every run dispatched
for a ticket is an attempt of its kind in each repository it leased a slot in, whatever it ended as, and the counts
never reset: a unit at its limit waits for a human, who raises the limit in config or grants that unit more runs of
the kind with `canopy grant` (DESIGN §22). A `fix-ci` run, a kind no longer dispatched, counts as a `resume`, and so do
its grants (M56). The CI cooldown holds a `resume` whose only reason is `ci`, from the end of the latest run that
covered the unit and worked on CI: a `resume` with `ci` among its reasons, or an old `fix-ci`. `dispatch.py` enforces
these; the overseer's state block shows them.

A plan is not a unit's work: it writes down how the ticket will be done across every repository it touches (DESIGN
§25). Nor is an old `split`, a kind follow-up tickets replaced (M46), nor an old `needs-plan`, the triage before a plan
the operator removed (M55). Their runs are counted per ticket, and never in a unit's counts. The operator grants a
ticket more plans (`grant_ticket`).

A feedback plan is a unit's: it reads the PR's head in the unit's slot (DESIGN §32). Its runs count per unit, as the
kinds above do, and are granted per unit, but apart from `KINDS`, so a unit's counts read as they did before feedback
plans (`feedback_plan_attempts`).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, assert_never

from canopy.core import conversation, db, records, sql
from canopy.core.vocab import ResumeReason, RunKind

if TYPE_CHECKING:
    from canopy.core.config import Config

# A unit: a ticket key and a repository name; None for a slot recorded with no repository name.
Unit = tuple[str, str | None]

# The kinds that work in a unit, and every kind `canopy dispatch` takes. Typed as str, since the counts below key on
# `runs.kind` as read; a `click.Choice` takes them as `str(kind)`, since click matches an enum by its name. `fix-ci` is
# none of them: its old runs and grants count as `resume`'s (`counted_as`). Nor are `split` and `needs-plan`, retired
# too: their old runs count per ticket, and nothing dispatches them.
KINDS: tuple[str, ...] = (RunKind.IMPLEMENT, RunKind.RESUME)
RETIRED = RunKind.FIX_CI
SPLIT = RunKind.SPLIT
PLAN = RunKind.PLAN
NEEDS_PLAN = RunKind.NEEDS_PLAN
FEEDBACK_PLAN = RunKind.FEEDBACK_PLAN
# The kinds whose runs are the ticket's, not a unit's: they work on no branch, and their attempts count per ticket.
TICKET_KINDS: tuple[str, ...] = (SPLIT, PLAN, NEEDS_PLAN)
# The kinds counted per ticket that `canopy grant` takes.
TICKET_GRANT_KINDS: tuple[str, ...] = (PLAN,)
#: The kinds counted per unit that `canopy grant` takes: `KINDS`, and feedback plans, counted apart from them.
UNIT_GRANT_KINDS: tuple[str, ...] = (*KINDS, FEEDBACK_PLAN)
# The kinds `attempts` leaves out: the ticket's, and feedback plans, which `feedback_plan_attempts` counts.
_APART: tuple[str, ...] = (*TICKET_KINDS, FEEDBACK_PLAN)
DISPATCH_KINDS: tuple[str, ...] = tuple(k for k in RunKind if k not in (RETIRED, SPLIT, NEEDS_PLAN))


def limits(config: Config) -> dict[str, int]:
    """Return the most runs of each kind one unit may have, and for the kinds counted per ticket, one ticket."""
    return {kind: _limit(config, RunKind(kind)) for kind in DISPATCH_KINDS}


def counted_as(kind: str) -> str:
    """Return the kind a run or grant of `kind` counts toward: an old `fix-ci`'s is `resume` (DESIGN §8)."""
    return str(RunKind.RESUME) if kind == RETIRED else kind


def _limit(config: Config, kind: RunKind) -> int:
    p = config.policy
    match kind:
        case RunKind.IMPLEMENT:
            return p.max_implement_attempts
        case RunKind.FIX_CI | RunKind.RESUME:
            return p.max_resume_attempts
        case RunKind.SPLIT | RunKind.NEEDS_PLAN:
            # Retired (M46, M55): nothing dispatches them.
            return 0
        case RunKind.PLAN:
            return p.max_plan_attempts
        case RunKind.FEEDBACK_PLAN:
            return p.max_feedback_plan_attempts
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
    query = (
        sql.select("r.ticket_key, s.repo, r.kind, count(DISTINCT r.id)")
        .from_("runs r")
        .join("run_slots s ON s.run_id = r.id")
        .where_not_in("r.kind", _APART)
        .group_by("r.ticket_key, s.repo, r.kind")
    )
    if ticket is not None:
        query = query.where("r.ticket_key = ?", ticket)
    for row in sql.execute(conn, query):
        counts_of = counts.setdefault(unit(str(row[0]), row[1]), dict.fromkeys(KINDS, 0))
        counts_of[counted_as(str(row[2]))] += int(row[3])
    return counts


def feedback_plan_attempts(conn: sqlite3.Connection) -> dict[Unit, int]:
    """Return each unit's count of feedback plan runs, whatever they ended as (DESIGN §32). Units with none are missing.

    A feedback plan run leases its unit's slot, so it counts in each repository it read, as a `resume` would.
    """
    rows = sql.execute(
        conn,
        sql.select("r.ticket_key, s.repo, count(DISTINCT r.id)")
        .from_("runs r")
        .join("run_slots s ON s.run_id = r.id")
        .where("r.kind = ?", FEEDBACK_PLAN)
        .group_by("r.ticket_key, s.repo"),
    )
    return {unit(str(row[0]), row[1]): int(row[2]) for row in rows}


def feedback_plan_limit(config: Config, granted: Mapping[str, int]) -> int:
    """Return the most feedback plan runs a unit may have: the policy's, plus the runs the operator granted it."""
    return config.policy.max_feedback_plan_attempts + granted.get(FEEDBACK_PLAN, 0)


def grants(conn: sqlite3.Connection) -> dict[Unit, dict[str, int]]:
    """Return the runs of each kind the operator granted each unit past its policy limit. Units without are missing."""
    granted: dict[Unit, dict[str, int]] = {}
    rows = sql.execute(
        conn,
        sql.select("ticket_key, repo, kind, sum(runs)").from_("attempt_grants").group_by("ticket_key, repo, kind"),
    )
    for row in rows:
        of_unit = granted.setdefault(unit(str(row[0]), str(row[1])), {})
        kind = counted_as(str(row[2]))
        of_unit[kind] = of_unit.get(kind, 0) + int(row[3])
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

    Returns:
        The unit's repository, named or found, and its runs of `kind` and its limit for them with the grant counted.

    Raises:
        Refused: `inside_run` inside one of canopy's own ticks or runs, `bad_kind` for a kind with no unit limit, or
            for `fix-ci`, whose runs count as `resume`'s,
            `unknown` for a ticket canopy has no record of,
            `unknown_repo` for a repository the ticket has had no runs in, or none named when it has had them in
            several.
    """
    conversation.check_operator()
    if kind == RETIRED:
        raise conversation.Refused(
            "bad_kind",
            "a resume now fixes CI, and fix-ci runs count as resume runs: grant resume instead",
        )
    if kind not in UNIT_GRANT_KINDS:
        raise conversation.Refused("bad_kind", f"{kind} is not one of {', '.join(UNIT_GRANT_KINDS)}")
    if db.get_ticket(conn, key) is None:
        raise conversation.Refused("unknown", f"canopy has no record of {key}, so it has no attempts to grant past")
    # Every repository the ticket has had runs in, including those `canopy forget` dropped the units of.
    worked = sorted(str(r) for k, r in attempts(conn, ticket=key) if k == key and r is not None)
    if repo is None:
        if len(worked) != 1:
            where = f"it has had runs in {', '.join(worked)}" if worked else "it has had no runs"
            raise conversation.Refused("unknown_repo", f"name the repository with repo (--repo): {where}")
        repo = worked[0]
    elif repo not in worked:
        raise conversation.Refused("unknown_repo", f"{key} has had no runs in {repo}")
    # The limit is read in the grant's own write transaction, so it counts this grant and none committed after it.
    with db.transaction(conn):
        records.insert(
            records.AttemptGrant,
            ticket_key=key,
            repo=repo,
            kind=kind,
            runs=runs,
            granted_at=db.now(),
        ).run(conn)
        granted = grants(conn).get(unit(key, repo), {})
        if kind == FEEDBACK_PLAN:
            done = feedback_plan_attempts(conn).get(unit(key, repo), 0)
            return Granted(repo=repo, runs=done, limit=feedback_plan_limit(config, granted))
        limit = unit_limits(config, granted)[kind]
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
    # Read in the grant's own transaction, as `grant` reads its limit.
    with db.transaction(conn):
        records.insert(records.TicketGrant, ticket_key=key, kind=kind, runs=runs, granted_at=db.now()).run(conn)
        return TicketGranted(runs=ticket_attempts(conn, kind).get(key, 0), limit=ticket_limit(conn, config, key, kind))


def ticket_limit(conn: sqlite3.Connection, config: Config, key: str, kind: str) -> int:
    """Return the most runs of `kind`, a kind counted per ticket, that `key` may have: the policy's plus its grants."""
    return limits(config)[kind] + ticket_grants(conn, kind).get(key, 0)


def ticket_grants(conn: sqlite3.Connection, kind: str) -> dict[str, int]:
    """Return the runs of `kind` the operator granted each ticket past its policy limit. Tickets without are missing."""
    rows = sql.execute(
        conn,
        sql.select("ticket_key, sum(runs)").from_("ticket_grants").where("kind = ?", kind).group_by("ticket_key"),
    )
    return {str(r[0]): int(r[1]) for r in rows}


def ticket_attempts(conn: sqlite3.Connection, kind: str) -> dict[str, int]:
    """Return each ticket's count of `kind` runs, a kind counted per ticket, whatever they ended as.

    Tickets with no such run are missing.
    """
    rows = sql.execute(
        conn,
        sql.select("ticket_key, count(*)").from_("runs").where("kind = ?", kind).group_by("ticket_key"),
    )
    return {str(r[0]): int(r[1]) for r in rows}


def unit_attempts(conn: sqlite3.Connection, key: str, repo: str | None) -> dict[str, int]:
    """Return one unit's run count per kind."""
    return attempts(conn, ticket=key).get(unit(key, repo), dict.fromkeys(KINDS, 0))


def ci_cooldowns(conn: sqlite3.Connection, config: Config, now: datetime) -> dict[Unit, datetime]:
    """Return, by unit, when a `resume` for CI alone may next run, for units still inside the cooldown.

    A run worked on CI if it was a `resume` with `ci` among its reasons, or an old `fix-ci`.

    Returns:
        Each unit whose last run that worked on CI ended less than the cooldown before `now`, with when it ends.
    """
    window = timedelta(minutes=config.policy.ci_cooldown_minutes)
    until: dict[Unit, datetime] = {}
    for_ci = sql.select("1").from_("run_reasons w").where("w.run_id = r.id AND w.reason = ?", ResumeReason.CI)
    worked_on_ci = (
        sql.select("r.ticket_key, s.repo, max(r.ended_at)")
        .from_("runs r")
        .join("run_slots s ON s.run_id = r.id")
        .where("r.ended_at IS NOT NULL")
        .where("r.kind = ? OR (r.kind = ? AND EXISTS ({}))", RETIRED, RunKind.RESUME, for_ci)
        .group_by("r.ticket_key, s.repo")
    )
    rows = sql.execute(conn, worked_on_ci)
    for row in rows:
        ends = db.parse_time(str(row[2])) + window
        name = unit(str(row[0]), row[1])
        if ends > now and (name not in until or ends > until[name]):
            until[name] = ends
    return until


def blocked(
    name: str,
    kind: str,
    *,
    counts: Mapping[str, int],
    limit: int,
    cooldown_until: datetime | None,
    reasons: AbstractSet[str] = frozenset(),
) -> tuple[str, str] | None:
    """Return the guard and reason that stop a `kind` run for unit `name` now, or None if neither does.

    `name` is how the reason names the unit: the ticket key, followed by its repository. The CI cooldown holds only a
    `resume` whose one reason is `ci`: one sent for anything else would run anyway, and fixes the build on the same
    checkout (DESIGN §8).
    """
    if counts.get(kind, 0) >= limit:
        return "attempt_limit", f"{name} has had {counts.get(kind, 0)} {kind} runs and the limit is {limit}"
    if kind == RunKind.RESUME and set(reasons) == {ResumeReason.CI} and cooldown_until is not None:
        return "cooldown", f"a resume for CI alone in {name} may run again after {db.format_time(cooldown_until)}"
    return None
