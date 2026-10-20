"""How the loop's agent runs ended, and what its guards refused (DESIGN §11), read by `canopy health`.

Reads only. Over the same window as `canopy spend` (whole local days, today's so far included, by start): how many of
each kind's runs ended each way and what they cost, the newest of those that ended other than as they should, the
overseer's asks a guard refused, by guard, and the plans triage waived (§25), each with what came of its ticket after.
It is what a chore that looks at canopy itself reads, beside `canopy spend`, to say which failures recur and what they
cost, and whether triage judges trivial work well.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, assert_never

from canopy.core import contract, db, plans, records, review_result, spend
from canopy.core.vocab import ChoreRunStatus, PlanSetting, ReviewRunStatus, RunKind, RunStatus, TickStatus

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Sequence
    from datetime import datetime

    from canopy.core.spend import Kind

# The newest failures a report lists, across every kind.
FAILURES = 20
#: The newest waivers a report lists.
WAIVERS = 50
# What a failure's note is cut to: enough to tell one cause from another, which `canopy show` and the web UI give whole.
NOTE_LIMIT = 300
REFUSED = "refused:"

#: Where a waiver stands now: `in_force` still waives the plan; `planned` the operator asked for a plan, undoing it;
#: `skipped` the operator's own skip took its place; `forgotten` a `canopy forget` ended it (DESIGN §25).
type Standing = Literal["in_force", "planned", "skipped", "forgotten"]
#: A review's impact (DESIGN §21), the least first.
IMPACTS = ("low", "normal", "high")

# The statuses each kind of run ends in when it did not do what it was started for. A worker that asked a question
# (`blocked`) or that the operator stopped did, as did a tick that closed `ok`. A triage before a plan and a plan run
# (§25) are runs of the `runs` table, and fail as a worker does.
_WORKER_FAILED = frozenset(
    {RunStatus.FAILED, RunStatus.UNKNOWN, RunStatus.UNPUSHED, RunStatus.CRASHED, RunStatus.TIMEOUT}
)
_FAILED: dict[Kind, frozenset[str]] = {
    "overseer": frozenset(TickStatus) - {TickStatus.RUNNING, TickStatus.OK},
    "workers": _WORKER_FAILED,
    "triage": _WORKER_FAILED,
    "plans": _WORKER_FAILED,
    "chores": frozenset(ChoreRunStatus) - {ChoreRunStatus.RUNNING, ChoreRunStatus.OK},
    "reviews": frozenset(ReviewRunStatus) - {ReviewRunStatus.RUNNING, ReviewRunStatus.DONE},
}
# Each kind's runs as one shape: its id, what it was (a tick's `live` or `dry run`, a run's kind, a chore's name, or
# `review`), its status, when it started, what it was about, its note, and its cost. A triage and a plan run are rows of
# `runs`, each a kind of its own, as `canopy spend` counts them. The tables are fixed, never input.
_RUN_ROWS = (
    "SELECT id, kind AS what, status, started_at, ticket_key AS subject, result_json AS note, cost_usd FROM runs"
)
_ROWS: dict[Kind, str] = {
    "overseer": "SELECT id, CASE WHEN dry_run THEN 'dry run' ELSE 'live' END AS what, status, started_at, "
    "NULL AS subject, summary AS note, cost_usd FROM ticks",
    "workers": f"{_RUN_ROWS} WHERE kind NOT IN ('{RunKind.NEEDS_PLAN.value}', '{RunKind.PLAN.value}')",
    "triage": f"{_RUN_ROWS} WHERE kind = '{RunKind.NEEDS_PLAN.value}'",
    "plans": f"{_RUN_ROWS} WHERE kind = '{RunKind.PLAN.value}'",
    "chores": "SELECT id, chore AS what, status, started_at, NULL AS subject, result_json AS note, cost_usd "
    "FROM chore_runs",
    "reviews": "SELECT id, 'review' AS what, status, started_at, pr_url AS subject, result_json AS note, cost_usd "
    "FROM review_runs",
}


@dataclass(frozen=True)
class Outcome:
    """How many of one kind's runs that started in the window, of one sort, ended in one status, and what they cost.

    `what` is the sort: `live` or `dry run` for the overseer, the run's kind for a worker (`implement`, `plan`), the
    chore's name, or `review`. `failed` says the status is one the run did not end in as it should have.
    """

    kind: Kind
    what: str
    status: str
    failed: bool
    runs: int
    cost_usd: float | None


@dataclass(frozen=True)
class Failure:
    """One run of the window that ended in a failed status (`Outcome.failed`), for `canopy show` to read whole.

    `id` is the tick's for the overseer and the run's otherwise (`canopy decisions ID`, `canopy show run:ID`).
    `subject` is the worker's ticket or the review's PR, None for a tick or a chore. `note` is the tick's summary or
    the result's harness note or summary, on one line and cut to `NOTE_LIMIT`: agents wrote some of it, so it is data.
    """

    kind: Kind
    id: int
    what: str
    status: str
    started_at: str
    subject: str | None
    note: str
    cost_usd: float | None


@dataclass(frozen=True)
class Refusal:
    """How often a guard refused what a tick asked for in the window (DESIGN §4): its decisions and their ticks."""

    guard: str
    decisions: int
    ticks: int
    last_tick: int


@dataclass(frozen=True)
class WaivedRun:
    """One of a waived ticket's runs after its triage, for `canopy show run:ID`."""

    id: int
    #: Its kind: `implement`, `resume`, `fix-ci`, or a `plan` the operator asked for after the waiver.
    kind: str
    status: str
    #: Whether it ended in a status a worker fails in (`Outcome.failed`).
    failed: bool
    cost_usd: float | None


