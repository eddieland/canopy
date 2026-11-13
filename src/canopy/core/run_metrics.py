"""Metrics of canopy's agent runs, read from their journal rows: how many ended, how long, what they cost (D132).

A run's metrics are recorded once, where its row is closed and after the transaction that closes it commits, in
whatever process closes it: the run's own, or a tick's reconcile for a run whose process died. So a run that crashed
is counted as one that ended well is, and what is counted is what the journal holds. A tick's overseer runs are
recorded as the tick closes, or, for a tick whose process died, as the next tick closes it `abandoned`, counting the
tick too, and so are its decisions. What the loop holds now is a set of gauges the tick sets as it closes, so a
collector can tell whether the loop still ticks and whether work piles up. Recording a metric never fails what closed
the row: what goes wrong is logged, and the metric is lost.

    canopy.runs              count     role, status, kind (a worker's)    each run that ended
    canopy.run.duration      seconds   role, status                       how long it ran
    canopy.cost              USD       role, model                        what it cost, as the runtime reported
    canopy.tokens            tokens    role, model, type                  its tokens, by type
    canopy.runs.active       gauge     role                               the runs at work as a tick closes
    canopy.ticks             count     status, dry_run                    a tick a dead process left (`tick` the rest)
    canopy.tick.last         seconds   status                             when the last tick of a status closed
    canopy.tickets           gauge     phase                              the open tickets the loop works, by phase
    canopy.capacity.used     gauge     role                               the runs that fill a role's capacity
    canopy.capacity.limit    gauge     role                               that capacity, as config sets it
    canopy.attention.open    gauge                                        the items waiting on the operator
    canopy.disk.free         bytes                                        free space where the state directory is
    canopy.decisions         count     kind, outcome, decider, dry_run    each decision a tick recorded, or refused

The rest are recorded where what they count happens: each step of a tick's time (`canopy.tick.step.duration`, by
step) in `loop.tick`, each delivery to a notification sink (`canopy.notifications`, by status) in `notify.deliver`,
and each run of a connector (`canopy.connector.runs`, by its source's kind and status) in `core.connector_runs`.
"""

from __future__ import annotations

import functools
import logging
import shutil
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from canopy.core import records, sql
from canopy.core.vocab import Decider, OverseerRunStatus, Phase, StartStatus, TickStatus
from canopy.infra import metrics

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from canopy.core.config import Capacity
    from canopy.core.db import RunTable


class Role(StrEnum):
    """Which of canopy's agents a run is, as a metric's `role` label names it."""

    WORKER = "worker"
    TASK = "task"
    REVIEW = "review"
    CHORE = "chore"
    OVERSEER = "overseer"


class DecisionKind(StrEnum):
    """What a decision was, as `canopy.decisions`' `kind` label names it: the word its action starts with.

    A refusal's action names the guard that refused it, not what was asked: it is a `dispatch` when its row names the
    kind of run it asked for, as a refused dispatch's does, and `other` otherwise.
    """

    DISPATCH = "dispatch"
    WAIT = "wait"
    SKIP = "skip"
    DONE = "done"
    ATTENTION = "attention"
    #: A review request's end, `review:end`.
    REVIEW = "review"
    CURSOR = "cursor"
    QUERIED = "queried"
    MIRROR = "mirror"
    #: Any action whose word is none of these.
    OTHER = "other"


class DecisionOutcome(StrEnum):
    """Whether a decision was made or a guard refused it, as `canopy.decisions`' `outcome` label names it."""

    MADE = "made"
    REFUSED = "refused"


class TokenType(StrEnum):
    """A kind of token a run spent, as `canopy.tokens`' `type` label names it, each a column of its row."""

    INPUT = "input"
    OUTPUT = "output"
    REASONING = "reasoning"
    CACHE_READ = "cache_read"
    CACHE_WRITE = "cache_write"


def _never_raises[**P](record: Callable[P, None]) -> Callable[P, None]:
    """Make `record` log what it raises rather than raise it: a metric lost never fails the close that recorded it.

    Returns:
        `record`, guarded.
    """

    @functools.wraps(record)
    def guarded(*args: P.args, **kwargs: P.kwargs) -> None:
        try:
            record(*args, **kwargs)
        # Whatever the journal or the SDK does, a metric is never worth the step that closed the row.
        except Exception as e:  # noqa: BLE001
            _LOG.warning("a metric was not recorded", extra={"metric": record.__name__, "error": type(e).__name__})

    return guarded


