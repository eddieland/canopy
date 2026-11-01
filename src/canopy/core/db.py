"""The SQLite journal: connection setup, migrations, and the queries the loop makes.

The journal holds facts about the loop only (DESIGN §4, §11). Nothing here is read back as a fact about the world.
Connections run in autocommit mode; anything that must be atomic opens its own transaction.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable, Collection, Generator, Iterable, Mapping, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Literal, LiteralString, assert_never

from canopy.core import item_numbers, records, sql
from canopy.core.vocab import (
    Decider,
    NumberedItem,
    Phase,
    PlannerApproval,
    PlanStatus,
    PoolKind,
    ResumeReason,
    RunKind,
    SeenKind,
    StartStatus,
    TickStatus,
)
from canopy.infra import procs
from canopy.runtime.report import ToolUse, Usage

if TYPE_CHECKING:
    from canopy.core.vocab import AnyRunStatus, RunStatus

DB_FILE_NAME = "canopy.db"
# How long a connection waits for another to release the write lock before its write fails as `database is locked`.
BUSY_SECONDS = 10.0
_MIGRATION_RE = re.compile(r"(\d{4})_([a-z0-9_]+)\.sql")
# The rationale the overseer gives a `done` decision for a ticket the tracker reports closed (DESIGN §7).
CLOSED_RATIONALE = "closed"
# The version of canopy this process runs, recorded on each tick it starts (DESIGN §6). Read once, at import: an upgrade
# while `canopy loop` runs replaces the installed package's metadata, not the code this process loaded, so a read per
# tick would name the new release on ticks the old code ran.
CANOPY_VERSION = version("canopy")

# The cursors the `ticket-set` tool names, and the column each one updates. The comment cursor is the ticket's; the
# review and ci cursors are a unit's, since each unit has its own PR (DESIGN §18). The message cursor is a ticket's,
# over journal message ids (DESIGN §22); the rest are journal numbers (§35).
TICKET_CURSORS: Mapping[str, LiteralString] = {"comment": "comment_cursor", "message": "last_message_id"}
UNIT_CURSORS: Mapping[str, LiteralString] = {"review": "review_cursor", "ci": "ci_cursor"}
CURSOR_COLUMNS: Mapping[str, LiteralString] = {**TICKET_CURSORS, **UNIT_CURSORS}
#: The columns of a ticket whose change is activity, as `change_ticket` sets them. A column name in SQL comes from
#: here, never from input.
type TicketChange = Literal["phase", "title", "done", "plan_setting"]
# The tables of detached runs (DESIGN §6): workers', chores', reviews', and tasks'. Each has the same lifecycle,
# written once below over a table from this closed set: claimed by its process's pid, its agent's pid recorded, its
# report, and its close. A table name in SQL comes from here, never from input.
type RunTable = Literal["runs", "chore_runs", "review_runs", "task_runs"]
# The rows whose agent's progress `set_progress` records as it prints; a worker run's is `set_run_progress`.
type ProgressTable = Literal["ticks", "chore_runs", "task_runs", "review_runs"]
RUN_TABLES: tuple[RunTable, ...] = ("runs", "chore_runs", "review_runs", "task_runs")
# What each run table's rows are called in a message, and the column it keeps its agent's pid in: the leader of the
# process group the run's own process starts, which outlives that process if it dies.
RUN_NOUNS: Mapping[RunTable, str] = {
    "runs": "run",
    "chore_runs": "chore run",
    "review_runs": "review run",
    "task_runs": "task run",
}
AGENT_PID: Mapping[RunTable, LiteralString] = {
    "runs": "worker_pid",
    "chore_runs": "agent_pid",
    "review_runs": "agent_pid",
    "task_runs": "agent_pid",
}
#: The run tables whose runs each hold a slot, and so count toward `capacity.max_workers` (DESIGN §6, §21, §36).
SLOT_TABLES: tuple[RunTable, ...] = ("runs", "review_runs", "task_runs")


class MigrationError(Exception):
    """The migrations on disk and the database disagree."""


@dataclass(frozen=True)
class RunSlot:
    """One slot a run leased: the repository whose pool it came from, the slot, its lease, and the run's base there.

    `pool` is the pool that made the lease, which is the pool it goes back to (DESIGN §18).
    """

    repo: str
    slot_path: Path
    lease_id: str
    lease_holder: str
    base_branch: str
    pool: PoolKind = PoolKind.TREEHOUSE


@dataclass(frozen=True)
class Event:
    """A point event for notification sinks (DESIGN §20), recorded with the fact it reports."""

    group: str
    kind: str
    fields: Mapping[str, object]


@dataclass(frozen=True)
class Comment:
    """A tracker comment as its message records it (DESIGN §22, §35): its id, author's account id, and time."""

    id: str
    author: str
    at: str
    truncated: bool


@dataclass(frozen=True)
class Migration:
    """One migration file on disk."""

    version: int
    name: str
    path: Path


def format_time(moment: datetime) -> str:
    """UTC, millisecond precision, the same shape as the schema's own defaults.

    Returns:
        `moment` in UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ`.
    """
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_time(stamp: str) -> datetime:
    """Read a timestamp the journal wrote, as an aware UTC datetime.

    Returns:
        The moment `stamp` names, with its timezone set to UTC.
    """
    return datetime.fromisoformat(stamp).astimezone(UTC)


def now() -> str:
    """The current time as the journal stores it.

    Returns:
        Now, in the shape `format_time` writes.
    """
    return format_time(datetime.now(UTC))