@dataclass(frozen=True)
class Waiver:
    """A plan a triage run that started in the window waived (DESIGN §25), and what came of its ticket after."""

    ticket: str
    #: The triage run, for `canopy show run:ID`.
    run_id: int
    #: When the waiver was written, as its run closed.
    at: str
    #: The triage's reason on one line, cut to `NOTE_LIMIT`: model text written from the ticket, so data.
    reason: str
    standing: Standing
    #: Whether the ticket is marked done now.
    done: bool
    #: The ticket's runs after the triage, oldest first, up to a forget that ended the waiver.
    runs: Sequence[WaivedRun] = ()
    #: The highest impact a `done` review of the ticket's PR judged since the waiver, None before any (DESIGN §21).
    impact: str | None = None
    #: The newest review that judged `impact`.
    review_id: int | None = None


@dataclass(frozen=True)
class Health:
    """The window's runs by how they ended, its newest failures, refusals, and waivers, as `canopy health` reports them.

    The window is `spend.breakdown`'s, `[since, until)`. `outcomes` is in `spend.KINDS` order, then by sort and status;
    `failures` the newest first, at most `FAILURES`; `refusals` the most frequent first; `waivers` the newest first, at
    most `WAIVERS`, each by when its triage started.
    """

    since: str
    until: str
    days: int
    outcomes: Sequence[Outcome] = ()
    failures: Sequence[Failure] = ()
    refusals: Sequence[Refusal] = ()
    waivers: Sequence[Waiver] = ()


def report(conn: sqlite3.Connection, now: datetime, days: int) -> Health:
    """How the runs of the last `days` local days ended, today's so far included, what guards refused, and the waivers.

    Returns:
        The report; a window with nothing in it has empty lists.
    """
    start, end = spend.window(now, days)
    since = db.format_time(start)
    until = db.format_time(end)
    with db.read_snapshot(conn):
        outcomes = [o for kind in spend.KINDS for o in _outcomes(conn, kind, since, until)]
        failures = [f for kind in spend.KINDS for f in _failures(conn, kind, since, until)]
        refusals = _refusals(conn, since, until)
        waivers = _waivers(conn, since, until)
    failures.sort(key=lambda f: (f.started_at, spend.KINDS.index(f.kind), f.id), reverse=True)
    return Health(
        since=since,
        until=until,
        days=days,
        outcomes=outcomes,
        failures=failures[:FAILURES],
        refusals=refusals,
        waivers=waivers,
    )


# One kind's ended runs in the window, by sort and status. A run still running has not ended any way yet.
def _outcomes(conn: sqlite3.Connection, kind: Kind, since: str, until: str) -> list[Outcome]:
    rows = conn.execute(
        f"SELECT what, status, count(*), SUM(cost_usd) FROM ({_ROWS[kind]}) "  # noqa: S608 (a fixed query)
        "WHERE started_at >= ? AND started_at < ? AND status != 'running' GROUP BY what, status ORDER BY what, status",
        (since, until),
    )
    return [
        Outcome(
            kind=kind,
            what=str(what),
            status=str(status),
            failed=str(status) in _FAILED[kind],
            runs=int(runs),
            cost_usd=cost,
        )
        for what, status, runs, cost in rows
    ]


def _failures(conn: sqlite3.Connection, kind: Kind, since: str, until: str) -> Iterable[Failure]:
    statuses = sorted(_FAILED[kind])
    marks = ", ".join("?" * len(statuses))
    rows = conn.execute(
        f"SELECT * FROM ({_ROWS[kind]}) "  # noqa: S608 (a fixed query, and a mark per status)
        f"WHERE started_at >= ? AND started_at < ? AND status IN ({marks}) ORDER BY started_at DESC, id DESC LIMIT ?",
        (since, until, *statuses, FAILURES),
    )
    for run_id, what, status, started, subject, note, cost in rows:
        yield Failure(
            kind=kind,
            id=int(run_id),
            what=str(what),
            status=str(status),
            started_at=str(started),
            subject=None if subject is None else str(subject),
            note=_note(kind, note),
            cost_usd=cost,
        )