_LOG = logging.getLogger("canopy")
#: Each run table's role.
ROLES: Mapping[RunTable, Role] = {
    "runs": Role.WORKER,
    "task_runs": Role.TASK,
    "review_runs": Role.REVIEW,
    "chore_runs": Role.CHORE,
    # A planner's, as a ticket's plan run in `runs` is.
    "epic_runs": Role.WORKER,
}


@_never_raises
def ended(conn: sqlite3.Connection, table: RunTable, run_id: int) -> None:
    """Record the metrics of run `run_id` of `table`, just closed; nothing while metrics are off."""
    if not metrics.enabled():
        return
    row = records.select(records.of_table(table)).where("id = ?", run_id).one(conn)
    if row is not None:
        _meter(ROLES[table], asdict(row))


@_never_raises
def overseer_ended(conn: sqlite3.Connection, tick_id: int) -> None:
    """Record the metrics of tick `tick_id`'s overseer runs, all closed as the tick closes."""
    if not metrics.enabled():
        return
    closed = (
        records.select(records.OverseerRun)
        .where("tick_id = ?", tick_id)
        .where("status != ?", OverseerRunStatus.RUNNING)
        .all(conn)
    )
    for row in closed:
        _meter(Role.OVERSEER, asdict(row))


@_never_raises
def decisions(conn: sqlite3.Connection, tick_id: int, *, dry_run: bool) -> None:
    """Count tick `tick_id`'s decisions as it closes, each by its kind, its outcome, and who made it.

    Read from the journal, as a run's metrics are: the overseer records its decisions through canopy's tools, in a
    process of their own. The guard that refused one is left out: guards are words each verb names as it refuses,
    held in no closed vocabulary (D132).
    """
    if not metrics.enabled():
        return
    found = Counter(_decided(row) for row in records.select(records.Decision).where("tick_id = ?", tick_id).all(conn))
    for (kind, outcome, decider), n in found.items():
        by = {} if decider is None else {"decider": decider}
        metrics.count("canopy.decisions", n, kind=kind, outcome=outcome, dry_run=dry_run, **by)


@_never_raises
def abandoned(conn: sqlite3.Connection, tick_ids: Iterable[int]) -> None:
    """Count the ticks a dead process left, `tick_ids`, their decisions, and their overseer's runs, as one closes them.

    A tick that died recorded no metrics, so it is counted here or never. Its duration is not recorded: it ended when
    its process died, not when it was found dead.
    """
    if not metrics.enabled():
        return
    for tick_id in tick_ids:
        tick = records.select(records.Tick).where("id = ?", tick_id).one(conn)
        if tick is not None:
            metrics.count("canopy.ticks", status=TickStatus.ABANDONED, dry_run=tick.dry_run)
            decisions(conn, tick_id, dry_run=tick.dry_run)
        tick_closed(conn, tick_id)
        overseer_ended(conn, tick_id)


#: The run tables whose running runs fill each role's capacity: every run that holds a slot fills `max_workers`, a
#: review's and a task's within it, and a chore runs apart (DESIGN §6, §19, §21, §36). A worker's are `db.SLOT_TABLES`.
FILLED_BY: Mapping[Role, Collection[RunTable]] = {
    Role.WORKER: ("runs", "review_runs", "task_runs", "epic_runs"),
    Role.REVIEW: ("review_runs",),
    Role.TASK: ("task_runs",),
    Role.CHORE: ("chore_runs",),
}


@_never_raises
def active(conn: sqlite3.Connection, capacity: Capacity) -> None:
    """Set the runs of each role at work now, and how full each role's `capacity` is, as a tick closes."""
    if not metrics.enabled():
        return
    # One statement, so one snapshot of the journal: a run that starts or ends meanwhile is in every count or in none.
    each = (
        sql.select("? AS run_table, count(*) AS running", table)
        .from_("{}", sql.name(table))
        .where("status = 'running'")
        for table in ROLES
    )
    counts = sql.union(*each, every=True)
    running = {row.run_table: row.running for row in records.fetch_all(conn, _Running, counts)}
    for role in dict.fromkeys(ROLES.values()):
        at_work = sum(running[table] for table, owner in ROLES.items() if owner is role)
        metrics.gauge("canopy.runs.active", at_work, role=role)
    limits = {
        Role.WORKER: capacity.max_workers,
        Role.REVIEW: capacity.max_reviews,
        Role.TASK: capacity.max_tasks,
        Role.CHORE: capacity.max_chores,
    }
    for role, tables in FILLED_BY.items():
        metrics.gauge("canopy.capacity.used", sum(running[t] for t in tables), role=role)
        metrics.gauge("canopy.capacity.limit", limits[role], role=role)