def connect(path: Path) -> sqlite3.Connection:
    """Open the journal at `path` in WAL mode with foreign keys on, creating its directory.

    Returns:
        An autocommit connection whose rows are `sqlite3.Row`. The caller closes it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, autocommit=True, timeout=BUSY_SECONDS)
    conn.row_factory = sqlite3.Row
    # WAL must be set outside a transaction; migration 0001 repeats it inside one, where it is then a no-op.
    sql.execute(conn, sql.frag("PRAGMA journal_mode = WAL"))
    sql.execute(conn, sql.frag("PRAGMA foreign_keys = ON"))
    return conn


def discover(migrations_dir: Path) -> list[Migration]:
    """Return the migrations in `migrations_dir`, checking names and numbering.

    Raises:
        MigrationError: A file name is not `NNNN_name.sql`, or the versions are not 1, 2, 3, ... with no gaps.
    """
    found: list[Migration] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        m = _MIGRATION_RE.fullmatch(path.name)
        if m is None:
            raise MigrationError(f"migration file name must be NNNN_name.sql: {path.name}")
        found.append(Migration(int(m.group(1)), m.group(2), path))
    versions = [m.version for m in found]
    if versions != list(range(1, len(found) + 1)):
        raise MigrationError(f"migrations must be numbered 1, 2, 3, ... with no gaps; found {versions}")
    return found


@contextmanager
def transaction(conn: sqlite3.Connection) -> Generator[None]:
    """Run the block in a `BEGIN IMMEDIATE` transaction; roll back if it raises.

    Inside a transaction already, the block runs in that one, which commits or rolls back with it: so a call that
    writes several records together, as a `ticket-set` of several tickets does, can wrap writes that open their own.
    """
    if conn.in_transaction:
        yield
        return
    sql.execute(conn, sql.frag("BEGIN IMMEDIATE"))
    try:
        yield
    except BaseException:
        sql.execute(conn, sql.frag("ROLLBACK"))
        raise
    sql.execute(conn, sql.frag("COMMIT"))


def migrate(conn: sqlite3.Connection, migrations_dir: Path) -> list[int]:
    """Apply pending migrations in order, in one transaction. Returns the versions applied.

    Returns:
        The versions this call applied, in order; empty when the journal was already current.

    Raises:
        MigrationError: The migration files are misnamed or misnumbered, the journal has migrations this canopy does
            not know, or a run an earlier canopy started is still alive while there is something to apply.
    """
    known = discover(migrations_dir)
    applied_now: list[int] = []
    # IMMEDIATE takes the write lock before reading what is applied, so two processes cannot both apply a migration.
    with transaction(conn):
        has_table = sql.execute(conn, _table_named("schema_migrations")).fetchone()
        applied = (
            {int(r[0]) for r in sql.execute(conn, sql.select("version").from_("schema_migrations"))}
            if has_table
            else set()
        )
        unknown = applied - {m.version for m in known}
        if unknown:
            # Runs the journal's own canopy started come first: the fix for an unknown journal may be a fresh one, and
            # moving this one aside under a live run would lose it (D068).
            _check_no_live_runs(conn)
            raise MigrationError(f"the journal has migrations this canopy does not know: {sorted(unknown)}")
        pending = [m for m in known if m.version not in applied]
        if pending:
            _check_no_live_runs(conn)
        for m in pending:
            conn.executescript(m.path.read_text())
            # The migrations' own ledger, which no row type reads: it is written before any table it would check.
            ledger = sql.insert("schema_migrations", version=m.version, name=m.name)  # noqa: TID251
            sql.execute(conn, ledger.or_ignore())
            applied_now.append(m.version)
    return applied_now


def live_runs(conn: sqlite3.Connection) -> list[str]:
    """Every run that is `running` and whose process is alive, read from any schema this canopy or an older one wrote.

    A run whose `_run` is gone does not count; the next tick's reconcile closes it (DESIGN §6).

    Returns:
        Each run as a message names it, `run 3` or `review run 4`, by table, then by id.
    """
    live: list[str] = []
    # Every table of detached runs: each process writes its own row when it ends.
    for table in RUN_TABLES:
        if not sql.execute(conn, _table_named(table)).fetchone():
            continue
        rows = sql.execute(
            conn,
            sql.select("id, pid, log_path").from_(table).where("status = 'running'").order_by("id"),
        )
        live += [f"{RUN_NOUNS[table]} {r['id']}" for r in rows if procs.running(Path(r["log_path"]), r["pid"])]
    return live


def _table_named(table: str) -> sql.Select:
    """A query of one row if the journal has a table named `table`, and none if it has not.

    Returns:
        The query.
    """
    return sql.select("1").from_("sqlite_master").where("type = 'table' AND name = ?", table)


def _check_no_live_runs(conn: sqlite3.Connection) -> None:
    """Refuse to migrate while a `_run` is alive: it was started by an earlier canopy, which wrote the old schema.

    Raises:
        MigrationError: A run, chore run, review run, or task run is `running` and its process is alive.
    """
    live = live_runs(conn)
    if live:
        runs = f"{live[0]} is" if len(live) == 1 else f"{', '.join(live)} are"
        raise MigrationError(
            f"this canopy changes the journal, but {runs} still working for the canopy before it and would fail "
            "writing the old journal. Run canopy again once they finish.",
        )


def record_event(conn: sqlite3.Connection, event: Event) -> int:
    """Add `event` to the outbox and return its id. Inside a transaction, it commits or rolls back with the fact.

    Returns:
        The new `notify_events` row's id.
    """
    cur = records.insert(
        records.NotifyEvent,
        grp=event.group,
        kind=event.kind,
        at=now(),
        fields=json.dumps(dict(event.fields)),
    ).run(conn)
    return rowid(cur)


def rowid(cur: sqlite3.Cursor) -> int:
    """Return the id of the row the INSERT run through `cur` made.

    Returns:
        The new row's id.

    Raises:
        sqlite3.DatabaseError: The INSERT made no row.
    """
    if cur.lastrowid is None:
        raise sqlite3.DatabaseError("INSERT returned no row id")
    return cur.lastrowid


# Ticks


def start_tick(conn: sqlite3.Connection, *, dry_run: bool) -> int:
    """Insert a `running` tick row, with the version of canopy running it, and return its id.

    Returns:
        The new tick's id.
    """
    cur = records.insert(records.Tick, started_at=now(), dry_run=int(dry_run), canopy_version=CANOPY_VERSION).run(conn)
    return rowid(cur)


def set_tick_model(conn: sqlite3.Connection, tick_id: int, model: str | None) -> None:
    """Record the model tick `tick_id`'s overseer asks for as it starts (DESIGN §13); None for the runtime's default."""
    records.update(records.Tick).set(model=model).where("id = ?", tick_id).run(conn)


def finish_tick(conn: sqlite3.Connection, tick_id: int, status: TickStatus, summary: str) -> None:
    """Close a tick with its final status and summary."""
    records.update(records.Tick).set(ended_at=now(), status=status, summary=summary).where("id = ?", tick_id).run(conn)


def set_tick_read(conn: sqlite3.Connection, tick_id: int) -> None:
    """Record what a tick has read up to: the newest message, and the time (§6, §22).

    Every message up to it was there to see, and every run that started or ended before it.
    """
    newest = sql.select("coalesce(max(id), 0)").from_("messages")
    (
        records.update(records.Tick)
        .set(message_id=sql.frag("({})", newest), read_at=now())
        .where("id = ?", tick_id)
        .run(conn)
    )


def set_tick_loop(conn: sqlite3.Connection, tick_id: int, *, idle: bool, woken_by: str) -> None:
    """Record what the loop knew about a tick it ran: whether it was idle, and what ended the wait before it (§6)."""
    records.update(records.Tick).set(idle=int(idle), woken_by=woken_by).where("id = ?", tick_id).run(conn)


def set_tick_query(conn: sqlite3.Connection, tick_id: int, *, due: bool) -> None:
    """Record whether a tick's state block told the overseer to run the tracker query (§7, Spacing the query)."""
    records.update(records.Tick).set(query_due=int(due)).where("id = ?", tick_id).run(conn)


def set_tick_overseer(conn: sqlite3.Connection, tick_id: int, *, ran: bool) -> None:
    """Record whether a tick runs its overseer: not when it is halted, nor when nothing is left to it (DESIGN §39)."""
    records.update(records.Tick).set(overseer_ran=int(ran)).where("id = ?", tick_id).run(conn)


def last_query_at(conn: sqlite3.Connection) -> str | None:
    """When the newest live `ok` tick that ran the tracker query started (§7, Spacing the query).

    A tick from before `query_due` was recorded ran it. A dry run, and a tick that did not close `ok`, are not counted:
    one that skipped or failed may not have read the query to the end.

    Returns:
        That tick's `started_at`, or None if no tick has run the query.
    """
    query = (
        sql.select("max(started_at)")
        .from_("ticks")
        .where("status = 'ok' AND dry_run = 0 AND coalesce(query_due, 1) = 1")
    )
    row = sql.execute(conn, query).fetchone()
    return None if row is None or row[0] is None else str(row[0])


def previous_tick(conn: sqlite3.Connection, tick_id: int) -> records.Tick | None:
    """Return the tick before `tick_id`, whatever its status, or None if it is the first."""
    return records.select(records.Tick).where("id < ?", tick_id).order_by("id DESC").limit(1).one(conn)


def runs_moved_after(conn: sqlite3.Connection, since: str) -> bool:
    """Whether a run of any table started or ended after `since`, a time the journal wrote (§6).

    Returns:
        True if at least one did.
    """
    return any(
        sql.execute(
            conn,
            sql.select("1").from_(table).where("started_at > ? OR ended_at > ?", since, since).limit(1),
        ).fetchone()
        for table in RUN_TABLES
    )


def runs_ended_after(conn: sqlite3.Connection, since: str) -> bool:
    """Whether a run of any table ended after `since`, a time the journal wrote (§6).

    Returns:
        True if at least one did.
    """
    return any(
        sql.execute(conn, sql.select("1").from_(table).where("ended_at > ?", since).limit(1)).fetchone()
        for table in RUN_TABLES
    )


def starts_moved_after(conn: sqlite3.Connection, since: str) -> bool:
    """Whether the operator started or stopped a subject after `since`, a time the journal wrote (§6, §22).

    Returns:
        True if a start record's latest start or stop is newer.
    """
    query = sql.select("1").from_("starts").where("started_at > ? OR stopped_at > ?", since, since).limit(1)
    return sql.execute(conn, query).fetchone() is not None


def granted_after(conn: sqlite3.Connection, since: str) -> bool:
    """Whether the operator granted a ticket's attempts or a PR's reviews after `since`, a time the journal wrote (§6).

    Returns:
        True if at least one grant is newer.
    """
    tables: tuple[Literal["attempt_grants", "review_grants"], ...] = ("attempt_grants", "review_grants")
    return any(
        sql.execute(conn, sql.select("1").from_(table).where("granted_at > ?", since).limit(1)).fetchone()
        for table in tables
    )


def phases(conn: sqlite3.Connection) -> dict[tuple[str, str | None], str | None]:
    """Every ticket's and unit's recorded phase, to tell which a tick changed (§6, churn).

    Returns:
        The phase by ticket key and repository: None for the ticket's own, the unit's repository for a unit's.
    """
    found: dict[tuple[str, str | None], str | None] = {}
    for key, phase in sql.execute(conn, sql.select("key, phase").from_("tickets")):
        found[str(key), None] = None if phase is None else str(phase)
    for key, repo, phase in sql.execute(conn, sql.select("ticket_key, repo, phase").from_("ticket_units")):
        found[str(key), str(repo)] = None if phase is None else str(phase)
    return found


def acknowledged_message_id(conn: sqlite3.Connection) -> int | None:
    """The newest message the latest `ok` tick read, or None before the first `ok` tick that recorded one (§22).

    Returns:
        That message's id, or None.
    """
    query = sql.select("message_id").from_("ticks").where("status = 'ok'").order_by("id DESC").limit(1)
    row = sql.execute(conn, query).fetchone()
    return None if row is None or row[0] is None else int(row[0])


def abandon_unfinished_ticks(conn: sqlite3.Connection) -> list[int]:
    """Close ticks left `running` by a tick process that died. Call only while holding the tick lock.

    Returns:
        The ids of the ticks marked `abandoned`.
    """
    running = sql.select("id").from_("ticks").where("status = ?", TickStatus.RUNNING)
    ids = [int(r[0]) for r in sql.execute(conn, running)]
    abandon = (
        records.update(records.Tick)
        .set(ended_at=sql.ROW, status=TickStatus.ABANDONED, summary="the tick process exited without finishing")
        .where("id = ?", sql.ROW)
    )
    sql.execute_many(conn, abandon.statement, [(now(), i) for i in ids])
    return ids