# A tick's note is its summary, canopy's, which quotes the overseer's reason for a skip; a run's is in its stored
# result, the harness's note or else the agent's summary.
def _note(kind: Kind, stored: object) -> str:
    text = str(stored or "") if kind == "overseer" else contract.stored_note(contract.stored_object(_text(stored)))
    return _one_line(text)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _refusals(conn: sqlite3.Connection, since: str, until: str) -> list[Refusal]:
    rows = conn.execute(
        "SELECT substr(action, ?), count(*), count(DISTINCT tick_id), max(tick_id) FROM decisions "
        "WHERE action LIKE ? AND created_at >= ? AND created_at < ? GROUP BY action ORDER BY count(*) DESC, action",
        (len(REFUSED) + 1, f"{REFUSED}%", since, until),
    )
    return [
        Refusal(guard=str(guard), decisions=int(n), ticks=int(ticks), last_tick=int(last))
        for guard, n, ticks, last in rows
    ]


def _waivers(conn: sqlite3.Connection, since: str, until: str) -> list[Waiver]:
    waived = records.fetch_all(
        conn,
        records.PlanWaiver,
        "SELECT w.* FROM plan_waivers w JOIN runs r ON r.id = w.run_id "
        "WHERE r.started_at >= ? AND r.started_at < ? ORDER BY w.run_id DESC LIMIT ?",
        (since, until, WAIVERS),
    )
    found: list[Waiver] = []
    for w in waived:
        # Always there: a waiver's ticket is a foreign key.
        ticket = db.get_ticket(conn, w.ticket_key)
        if ticket is not None:
            found.append(_waiver(conn, w, ticket))
    return found


# What came of one waiver's ticket: where the waiver stands, the ticket's runs after the triage, and the highest impact
# a review judged its PR. A forget after the triage starts the ticket over, so what follows it is not the waiver's.
def _waiver(conn: sqlite3.Connection, waived: records.PlanWaiver, ticket: records.Ticket) -> Waiver:
    forgotten = ticket.forgotten_run_id is not None and ticket.forgotten_run_id >= waived.run_id
    last_run = ticket.forgotten_run_id if forgotten else None
    runs = conn.execute(
        "SELECT id, kind, status, cost_usd FROM runs WHERE ticket_key = ? AND id > ? AND id <= coalesce(?, id) "
        "ORDER BY id",
        (waived.ticket_key, waived.run_id, last_run),
    ).fetchall()
    impact, review_id = _impact(conn, waived, ticket.forgotten_at if forgotten else None)
    return Waiver(
        ticket=waived.ticket_key,
        run_id=waived.run_id,
        at=waived.at,
        reason=_one_line(waived.reason),
        standing=_standing(conn, waived, ticket, forgotten=forgotten),
        done=ticket.done,
        runs=[
            WaivedRun(
                id=int(run_id),
                kind=str(kind),
                status=str(status),
                failed=str(status) in _WORKER_FAILED,
                cost_usd=cost,
            )
            for run_id, kind, status, cost in runs
        ],
        impact=impact,
        review_id=review_id,
    )


def _standing(
    conn: sqlite3.Connection, waived: records.PlanWaiver, ticket: records.Ticket, *, forgotten: bool
) -> Standing:
    if forgotten:
        return "forgotten"
    match ticket.plan_setting:
        case PlanSetting.PLAN:
            return "planned"
        case PlanSetting.SKIP:
            return "skipped"
        case None:
            in_force = plans.waiver(conn, ticket)
            return "in_force" if in_force is not None and in_force.id == waived.id else "forgotten"
        case _:
            assert_never(ticket.plan_setting)


# The highest impact a `done` review of the ticket's PR judged after the waiver and before a forget that ended it, and
# the newest review that judged it. A review names its ticket, or its PR is one of the ticket's units' (§21).
def _impact(conn: sqlite3.Connection, waived: records.PlanWaiver, until: str | None) -> tuple[str | None, int | None]:
    rows = conn.execute(
        "SELECT id, result_json FROM review_runs WHERE status = ? AND started_at >= ? "
        "AND started_at <= coalesce(?, started_at) AND (ticket_key = ? OR pr_url IN "
        "(SELECT pr_url FROM ticket_units WHERE ticket_key = ? AND pr_url IS NOT NULL)) ORDER BY id",
        (ReviewRunStatus.DONE, waived.at, until, waived.ticket_key, waived.ticket_key),
    )
    best: tuple[str | None, int | None] = (None, None)
    for review_id, stored in rows:
        result = review_result.stored(stored)
        if result is None or result.impact is None:
            continue
        if best[0] is None or IMPACTS.index(result.impact) >= IMPACTS.index(best[0]):
            best = (result.impact, int(review_id))
    return best


def _one_line(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= NOTE_LIMIT else text[: NOTE_LIMIT - 3] + "..."
