"""How the loop's agent runs ended, and what its guards refused (DESIGN §11), read by `canopy health`.

Reads only. Over the same window as `canopy spend` (whole local days, today's so far included, by start): how many of
each kind's runs ended each way and what they cost, the newest of those that ended other than as they should, the
overseer's asks a guard refused, by guard. It is what a chore that looks at canopy itself reads, beside `canopy
spend`, to say which failures recur and what they cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import contract, db, spend, sql
from canopy.core.vocab import ChoreRunStatus, ReviewRunStatus, RunKind, RunStatus, TickStatus

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import datetime

    from canopy.core.spend import Kind

# The newest failures a report lists, across every kind.
FAILURES = 20
# What a failure's note is cut to: enough to tell one cause from another, which `canopy show` and the web UI give whole.
NOTE_LIMIT = 300
REFUSED = "refused:"


# The statuses each kind of run ends in when it did not do what it was started for. A worker that asked a question
# (`blocked`) or that the operator stopped did, as did a tick that closed `ok`. A plan run (§25), an old triage before
# a plan among them, is a run of the `runs` table, and fails as a worker does.
_WORKER_FAILED = frozenset(
    {RunStatus.FAILED, RunStatus.UNKNOWN, RunStatus.UNPUSHED, RunStatus.CRASHED, RunStatus.TIMEOUT}
)
_FAILED: dict[Kind, frozenset[str]] = {
    "overseer": frozenset(TickStatus) - {TickStatus.RUNNING, TickStatus.OK},
    "workers": _WORKER_FAILED,
    "plans": _WORKER_FAILED,
    "chores": frozenset(ChoreRunStatus) - {ChoreRunStatus.RUNNING, ChoreRunStatus.OK},
    "reviews": frozenset(ReviewRunStatus) - {ReviewRunStatus.RUNNING, ReviewRunStatus.DONE},
}
# Each kind's runs as one shape: its id, what it was (a tick's `live` or `dry run`, a run's kind, a chore's name, or
# `review`), its status, when it started, what it was about, its note, and its cost. A plan run is a row of `runs`, a
# kind of its own, an old triage among them, as `canopy spend` counts them. The tables are fixed, never input, and
# each is built from literal SQL (D125).
_RUN_ROWS = sql.select(
    "id, kind AS what, status, started_at, ticket_key AS subject, result_json AS note, cost_usd"
).from_("runs")
_PLAN_KINDS = sql.in_("kind", (RunKind.PLAN, RunKind.NEEDS_PLAN))
_ROWS: Mapping[Kind, sql.Select] = {
    "overseer": sql.select(
        "id, CASE WHEN dry_run THEN 'dry run' ELSE 'live' END AS what, status, started_at, "
        "NULL AS subject, summary AS note, cost_usd"
    ).from_("ticks"),
    "workers": _RUN_ROWS.where("NOT ({})", _PLAN_KINDS),
    "plans": _RUN_ROWS.where("{}", _PLAN_KINDS),
    "chores": sql.select("id, chore AS what, status, started_at, NULL AS subject, result_json AS note, cost_usd").from_(
        "chore_runs"
    ),
    "reviews": sql.select(
        "id, 'review' AS what, status, started_at, pr_url AS subject, result_json AS note, cost_usd"
    ).from_("review_runs"),
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
class Health:
    """The window's runs by how they ended, its newest failures, and its refusals, as `canopy health` reports them.

    The window is `spend.breakdown`'s, `[since, until)`. `outcomes` is in `spend.KINDS` order, then by sort and status;
    `failures` the newest first, at most `FAILURES`; `refusals` the most frequent first.
    """

    since: str
    until: str
    days: int
    outcomes: Sequence[Outcome] = ()
    failures: Sequence[Failure] = ()
    refusals: Sequence[Refusal] = ()


def report(conn: sqlite3.Connection, now: datetime, days: int) -> Health:
    """How the runs of the last `days` local days ended, today's so far included, and what guards refused.

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
    failures.sort(key=lambda f: (f.started_at, spend.KINDS.index(f.kind), f.id), reverse=True)
    return Health(
        since=since,
        until=until,
        days=days,
        outcomes=outcomes,
        failures=failures[:FAILURES],
        refusals=refusals,
    )


# One kind's ended runs in the window, by sort and status. A run still running has not ended any way yet.
def _outcomes(conn: sqlite3.Connection, kind: Kind, since: str, until: str) -> list[Outcome]:
    ended = (
        sql.select("what, status, count(*), SUM(cost_usd)")
        .from_("({})", _ROWS[kind])
        .where("started_at >= ? AND started_at < ? AND status != 'running'", since, until)
        .group_by("what, status")
        .order_by("what, status")
    )
    rows = sql.execute(conn, ended)
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
    failed = (
        sql.select("*")
        .from_("({})", _ROWS[kind])
        .where("started_at >= ? AND started_at < ?", since, until)
        .where_in("status", sorted(_FAILED[kind]))
        .order_by("started_at DESC, id DESC")
        .limit(FAILURES)
    )
    rows = sql.execute(conn, failed)
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
    refused = (
        sql.select("substr(action, ?), count(*), count(DISTINCT tick_id), max(tick_id)", len(REFUSED) + 1)
        .from_("decisions")
        .where("action LIKE ? AND created_at >= ? AND created_at < ?", f"{REFUSED}%", since, until)
        .group_by("action")
        .order_by("count(*) DESC, action")
    )
    rows = sql.execute(conn, refused)
    return [
        Refusal(guard=str(guard), decisions=int(n), ticks=int(ticks), last_tick=int(last))
        for guard, n, ticks, last in rows
    ]


def _one_line(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= NOTE_LIMIT else text[: NOTE_LIMIT - 3] + "..."