def get_tick(conn: sqlite3.Connection, tick_id: int) -> records.Tick | None:
    """Return the tick row with `tick_id`, or None."""
    return records.select(records.Tick).where("id = ?", tick_id).one(conn)


def tick_neighbours(conn: sqlite3.Connection, tick_id: int) -> tuple[int | None, int | None]:
    """Return the ids of the ticks just before and just after `tick_id`, dry runs included, each None at an end.

    Returns:
        The previous tick's id and the next one's, found by query rather than by counting, so a gap is stepped over.
    """
    before = sql.execute(conn, sql.select("max(id)").from_("ticks").where("id < ?", tick_id)).fetchone()[0]
    after = sql.execute(conn, sql.select("min(id)").from_("ticks").where("id > ?", tick_id)).fetchone()[0]
    return before, after


def last_tick(conn: sqlite3.Connection) -> records.Tick | None:
    """Return the most recent tick row, or None."""
    return records.select(records.Tick).order_by("id DESC").limit(1).one(conn)


# Tickets


def touch_ticket(conn: sqlite3.Connection, key: str, repo: str) -> None:
    """Record that `key` was seen now, creating its row on first sight."""
    ts = now()
    records.insert(
        records.Ticket,
        key=key,
        repo=repo,
        first_seen_at=ts,
        last_seen_at=ts,
        changed_at=ts,
    ).on_conflict(
        "(key) DO UPDATE SET last_seen_at = excluded.last_seen_at",
    ).run(conn)


def change_ticket(conn: sqlite3.Connection, key: str, column: TicketChange, value: sql.Value) -> None:
    """Set one of `key`'s columns, and mark the ticket changed only if the value is new.

    So a tick that sets what was already there is no activity on the web UI's lists (DESIGN §22).
    """
    (
        records.update(records.Ticket)
        .set_to("{} = ?", sql.name(column), value)
        .set(changed_at=now())
        .where("key = ? AND {} IS NOT ?", key, sql.name(column), value)
        .run(conn)
    )


def set_ticket(
    conn: sqlite3.Connection,
    key: str,
    repo: str,
    *,
    phase: Phase | None = None,
    cursors: Mapping[str, str] | None = None,
    done: bool = False,
    title: str | None = None,
) -> None:
    """Record a ticket's own phase, its cursors, its done flag, or its title in one transaction."""
    with transaction(conn):
        touch_ticket(conn, key, repo)
        if phase is not None:
            change_ticket(conn, key, "phase", phase)
        if title is not None:
            change_ticket(conn, key, "title", title)
        for name, value in (cursors or {}).items():
            cursor = sql.name(TICKET_CURSORS[name])
            records.update(records.Ticket).set_to("{} = ?", cursor, value).where("key = ?", key).run(conn)
        if done:
            change_ticket(conn, key, "done", 1)


def _ensure_unit(conn: sqlite3.Connection, key: str, unit: str) -> None:
    """Create `key`'s unit in repository `unit` if it has none. Call inside a transaction."""
    records.insert(records.TicketUnit, ticket_key=key, repo=unit).on_conflict("(ticket_key, repo) DO NOTHING").run(conn)


def set_unit(
    conn: sqlite3.Connection,
    key: str,
    repo: str,
    unit: str,
    *,
    phase: str | None = None,
    cursors: Mapping[str, str] | None = None,
    pr_url: str | None = None,
) -> None:
    """Record a unit's phase, review and ci cursors, or PR in one transaction, creating the unit if it has no row.

    `repo` is the workspace root, as for `set_ticket`; `unit` is the repository's name in the workspace.
    """
    with transaction(conn):
        touch_ticket(conn, key, repo)
        _ensure_unit(conn, key, unit)
        the_unit = records.update(records.TicketUnit).where("ticket_key = ? AND repo = ?", key, unit)
        changes: tuple[tuple[Literal["phase", "pr_url"], str | None], ...] = (("phase", phase), ("pr_url", pr_url))
        for column, value in changes:
            if value is None:
                continue
            change = the_unit.set_to("{} = ?", sql.name(column), value).where("{} IS NOT ?", sql.name(column), value)
            if change.run(conn).rowcount:
                records.update(records.Ticket).set(changed_at=now()).where("key = ?", key).run(conn)
        for name, value in (cursors or {}).items():
            the_unit.set_to("{} = ?", sql.name(UNIT_CURSORS[name]), value).run(conn)


def set_pr_title(conn: sqlite3.Connection, pr_url: str, title: str) -> None:
    """Record `title` as the PR's own title, replacing any earlier one: for display, never as truth (DESIGN §22)."""
    records.insert(records.PrTitle, pr_url=pr_url, title=title, updated_at=now()).on_conflict(
        "(pr_url) DO UPDATE SET title = excluded.title, updated_at = excluded.updated_at",
    ).run(conn)


def pr_titles(conn: sqlite3.Connection, pr_urls: Collection[str]) -> dict[str, str]:
    """Return the own title recorded for each of `pr_urls` that has one, by URL."""
    query = sql.select("pr_url, title").from_("pr_titles").where_in("pr_url", pr_urls)
    return {str(r[0]): str(r[1]) for r in sql.execute(conn, query)}


def ticket_titles(conn: sqlite3.Connection, keys: Collection[str]) -> dict[str, str]:
    """Return the title of each of tickets `keys` the overseer has named, by key."""
    query = sql.select("key, title").from_("tickets").where_in("key", keys).where("title IS NOT NULL")
    return {str(r[0]): str(r[1]) for r in sql.execute(conn, query)}


def units(conn: sqlite3.Connection, key: str) -> list[records.TicketUnit]:
    """Return `key`'s units, by repository."""
    return records.select(records.TicketUnit).where("ticket_key = ?", key).order_by("repo").all(conn)


def all_units(conn: sqlite3.Connection) -> dict[str, list[records.TicketUnit]]:
    """Return every ticket's units, by ticket key, each list by repository."""
    found: dict[str, list[records.TicketUnit]] = {}
    query = records.select(records.TicketUnit).order_by("ticket_key, repo")
    for row in query.all(conn):
        found.setdefault(row.ticket_key, []).append(row)
    return found


def get_ticket(conn: sqlite3.Connection, key: str) -> records.Ticket | None:
    """Return the ticket row for `key`, or None."""
    return records.select(records.Ticket).where("key = ?", key).one(conn)


def open_tickets(conn: sqlite3.Connection) -> list[records.Ticket]:
    """Return the tickets not marked done, by key."""
    return records.select(records.Ticket).where("done = 0").order_by("key").all(conn)


def recently_done(conn: sqlite3.Connection, since: str) -> list[sqlite3.Row]:
    """Return the tickets marked done whose newest `done` decision is at or after `since`, by key (DESIGN §7).

    Each row has `key` and `done_at`, that decision's time. Not one: a ticket marked done with no `done` decision since
    the operator last forgot it, or whose newest one says `closed`, since the tracker reports a closed ticket closed,
    and leaving it out lets the query find it again once it is reopened.
    """
    # Each done ticket's newest decision by `decisions_ticket`, not a scan of every decision ever recorded.
    newest_done = sql.select("max(id)").from_("decisions").where("ticket_key = t.key AND action = 'done'")
    query = (
        sql.select("t.key, d.created_at AS done_at")
        .from_("tickets t")
        .join("decisions d ON d.id = ({})", newest_done)
        .where("t.done = 1 AND d.created_at >= ? AND d.rationale != ?", since, CLOSED_RATIONALE)
        .where("t.forgotten_at IS NULL OR d.created_at > t.forgotten_at")
        .order_by("t.key")
    )
    return sql.execute(conn, query).fetchall()


# The run lifecycle (DESIGN §6, §8): what every table of detached runs shares

# A run with its ticket's title as `ticket_title`, a `resume`'s reasons as `reasons`, comma-separated (read them with
# `reasons_in`), and whether the operator stopped its ticket as `ticket_stopped`, for display (DESIGN §8, §13, §22).
# Every query a page or `canopy status` shows runs from starts here.
_RUNS = (
    sql.select(
        "r.*, t.title AS ticket_title, "
        "(SELECT group_concat(w.reason, ',') FROM run_reasons w WHERE w.run_id = r.id) AS reasons, "
        "EXISTS (SELECT 1 FROM starts s WHERE s.subject_kind = 'ticket' AND s.subject_id = r.ticket_key "
        "AND s.status = 'stopped') AS ticket_stopped",
    )
    .from_("runs r")
    .left_join("tickets t ON t.key = r.ticket_key")
)
# What a run table's rows are read as: a run with its ticket's title, for display, and any other run as it is.
_RUN_SELECT: Mapping[RunTable, sql.Select] = {
    "runs": _RUNS,
    "chore_runs": sql.select("r.*").from_("chore_runs r"),
    "review_runs": sql.select("r.*").from_("review_runs r"),
    "task_runs": sql.select("r.*").from_("task_runs r"),
}