@_never_raises
def tick_closed(conn: sqlite3.Connection, tick_id: int) -> None:
    """Set `canopy.tick.last`, under tick `tick_id`'s status, to when it closed: no tick for long is a loop stopped."""
    if not metrics.enabled():
        return
    tick = records.select(records.Tick).where("id = ?", tick_id).one(conn)
    if tick is not None and tick.ended_at is not None:
        metrics.gauge("canopy.tick.last", _moment(tick.ended_at).timestamp(), unit="s", status=tick.status)


@_never_raises
def tickets(conn: sqlite3.Connection) -> None:
    """Set `canopy.tickets` to the open tickets in each phase: neither done nor stopped, so the ones the loop works.

    A ticket's phase is the one its row holds, as the overseer or the harness last set it; one with none set yet is in
    no phase. A phase no open ticket is in is set to 0, so a phase emptied since the last tick reads empty.
    """
    if not metrics.enabled():
        return
    stopped = (
        sql.select("subject_id").from_("starts").where("subject_kind = 'ticket' AND status = ?", StartStatus.STOPPED)
    )
    query = (
        sql.select("phase, count(*) AS tickets")
        .from_("tickets")
        .where("done = 0 AND phase IS NOT NULL")
        .where("key NOT IN ({})", stopped)
        .group_by("phase")
    )
    found = {row.phase: row.tickets for row in records.fetch_all(conn, _InPhase, query)}
    for phase in Phase:
        metrics.gauge("canopy.tickets", found.get(phase, 0), phase=phase)


@_never_raises
def attention(open_items: int) -> None:
    """Set `canopy.attention.open` to the `open_items` on the attention list as the tick published it."""
    metrics.gauge("canopy.attention.open", open_items)


@_never_raises
def disk(state_dir: Path) -> None:
    """Set `canopy.disk.free` to the bytes free where `state_dir` is, which `loop.min_free_disk_mib` guards (§6)."""
    if not metrics.enabled():
        return
    metrics.gauge("canopy.disk.free", shutil.disk_usage(state_dir).free, unit="By")


@dataclass(frozen=True)
class _Running(records.View):
    """How many of one run table's runs are at work."""

    run_table: str
    running: int


@dataclass(frozen=True)
class _InPhase(records.View):
    """How many open tickets are in one phase."""

    phase: Phase
    tickets: int


#: The word a refusal's action starts with, before the guard that refused it.
_REFUSED = "refused"
#: Each word an action may start with that names its kind.
_KIND_WORDS = frozenset(kind.value for kind in DecisionKind)


def _decided(row: records.Decision) -> tuple[DecisionKind, DecisionOutcome, Decider | None]:
    """A decision's labels: its kind, read from its action's first word, its outcome, and who made it.

    Returns:
        The kind, the outcome, and the decider, None on a decision from before the journal recorded one.
    """
    word = row.action.partition(":")[0]
    if word == _REFUSED:
        kind = DecisionKind.DISPATCH if row.kind is not None else DecisionKind.OTHER
        return kind, DecisionOutcome.REFUSED, row.decider
    kind = DecisionKind(word) if word in _KIND_WORDS else DecisionKind.OTHER
    return kind, DecisionOutcome.MADE, row.decider


#: Each token type, by the column that holds it.
_TOKEN_COLUMNS: Mapping[TokenType, str] = {
    TokenType.INPUT: "tokens_input",
    TokenType.OUTPUT: "tokens_output",
    TokenType.REASONING: "tokens_reasoning",
    TokenType.CACHE_READ: "tokens_cache_read",
    TokenType.CACHE_WRITE: "tokens_cache_write",
}


def _meter(role: Role, row: Mapping[str, Any]) -> None:
    """Record one ended run's metrics, from its row's columns."""
    status = row["status"]
    kind = {"kind": row["kind"]} if role is Role.WORKER else {}
    metrics.count("canopy.runs", role=role, status=status, **kind)
    if row["ended_at"] is not None:
        seconds = (_moment(row["ended_at"]) - _moment(row["started_at"])).total_seconds()
        metrics.record("canopy.run.duration", seconds, unit="s", role=role, status=status)
    model = row["model"]
    if row["cost_usd"] is not None:
        metrics.count("canopy.cost", float(row["cost_usd"]), unit="USD", model=model, role=role)
    for token_type, column in _TOKEN_COLUMNS.items():
        if row[column]:
            metrics.count("canopy.tokens", int(row[column]), unit="{token}", model=model, role=role, type=token_type)


def _moment(stamp: str) -> datetime:
    """A time the journal wrote, read as `db.parse_time` reads it: `db` calls this module, so it cannot import `db`.

    Returns:
        The moment, in UTC.
    """
    return datetime.fromisoformat(stamp).astimezone(UTC)