def running_runs(conn: sqlite3.Connection, table: RunTable) -> list[sqlite3.Row]:
    """Return `table`'s runs with status `running`, oldest first."""
    return sql.execute(conn, _RUN_SELECT[table].where("r.status = 'running'").order_by("r.started_at")).fetchall()


def busy_workers(conn: sqlite3.Connection) -> int:
    """How many runs hold a slot now, and so count toward `capacity.max_workers` (DESIGN §6, §21, §36).

    Returns:
        The running worker and plan runs, review runs, and task runs.
    """
    return sum(len(running_runs(conn, table)) for table in SLOT_TABLES)


def claim_run(conn: sqlite3.Connection, table: RunTable, run_id: int, pid: int) -> bool:
    """Record `pid` as the process working a running run in `table`. Only the first process to claim a run gets it.

    The spawn claims with the pid it started, and the process (`_run`, `_chore`, `_review`) claims with its own, which
    is the same pid; a second process for the same run has a different one and is refused.

    Returns:
        True if `pid` now holds the run; False if the run is not running or another pid holds it.
    """
    claim = (
        records.update(records.of_table(table))
        .set(pid=pid)
        .where("id = ? AND status = 'running' AND (pid IS NULL OR pid = ?)", run_id, pid)
    )
    return claim.run(conn).rowcount == 1


def set_agent_pid(conn: sqlite3.Connection, table: RunTable, run_id: int, pid: int) -> None:
    """Record the pid, and so the process group, of the agent a run in `table` started: a worker, chore, or reviewer."""
    (
        records.update(records.of_table(table))
        .set_to("{} = ?", sql.name(AGENT_PID[table]), pid)
        .where("id = ?", run_id)
        .run(conn)
    )


def set_run_report(
    conn: sqlite3.Connection,
    table: RunTable,
    run_id: int,
    session_id: str | None,
    usage: Usage | None,
    *,
    digest: str | None = None,
    tools: Sequence[ToolUse] = (),
) -> None:
    """Record what the agent runtime reported about a run in `table`: its session, what it cost, and its tools.

    The tools are its tool calls rolled up by tool (DESIGN §13), in place of any recorded before. `digest` names the
    definitions snapshot the run loaded, recorded only when the runtime reported something.
    """
    _set_report(conn, table, run_id, session_id, usage, digest=digest, tools=tools)


def finish_run(
    conn: sqlite3.Connection,
    table: RunTable,
    run_id: int,
    status: AnyRunStatus,
    result_json: str | None,
    *,
    event: Event | None = None,
    then: Callable[[], None] | None = None,
) -> bool:
    """Close a running run in `table`, recording `event` with it. Returns False if it was already closed.

    `then`, when this call closes the run, writes what the run reported beside its result in the same transaction.
    A worker run that reports messages closes with `finish_ticket_run` instead. A review run that ends `done`
    also ends its PR's open review request, as `reviewed`, in the same transaction (DESIGN §21): the request asked for
    one review, and this is it. A request the operator chose personas for asked for one in each (§31): it ends once
    each has a `done` review of the PR started since the request was made.

    Returns:
        True if this call closed the run.
    """
    with transaction(conn):
        closed = _close_run(conn, table, run_id, status, result_json)
        if closed and table == "review_runs":
            _number_review_run(conn, run_id)
        if closed and table == "review_runs" and status == "done":
            # A revision of a review's draft is no review: it answers no request (DESIGN §34).
            its_pr = sql.select("pr_url").from_("review_runs").where("id = ? AND revises IS NULL", run_id)
            (
                records.update(records.ReviewRequest)
                .set(ended_at=now())
                .set_to("end_reason = 'reviewed'")
                .where("ended_at IS NULL AND pr_url = ({})", its_pr)
                .where(
                    "NOT EXISTS (SELECT 1 FROM review_request_personas p WHERE p.request_id = review_requests.id "
                    "AND NOT EXISTS (SELECT 1 FROM review_runs r WHERE r.pr_url = review_requests.pr_url "
                    "AND r.persona = p.persona AND r.status = 'done' AND r.revises IS NULL "
                    "AND r.started_at >= review_requests.created_at))",
                )
                .run(conn)
            )
        if closed and event is not None:
            record_event(conn, event)
        if closed and then is not None:
            then()
    return closed


def _number_review_run(conn: sqlite3.Connection, run_id: int) -> None:
    """Give a review run that just ended its journal number, what a `review` cursor names of it (DESIGN §35)."""
    run = sql.execute(conn, sql.select("pr_url, ended_at").from_("review_runs").where("id = ?", run_id)).fetchone()
    number = item_numbers.take(conn, NumberedItem.REVIEW_RUN, str(run[0]), run_id, at=str(run[1]))
    records.update(records.ReviewRun).set(number=number).where("id = ?", run_id).run(conn)


def _close_run(
    conn: sqlite3.Connection,
    table: RunTable,
    run_id: int,
    status: AnyRunStatus,
    result_json: str | None,
) -> bool:
    """Close a running run in `table`, in the caller's transaction. Nothing changes for one already closed.

    Returns:
        True if this call closed the run.
    """
    close = (
        records.update(records.of_table(table))
        .set(ended_at=now(), status=status, result_json=result_json)
        .where("id = ? AND status = 'running'", run_id)
    )
    return close.run(conn).rowcount == 1


# Runs and decisions


def insert_run(
    conn: sqlite3.Connection,
    *,
    tick_id: int,
    key: str,
    kind: str,
    branch: str,
    slots: Sequence[RunSlot],
    runs_dir: Path,
    works_units: bool = True,
    started: Callable[[int], Event | None] | None = None,
    private: bool = False,
    check: Callable[[], None] | None = None,
    plan_id: int | None = None,
    reasons: Sequence[str] = (),
    rendered: Callable[[int], None] | None = None,
    feedback_plan_id: int | None = None,
    persona: str | None = None,
    persona_digest: str | None = None,
    persona_text: str | None = None,
    model: str | None = None,
    plan_review: PlannerApproval | None = None,
) -> int:
    """Insert a `running` run with no pid yet, logging to `<runs_dir>/<id>.log`, and return its id.

    Each of `slots` is recorded in `run_slots`, and each repository they came from becomes a unit of the ticket with the
    run's branch. A run that does not work in units, a plan, leaves the ticket's branch and units as they
    are: it pushes nothing (DESIGN §25). `started` builds the `run.started` event from the run's id, recorded in the
    same transaction, or None when no sink takes it. `private` marks a run on a private ticket (DESIGN §22). `check`
    runs first in the transaction and refuses the run by raising: what it reads cannot change before the row is written.
    `plan_id` is the approved plan an `implement` or `resume` follows, the one its prompt names (DESIGN §25).
    `reasons` are why a `resume` runs, as its dispatch named them (DESIGN §8).
    `rendered` records, from the run's id, what its prompt was rendered under of agent memory (DESIGN §28).
    `feedback_plan_id` is the approved feedback plan a `resume` follows in place of a ticket's plan (DESIGN §32).
    `persona` and `persona_digest` are the name and text digest of the persona its prompt carries, or None for a kind
    no persona reaches (DESIGN §31); `persona_text` is that text, kept once per digest (`record_persona_text`).
    `model` is the model canopy chose for the run's agent, or None for the runtime's default (DESIGN §13).
    `plan_review` is the level of `policy.planner_may_approve` a plan run's prompt offered, None for another kind (§25).

    Returns:
        The new run's id.
    """
    with transaction(conn):
        if check is not None:
            check()
        run = records.insert(
            records.Run,
            tick_id=tick_id,
            ticket_key=key,
            kind=kind,
            branch=branch,
            started_at=now(),
            log_path="",
            private=int(private),
            plan_id=plan_id,
            feedback_plan_id=feedback_plan_id,
            persona=persona,
            persona_digest=persona_digest,
            model=model,
            plan_review=plan_review,
        )
        run_id = rowid(run.run(conn))
        record_persona_text(conn, persona_digest, persona_text)
        records.update(records.Run).set(log_path=str(runs_dir / f"{run_id}.log")).where("id = ?", run_id).run(conn)
        records.insert_rows(
            records.RunSlot,
            ("run_id", "repo", "slot_path", "lease_id", "lease_holder", "base_branch", "pool"),
        ).many(
            conn,
            [(run_id, s.repo, str(s.slot_path), s.lease_id, s.lease_holder, s.base_branch, s.pool) for s in slots],
        )
        records.insert_rows(records.RunReason, ("run_id", "reason")).many(conn, [(run_id, r) for r in reasons])
        event = started(run_id) if started is not None else None
        if event is not None:
            record_event(conn, event)
        if rendered is not None:
            rendered(run_id)
        if not works_units:
            return run_id
        records.update(records.Ticket).set(branch=branch).where("key = ?", key).run(conn)
        for slot in slots:
            _ensure_unit(conn, key, slot.repo)
            (
                records.update(records.TicketUnit)
                .set(branch=branch)
                .where("ticket_key = ? AND repo = ?", key, slot.repo)
                .run(conn)
            )
    return run_id


def run_reasons(conn: sqlite3.Connection, run_ids: Sequence[int]) -> dict[int, tuple[ResumeReason, ...]]:
    """Return why each `resume` in `run_ids` ran, in the vocabulary's order (DESIGN §8). A run with none is missing."""
    if not run_ids:
        return {}
    rows = records.select(records.RunReason).where_in("run_id", run_ids).all(conn)
    found: dict[int, set[ResumeReason]] = {}
    for row in rows:
        found.setdefault(row.run_id, set()).add(row.reason)
    return {run_id: tuple(r for r in ResumeReason if r in named) for run_id, named in found.items()}


def reasons_in(row: sqlite3.Row) -> tuple[ResumeReason, ...]:
    """Return a run row's reasons, in the vocabulary's order: none for a row not read with them, or a run without."""
    # `keys()`, since `in` a Row tests its values.
    named: list[str] = str(row["reasons"] or "").split(",") if "reasons" in row.keys() else []  # noqa: SIM118
    return tuple(r for r in ResumeReason if r in named)


def run_slots(conn: sqlite3.Connection, run_id: int) -> list[records.RunSlot]:
    """Return the slots run `run_id` leased, by repository."""
    return records.select(records.RunSlot).where("run_id = ?", run_id).order_by("repo").all(conn)


def all_run_slots(conn: sqlite3.Connection, run_ids: Sequence[int]) -> dict[int, list[records.RunSlot]]:
    """Return the slots of each run in `run_ids`, by run id, each list by repository."""
    found: dict[int, list[records.RunSlot]] = {i: [] for i in run_ids}
    if not run_ids:
        return found
    query = records.select(records.RunSlot).where_in("run_id", run_ids).order_by("run_id, repo")
    for row in query.all(conn):
        found[row.run_id].append(row)
    return found


def get_run(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row | None:
    """Return the run with `run_id`, or None."""
    row: sqlite3.Row | None = sql.execute(conn, _RUNS.where("r.id = ?", run_id)).fetchone()
    return row


def set_slot_link(conn: sqlite3.Connection, run_id: int, repo: str, link: bytes | None) -> None:
    """Record what a run's slot's `.git` file held when `_run` started (DESIGN §8)."""
    records.update(records.RunSlot).set(git_link=link).where("run_id = ? AND repo = ?", run_id, repo).run(conn)


def finish_ticket_run(
    conn: sqlite3.Connection,
    run_id: int,
    status: RunStatus,
    result_json: str | None,
    *,
    messages: Sequence[tuple[str, str]] = (),
    event: Callable[[int | None], Event | None] | None = None,
    then: Callable[[], object] | None = None,
) -> bool:
    """Close a running worker run, with the messages it reports and its event, as `finish_run` closes any run.

    `messages` are the run's `(kind, body)` messages about its ticket (DESIGN §22), recorded in order. `event` builds
    the `run.ended` event from the id of the last of them, or None if there are none. `then` writes what else the run
    reported, such as its memory (DESIGN §28), in the same transaction. Nothing changes for a run already closed.

    Returns:
        True if this call closed the run.
    """
    with transaction(conn):
        if not _close_run(conn, "runs", run_id, status, result_json):
            return False
        key = sql.execute(conn, sql.select("ticket_key").from_("runs").where("id = ?", run_id)).fetchone()[0]
        last: int | None = None
        for kind, body in messages:
            last = insert_message(
                conn,
                SUBJECT_TICKET,
                str(key),
                source="worker",
                kind=kind,
                channel="run",
                body=body,
                run_id=run_id,
            )
        built = event(last) if event is not None else None
        if built is not None:
            record_event(conn, built)
        if then is not None:
            then()
    return True


def set_tick_report(
    conn: sqlite3.Connection,
    tick_id: int,
    session_id: str | None,
    usage: Usage | None,
    *,
    digest: str | None = None,
    tools: Sequence[ToolUse] = (),
) -> None:
    """Record what the agent runtime reported about a tick's overseer run: its session, cost, and tools (§6, §13).

    The tools are its tool calls rolled up by tool, in place of any recorded before. `digest` names the definitions
    snapshot the overseer loaded, recorded only when the runtime reported something.
    """
    _set_report(conn, "ticks", tick_id, session_id, usage, digest=digest, tools=tools)


def run_tools(conn: sqlite3.Connection, table: RunTable | Literal["ticks"], run_id: int) -> list[records.RunTool]:
    """What a run's tool calls put into its context, by tool (§13): a tick's overseer when `table` is `ticks`.

    Returns:
        A row per tool it called, the most characters returned first; empty for a run that printed no tool call.
    """
    return (
        records.select(records.RunTool)
        .where("run_table = ? AND run_id = ?", table, run_id)
        .order_by("result_chars DESC, tool")
        .all(conn)
    )


#: The assignments of a row's cost and token columns, a `?` for each of what `_spent` returns, in its order.
_SPENT: LiteralString = (
    "cost_usd = ?, tokens_input = ?, tokens_output = ?, tokens_reasoning = ?, tokens_cache_read = ?, "
    "tokens_cache_write = ?, tokens_peak_context = ?, tokens_first_call = ?, tokens_first_cache_write = ?, "
    "tokens_first_cache_read = ?"
)


def set_run_progress(
    conn: sqlite3.Connection,
    run_id: int,
    session_id: str,
    *,
    usage: Usage | None = None,
    did: tuple[str, str] | None = None,
) -> None:
    """Record what a running run's worker has reported so far (DESIGN §8). Nothing changes for a run not running.

    Its session always; what it has spent so far when `usage` is given; and its latest tool call when `did` is, as
    `(tool, what it did)`, stamped now.
    """
    running = records.update(records.Run).where("id = ? AND status = 'running'", run_id)
    with transaction(conn):
        running.set(session_id=session_id).run(conn)
        if usage is not None:
            running.set_to(_SPENT, *_spent(usage)).run(conn)
        if did is not None:
            tool, what = did
            running.set(activity_tool=tool, activity=what, activity_at=now()).run(conn)


def set_progress(
    conn: sqlite3.Connection,
    table: ProgressTable,
    row_id: int,
    session_id: str,
    *,
    usage: Usage | None = None,
    did: tuple[str, str] | None = None,
) -> None:
    """Record what a running tick's overseer, or a chore, task, or review run's agent, has reported so far (§6, §19).

    Its session always, what it has spent so far when `usage` is given, and a tick's overseer's latest tool call when
    `did` is, as `(tool, what it did)`, stamped now; only a tick keeps one. Nothing changes for one not running.
    """
    running = records.update(records.of_table(table)).where("id = ? AND status = 'running'", row_id)
    with transaction(conn):
        running.set(session_id=session_id).run(conn)
        if usage is not None:
            running.set_to(_SPENT, *_spent(usage)).run(conn)
        if did is not None:
            tool, what = did
            running.set(activity_tool=tool, activity=what, activity_at=now()).run(conn)


def usage_of(row: sqlite3.Row | records.Row) -> Usage | None:
    """What a run, chore run, review run, or tick row says its agent cost, or None when the runtime reported nothing.

    Returns:
        The row's cost and token counts, a missing count read as 0 and a missing peak context or first call as
        unknown, or None when it has no cost.
    """
    values = records.columns(row)
    if values["cost_usd"] is None:
        return None
    return Usage(
        cost_usd=float(values["cost_usd"]),
        input=int(values["tokens_input"] or 0),
        output=int(values["tokens_output"] or 0),
        reasoning=int(values["tokens_reasoning"] or 0),
        cache_read=int(values["tokens_cache_read"] or 0),
        cache_write=int(values["tokens_cache_write"] or 0),
        peak_context=int(values["tokens_peak_context"]) if values["tokens_peak_context"] is not None else None,
        first_call=int(values["tokens_first_call"]) if values["tokens_first_call"] is not None else None,
        first_cache_write=int(values["tokens_first_cache_write"])
        if values["tokens_first_cache_write"] is not None
        else None,
        first_cache_read=int(values["tokens_first_cache_read"])
        if values["tokens_first_cache_read"] is not None
        else None,
    )


def spent_on[R: records.Row](update: records.Update[R], usage: Usage | None) -> records.Update[R]:
    """`update`, also setting a row's cost and token columns to what `usage` says, each NULL when it is None.

    Returns:
        The update, with those columns set.
    """
    return update.set_to(_SPENT, *(_spent(usage) if usage is not None else (None,) * 10))


def _set_report(
    conn: sqlite3.Connection,
    table: RunTable | Literal["ticks"],
    row_id: int,
    session_id: str | None,
    usage: Usage | None,
    *,
    digest: str | None,
    tools: Sequence[ToolUse],
) -> None:
    # Only with a report: a template of the operator's that prints plain text may not load the snapshot at all.
    loaded = digest if session_id is not None or usage is not None else None
    report = (
        spent_on(records.update(records.of_table(table)), usage)
        .set(session_id=session_id)
        .set(definitions_digest=loaded)
        .where("id = ?", row_id)
    )
    with transaction(conn):
        report.run(conn)
        records.delete(records.RunTool).where("run_table = ? AND run_id = ?", table, row_id).run(conn)
        records.insert_rows(records.RunTool, ("run_table", "run_id", "tool", "calls", "errors", "result_chars")).many(
            conn,
            [(table, row_id, t.tool, t.calls, t.errors, t.result_chars) for t in tools],
        )


def _spent(usage: Usage) -> tuple[float, int, int, int, int, int, int | None, int | None, int | None, int | None]:
    """`usage` as the cost and token columns hold it, in the order `_SPENT` sets them.

    Returns:
        The cost, each kind of token, the peak context, and the first call's tokens, cache write, and cache read.
    """
    return (
        usage.cost_usd,
        usage.input,
        usage.output,
        usage.reasoning,
        usage.cache_read,
        usage.cache_write,
        usage.peak_context,
        usage.first_call,
        usage.first_cache_write,
        usage.first_cache_read,
    )


def spent_since(conn: sqlite3.Connection, since: str) -> float | None:
    """What every agent run that started at or after `since` cost; None when none of them reported one (§13).

    Worker runs, chore runs, review runs, task runs, and each tick's overseer: every table an agent run records on.

    Returns:
        The total cost in US dollars, or None when no such run reported one.
    """
    tables: tuple[RunTable | Literal["ticks"], ...] = (*RUN_TABLES, "ticks")
    costs = [sql.select("SUM(cost_usd)").from_(table).where("started_at >= ?", since) for table in tables]
    row = sql.execute(conn, sql.select("({}), ({}), ({}), ({}), ({})", *costs)).fetchone()
    parts = [float(v) for v in row if v is not None]
    return sum(parts) if parts else None


def spent_ever(conn: sqlite3.Connection) -> float | None:
    """What every agent run the journal holds cost, whenever it started; None when none of them reported one (§13).

    Returns:
        The total cost in US dollars, or None when no run reported one.
    """
    # Every recorded time sorts after the empty string.
    return spent_since(conn, "")


def recent_runs(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Return the `limit` runs that ended most recently, the one that ended last first."""
    query = _RUNS.where("r.status != 'running'").order_by("r.ended_at DESC, r.id DESC").limit(limit)
    return sql.execute(conn, query).fetchall()


def ended_run_results(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return every ended run's end and stored result, for counting what ended and the PRs results name."""
    return sql.execute(conn, sql.select("ended_at, result_json").from_("runs").where("ended_at IS NOT NULL")).fetchall()


def ended_runs_of(conn: sqlite3.Connection, key: str, limit: int, *, skip_kind: str | None = None) -> list[sqlite3.Row]:
    """Return a ticket's latest `limit` ended runs since any forget, oldest first: id, kind, status, and end.

    Runs of `skip_kind`, if given, are left out, and do not count toward `limit`.
    """
    query = (
        sql.select("r.id, r.kind, r.status, r.ended_at")
        .from_("runs r")
        .left_join("tickets t ON t.key = r.ticket_key")
        .where("r.ticket_key = ? AND r.status != 'running' AND r.id > coalesce(t.forgotten_run_id, 0)", key)
    )
    if skip_kind is not None:
        query = query.where("r.kind != ?", skip_kind)
    rows = sql.execute(conn, query.order_by("r.id DESC").limit(limit)).fetchall()
    return rows[::-1]


def latest_runs(conn: sqlite3.Connection) -> dict[str, records.Run]:
    """Return each ticket's most recent run, by ticket key: none for a ticket forgotten since its latest run."""
    newest = sql.select("max(id)").from_("runs").where("ticket_key = r.ticket_key")
    query = (
        records.select(records.Run, "r")
        .left_join("tickets t ON t.key = r.ticket_key")
        .where("r.id = ({}) AND r.id > coalesce(t.forgotten_run_id, 0)", newest)
    )
    return {r.ticket_key: r for r in query.all(conn)}


def record_decision(
    conn: sqlite3.Connection,
    tick_id: int,
    key: str | None,
    action: str,
    rationale: str,
    *,
    repo: str | None = None,
    chore: str | None = None,
    pr: str | None = None,
    decider: Decider = Decider.OVERSEER,
    kept: bool = False,
    item: int | None = None,
    kind: RunKind | None = None,
) -> int:
    """Insert a decision for `tick_id` and return its id.

    `repo` is set for an item about a repository, `chore` for a decision about a chore, which has no ticket key, and
    `pr` for a decision about a PR the loop reviews, which has a ticket key only for one of the loop's own PRs.
    `decider` says who made it: the overseer, through one of its verbs, or the harness on its own (DESIGN §37). `kept`
    marks an attention item the overseer keeps, held until what it names ends it, and `item` is the journal number of
    what it names, if it names one (`core.kept_items`). `kind` is the kind of run a refused dispatch asked for.

    Returns:
        The new decision's id.
    """
    decision = records.insert(
        records.Decision,
        tick_id=tick_id,
        ticket_key=key,
        action=action,
        rationale=rationale,
        repo=repo,
        chore=chore,
        pr=pr,
        decider=decider,
        kept=kept,
        item=item,
        kind=kind,
    )
    return rowid(decision.run(conn))


def record_persona_text(conn: sqlite3.Connection, digest: str | None, text: str | None) -> None:
    """Keep the text of a persona a run was given, once per digest, unless it is kept already (DESIGN §31).

    A text is its digest's, so the first run that carries a digest records it and no later one changes it. Nothing is
    kept when either is None.
    """
    if digest is None or text is None:
        return
    records.insert(records.PersonaText, digest=digest, text=text, recorded_at=now()).or_ignore().run(conn)


def persona_text(conn: sqlite3.Connection, digest: str) -> str | None:
    """Return the text of the persona whose digest is `digest`, as a run was given it, or None if none was kept."""
    found = records.select(records.PersonaText).where("digest = ?", digest).one(conn)
    return found.text if found is not None else None


def has_runs(conn: sqlite3.Connection, key: str) -> bool:
    """Return whether any run was ever dispatched for `key`."""
    query = sql.select("1").from_("runs").where("ticket_key = ?", key).limit(1)
    return sql.execute(conn, query).fetchone() is not None


def decisions_for_tick(conn: sqlite3.Connection, tick_id: int) -> list[records.Decision]:
    """Return a tick's decisions in the order they were recorded."""
    return records.select(records.Decision).where("tick_id = ?", tick_id).order_by("id").all(conn)


def last_tick_decisions(conn: sqlite3.Connection, action: str) -> list[records.Decision]:
    """Return the `action` decisions of the newest `ok` tick that recorded one, in the order they were recorded.

    A tick that did not close `ok` may have stopped partway through recording them.
    """
    # Newest first, so the scan stops at the first tick that has one, each looked up through `decisions_tick`.
    has_one = sql.select("1").from_("decisions d").where("d.tick_id = k.id AND d.action = ?", action)
    newest = (
        sql.select("k.id")
        .from_("ticks k")
        .where("k.status = 'ok' AND EXISTS ({})", has_one)
        .order_by("k.id DESC")
        .limit(1)
    )
    return (
        records.select(records.Decision).where("tick_id = ({}) AND action = ?", newest, action).order_by("id").all(conn)
    )


def decisions_about(conn: sqlite3.Connection, key: str, limit: int) -> list[records.Decision]:
    """Return the latest `limit` decisions about ticket `key`, its units' included, across ticks, newest first."""
    return records.select(records.Decision).where("ticket_key = ?", key).order_by("id DESC").limit(limit).all(conn)


def decisions_about_pr(conn: sqlite3.Connection, url: str, limit: int) -> list[records.Decision]:
    """Return the latest `limit` decisions that name the PR at `url`, across ticks, newest first."""
    return records.select(records.Decision).where("pr = ?", url).order_by("id DESC").limit(limit).all(conn)


def last_decision_of(conn: sqlite3.Connection, key: str) -> str | None:
    """Return the newest decision's action about ticket `key` since it was forgotten, or None if no tick made one.

    The overseer records a decision for every ticket a tick looks at, but a phase only when told to, so this, not
    `tickets.phase`, says whether a tick has seen the ticket.
    """
    query = (
        sql.select("d.action")
        .from_("decisions d")
        .left_join("tickets t ON t.key = d.ticket_key")
        .where("d.ticket_key = ? AND (t.forgotten_at IS NULL OR d.created_at > t.forgotten_at)", key)
        .order_by("d.id DESC")
        .limit(1)
    )
    row = sql.execute(conn, query).fetchone()
    return None if row is None else str(row[0])


def recent_ticks(conn: sqlite3.Connection, limit: int, *, idle: bool = False) -> list[tuple[records.Tick, int]]:
    """Return the latest `limit` ticks, newest first, each with how many decisions it recorded.

    Args:
        conn: The journal.
        limit: How many ticks at most.
        idle: Whether to keep only the live ticks `canopy loop` found idle (DESIGN §6, Idle pacing).
    """
    query = records.select(records.Tick)
    if idle:
        query = query.where("dry_run = 0 AND idle = 1")
    return with_decision_counts(conn, query.order_by("id DESC").limit(limit).all(conn))


def with_decision_counts(conn: sqlite3.Connection, ticks: Iterable[records.Tick]) -> list[tuple[records.Tick, int]]:
    """Pair each of `ticks` with how many decisions it recorded, in one query by `decisions_tick`.

    Returns:
        The ticks, in the order given, each with its count.
    """
    found = list(ticks)
    query = (
        sql.select("tick_id, count(*)")
        .from_("decisions")
        .where("tick_id IN (SELECT value FROM json_each(?))", json.dumps([t.id for t in found]))
        .group_by("tick_id")
    )
    counts = dict(sql.execute(conn, query).fetchall())
    return [(t, int(counts.get(t.id, 0))) for t in found]


def decision_count(conn: sqlite3.Connection, tick_id: int) -> int:
    """Return how many decisions a tick recorded."""
    row = sql.execute(conn, sql.select("count(*)").from_("decisions").where("tick_id = ?", tick_id)).fetchone()
    return int(row[0])


# Conversations (DESIGN §22)

# The kind of subject a ticket is. Messages and start records are keyed by subject, so a new kind adds no table (D075).
SUBJECT_TICKET = "ticket"


def insert_message(
    conn: sqlite3.Connection,
    subject_kind: str,
    subject_id: str,
    *,
    source: str,
    kind: str,
    channel: str,
    body: str,
    run_id: int | None = None,
    answers: int | None = None,
    submission: str | None = None,
    comment: Comment | None = None,
    task_run_id: int | None = None,
) -> int:
    """Record a message and return its id. A worker's names its run: a ticket's in `run_id`, a task's in `task_run_id`.

    A submission already recorded for the subject records nothing new: its message's id is returned instead. So does a
    tracker comment already recorded for the subject.

    Returns:
        The id of the new message, or of the one already recorded for the submission or comment.
    """
    if submission is not None:
        query = (
            sql.select("id")
            .from_("messages")
            .where("subject_kind = ? AND subject_id = ? AND submission = ?", subject_kind, subject_id, submission)
        )
        found = sql.execute(conn, query).fetchone()
        if found is not None:
            return int(found[0])
    if comment is not None:
        recorded = comment_message(conn, subject_kind, subject_id, comment.id)
        if recorded is not None:
            return recorded.id
    message = records.insert(
        records.Message,
        subject_kind=subject_kind,
        subject_id=subject_id,
        at=now(),
        source=source,
        kind=kind,
        channel=channel,
        run_id=run_id,
        body=body,
        answers=answers,
        submission=submission,
        comment_id=comment.id if comment else None,
        author=comment.author if comment else None,
        commented_at=comment.at if comment else None,
        truncated=int(comment.truncated) if comment else 0,
        task_run_id=task_run_id,
    )
    return rowid(message.run(conn))


def comment_message(
    conn: sqlite3.Connection,
    subject_kind: str,
    subject_id: str,
    comment_id: str,
) -> records.Message | None:
    """Return the message a tracker comment was recorded as, or None if it was not (DESIGN §22, §35)."""
    return (
        records.select(records.Message)
        .where("subject_kind = ? AND subject_id = ? AND comment_id = ?", subject_kind, subject_id, comment_id)
        .one(conn)
    )


def get_message(conn: sqlite3.Connection, message_id: int) -> records.Message | None:
    """Return the message with `message_id`, or None."""
    return records.select(records.Message).where("id = ?", message_id).one(conn)


def messages_of(
    conn: sqlite3.Connection,
    subject_kind: str,
    subject_id: str,
    limit: int,
    *,
    after: int = 0,
) -> list[records.Message]:
    """Return a subject's latest `limit` messages newer than message id `after`, oldest first."""
    query = (
        records.select(records.Message)
        .where("subject_kind = ? AND subject_id = ? AND id > ?", subject_kind, subject_id, after)
        .order_by("id DESC")
        .limit(limit)
    )
    return query.all(conn)[::-1]


def run_messages(conn: sqlite3.Connection, run_id: int) -> list[records.Message]:
    """Return the messages a run reported, in order."""
    return records.select(records.Message).where("run_id = ?", run_id).order_by("id").all(conn)


def latest_message_id(conn: sqlite3.Connection, *, source: str | None = None, subject_kind: str | None = None) -> int:
    """Return the id of the newest message, of the newest from `source`, or about a kind of subject; 0 if none."""
    query = sql.select("max(id)").from_("messages")
    if source is not None:
        query = query.where("source = ?", source)
    if subject_kind is not None:
        query = query.where("subject_kind = ?", subject_kind)
    return int(sql.execute(conn, query).fetchone()[0] or 0)


def get_start(conn: sqlite3.Connection, subject_kind: str, subject_id: str) -> records.Start | None:
    """Return a subject's start record, or None if the operator never started it."""
    return (
        records.select(records.Start).where("subject_kind = ? AND subject_id = ?", subject_kind, subject_id).one(conn)
    )


def starts(conn: sqlite3.Connection) -> list[records.Start]:
    """Return every start record, by subject."""
    return records.select(records.Start).order_by("subject_kind, subject_id").all(conn)


def set_start(
    conn: sqlite3.Connection,
    subject_kind: str,
    subject_id: str,
    *,
    status: StartStatus,
    channel: str,
) -> None:
    """Mark a subject started or stopped, creating its record on its first start. Call inside a transaction."""
    ts = now()
    match status:
        case StartStatus.STARTED:
            start = records.insert(
                records.Start,
                subject_kind=subject_kind,
                subject_id=subject_id,
                status=sql.frag("'started'"),
                started_at=ts,
                channel=channel,
            ).on_conflict(
                "(subject_kind, subject_id) DO UPDATE SET status = 'started', started_at = excluded.started_at, "
                "stopped_at = NULL, channel = excluded.channel",
            )
            start.run(conn)
        case StartStatus.STOPPED:
            stop = (
                records.update(records.Start)
                .set_to("status = 'stopped'")
                .set(stopped_at=ts, channel=channel)
                .where("subject_kind = ? AND subject_id = ?", subject_kind, subject_id)
            )
            stop.run(conn)
        case _:
            assert_never(status)


def running_run_of(conn: sqlite3.Connection, key: str) -> records.Run | None:
    """Return the run working `key` now, if one is."""
    return (
        records.select(records.Run)
        .where("ticket_key = ? AND status = 'running'", key)
        .order_by("id DESC")
        .limit(1)
        .one(conn)
    )


def runs_of(conn: sqlite3.Connection, key: str, limit: int | None) -> list[sqlite3.Row]:
    """Return a ticket's latest `limit` runs, newest first; with None, every one."""
    # SQLite reads a negative LIMIT as none.
    query = _RUNS.where("r.ticket_key = ?", key).order_by("r.id DESC").limit(-1 if limit is None else limit)
    return sql.execute(conn, query).fetchall()


def ticket_cost(conn: sqlite3.Connection, key: str) -> sqlite3.Row:
    """Return what a ticket's runs and the review runs naming it cost, however long ago they ran (§13).

    The row has `runs` and `reviews`, how many of each; `priced`, how many of them reported a cost; and `cost_usd`,
    what those cost, NULL when none did. Not the overseer's: a tick's cost is the whole workspace's.
    """

    def spent(table: RunTable) -> sql.Select:
        return (
            sql.select("count(*) AS n, count(cost_usd) AS priced, sum(cost_usd) AS cost")
            .from_(table)
            .where("ticket_key = ?", key)
        )

    query = sql.select(
        "r.n AS runs, v.n AS reviews, r.priced + v.priced AS priced, "
        "CASE WHEN r.priced + v.priced > 0 THEN coalesce(r.cost, 0) + coalesce(v.cost, 0) END AS cost_usd",
    ).from_("({}) r, ({}) v", spent("runs"), spent("review_runs"))
    row: sqlite3.Row = sql.execute(conn, query).fetchone()
    return row


def recent_tickets(conn: sqlite3.Connection, limit: int, *, key: str | None = None) -> list[sqlite3.Row]:
    """Return the `limit` tickets with the most recent activity, most recently active first, each row with `active_at`.

    Activity is a message, a run starting or ending, a start or stop, or a change to the ticket (`changed_at`), not a
    tick that only sees it. Every one of those times is the journal's own format, so the newest is the greatest
    string. With `key`, only that ticket.

    Only the candidates `candidates` finds are weighed, so the read costs what `limit` does, not what the
    journal's history does: the web UI's event stream reads the list on every commit (DESIGN §22).
    """
    if limit < 1:
        return []
    with read_snapshot(conn):
        keys = [key] if key is not None else candidates(conn, _TICKET_ACTIVITY, limit)
        return _weighed_tickets(conn, json.dumps(keys), limit)


def _weighed_tickets(conn: sqlite3.Connection, keys: str, limit: int) -> list[sqlite3.Row]:
    query = (
        sql.select(
            "t.*, max("
            "  t.changed_at,"
            "  coalesce((SELECT max(m.at) FROM messages m WHERE m.subject_kind = ? AND m.subject_id = t.key), ''),"
            "  coalesce((SELECT max(coalesce(r.ended_at, r.started_at)) FROM runs r WHERE r.ticket_key = t.key), ''),"
            "  coalesce((SELECT coalesce(s.stopped_at, s.started_at) FROM starts s"
            "    WHERE s.subject_kind = ? AND s.subject_id = t.key), '')"
            ") AS active_at",
            SUBJECT_TICKET,
            SUBJECT_TICKET,
        )
        .from_("tickets t")
        .where("t.key IN (SELECT value FROM json_each(?))", keys)
        .order_by("active_at DESC, t.key")
        .limit(limit)
    )
    return sql.execute(conn, query).fetchall()


# Each source of a ticket's activity as `recent_tickets` weighs it: a ticket key and a time, newest first, read in
# order from an index (migration 0022). A run that ended has its end time (`finish_run`), so the ended runs and the
# running ones between them give each run's time as `recent_tickets` takes it. Messages and start records may name a
# ticket the journal has no row for, which the join leaves out, so one never takes a real ticket's place; CROSS JOIN
# keeps SQLite reading the start records in order from their index, rather than sorting every one.
_TICKET_ACTIVITY = (
    sql.select("key, changed_at").from_("tickets").order_by("changed_at DESC"),
    sql.select("m.subject_id, m.at")
    .from_("messages m")
    .join("tickets t ON t.key = m.subject_id")
    .where("m.subject_kind = 'ticket'")
    .order_by("m.at DESC"),
    sql.select("ticket_key, ended_at").from_("runs").where("ended_at IS NOT NULL").order_by("ended_at DESC"),
    sql.select("ticket_key, started_at").from_("runs").where("status = 'running'").order_by("started_at DESC"),
    sql.select("s.subject_id, coalesce(s.stopped_at, s.started_at) AS at")
    .from_("starts s CROSS JOIN tickets t ON t.key = s.subject_id")
    .where("s.subject_kind = 'ticket'")
    .order_by("at DESC"),
)


def candidates(conn: sqlite3.Connection, sources: Iterable[sql.Select], limit: int) -> list[str]:
    """The keys that may be among the `limit` with the most recent activity: each source's newest `limit`.

    Each source is a query of a key and a time, newest first, read in order from an index. A key's activity is its
    newest time in any source. Every key newer than it in that source is newer overall too, so a key among the
    `limit` newest overall is among the `limit` newest of that source. Keys tied with the last of a source's are read
    as well, so a tie never decides which one is left out.

    Returns:
        The candidates' keys, each once.
    """
    found: dict[str, None] = {}
    for source in sources:
        found.update(dict.fromkeys(_newest(conn, source, limit)))
    return list(found)


@contextmanager
def read_snapshot(conn: sqlite3.Connection) -> Generator[None]:
    """Every read in the block sees one snapshot of the journal: a deferred transaction, which writes nothing.

    The journal's connections are autocommit, so without it each query reads its own snapshot, and a commit between two
    reads could leave a row in one and out of the other: here, a key its new activity had just moved among the newest
    candidates. Inside a transaction already, as the event stream's reads are, the block reads in that one.
    """
    if conn.in_transaction:
        yield
        return
    sql.execute(conn, sql.frag("BEGIN"))
    try:
        yield
    finally:
        sql.execute(conn, sql.frag("COMMIT"))


def _newest(conn: sqlite3.Connection, source: sql.Select, limit: int) -> list[str]:
    seen: dict[str, None] = {}
    cutoff: str | None = None
    # Closed when the walk stops early, so the statement does not hold its read open in autocommit.
    with closing(sql.execute(conn, source)) as rows:
        for key, at in rows:
            if cutoff is not None and at < cutoff:
                break
            if key not in seen:
                seen[str(key)] = None
                if len(seen) == limit:
                    cutoff = at
    return list(seen)


def latest_message_of(conn: sqlite3.Connection, subject_kind: str, subject_id: str) -> int | None:
    """Return the id of a subject's newest message, or None if it has none."""
    query = (
        sql.select("max(id)").from_("messages").where("subject_kind = ? AND subject_id = ?", subject_kind, subject_id)
    )
    row = sql.execute(conn, query).fetchone()
    return None if row[0] is None else int(row[0])


def set_seen(conn: sqlite3.Connection, kind: SeenKind, subjects: Iterable[str], *, channel: str) -> list[str]:
    """Record that the operator saw each of `subjects` of `kind` now, through `channel` (DESIGN §22).

    One seen before keeps the time and channel it was first seen at.

    Returns:
        The subjects not seen before, in the order given.
    """
    at = now()
    new: list[str] = []
    for subject in subjects:
        mark = records.insert(records.Seen, kind=kind, subject=subject, at=at, channel=channel)
        if mark.on_conflict("(kind, subject) DO NOTHING").run(conn).rowcount > 0:
            new.append(subject)
    return new


def seen_among(conn: sqlite3.Connection, kind: SeenKind, subjects: Iterable[str]) -> frozenset[str]:
    """Return which of `subjects` of `kind` the operator has seen: a read by key, however many they have seen."""
    query = sql.select("subject").from_("seen").where("kind = ?", kind).where_in("subject", list(subjects))
    return frozenset(str(r[0]) for r in sql.execute(conn, query))


def forget_ticket(conn: sqlite3.Connection, key: str, *, channel: str, branch: str | None, prs: Iterable[str]) -> None:
    """Clear what the journal knows of a ticket's branch, PRs, and phases, and mark where its loop view begins.

    Call inside a transaction. Runs, messages, the start record, and the cursors stay (DESIGN §22). The forget is
    recorded with the `branch` and `prs` it dropped, beside every earlier one. A waiting or approved plan is
    superseded, so a ticket planned under `policy.plan = "approve"` is planned again; its file stays. So is a feedback
    plan (DESIGN §32): its PRs are forgotten with the rest.
    """
    ts = now()
    last_run = sql.select("max(id)").from_("runs").where("ticket_key = ?", key)
    last_message = (
        sql.select("max(id)").from_("messages").where("subject_kind = ? AND subject_id = ?", SUBJECT_TICKET, key)
    )
    forget = (
        records.update(records.Ticket)
        .set_to("branch = NULL, phase = NULL, needs_human_since = NULL, done = 0")
        .set(forgotten_at=ts, changed_at=ts)
        .set(forgotten_run_id=sql.frag("({})", last_run), forgotten_message_id=sql.frag("({})", last_message))
        .where("key = ?", key)
    )
    forget.run(conn)
    forgotten = (
        sql.select(
            "key, forgotten_at, ?, forgotten_run_id, forgotten_message_id, ?, ?",
            channel,
            branch,
            json.dumps(list(prs)),
        )
        .from_("tickets")
        .where("key = ?", key)
    )
    columns = ("ticket_key", "at", "channel", "run_id", "message_id", "branch", "prs")
    records.insert_from(records.Forget, columns, forgotten).run(conn)
    records.delete(records.TicketUnit).where("ticket_key = ?", key).run(conn)
    (
        records.update(records.Plan)
        .set(status=PlanStatus.SUPERSEDED)
        .where("ticket_key = ? AND status != ?", key, PlanStatus.SUPERSEDED)
        .run(conn)
    )
    (
        records.update(records.FeedbackPlan)
        .set(status=PlanStatus.SUPERSEDED)
        .where("ticket_key = ? AND status != ?", key, PlanStatus.SUPERSEDED)
        .run(conn)
    )


def forgets_of(conn: sqlite3.Connection, key: str) -> list[records.Forget]:
    """Return each time the operator forgot ticket `key`'s work, oldest first; the last is the one its row holds."""
    return records.select(records.Forget).where("ticket_key = ?", key).order_by("id").all(conn)


def worked_since_forget(conn: sqlite3.Connection, ticket: records.Ticket) -> bool:
    """Return whether anything has happened to a forgotten ticket since its latest forget, or True if it was never one.

    Work is a run, a message, a branch, a unit, or the done mark: what another forget would have something to drop.
    """
    if ticket.forgotten_at is None or ticket.branch is not None or ticket.done:
        return True
    later_runs = (
        sql.select("1").from_("runs").where("ticket_key = ? AND id > ?", ticket.key, ticket.forgotten_run_id or 0)
    )
    later_messages = (
        sql.select("1")
        .from_("messages")
        .where(
            "subject_kind = ? AND subject_id = ? AND id > ?",
            SUBJECT_TICKET,
            ticket.key,
            ticket.forgotten_message_id or 0,
        )
    )
    any_units = sql.select("1").from_("ticket_units").where("ticket_key = ?", ticket.key)
    work = sql.select("EXISTS ({}) OR EXISTS ({}) OR EXISTS ({})", later_runs, later_messages, any_units)
    row = sql.execute(conn, work).fetchone()
    return bool(row[0])


def forgotten_message_id(conn: sqlite3.Connection, key: str) -> int:
    """Return the newest message of `key` the operator forgot with its work, or 0: the loop reads only later ones."""
    row = sql.execute(conn, sql.select("forgotten_message_id").from_("tickets").where("key = ?", key)).fetchone()
    return int(row[0] or 0) if row is not None else 0
