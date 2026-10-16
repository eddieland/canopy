"""The SQLite journal: connection setup, migrations, and the queries the loop makes.

The journal holds facts about the loop only (DESIGN §4, §11). Nothing here is read back as a fact about the world.
Connections run in autocommit mode; anything that must be atomic opens its own transaction.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from canopy.core import agent_output, records
from canopy.core.vocab import PoolKind
from canopy.infra import procs

if TYPE_CHECKING:
    from canopy.core.agent_output import Usage
    from canopy.core.vocab import AnyRunStatus, RunStatus

DB_FILE_NAME = "canopy.db"
# How long a connection waits for another to release the write lock before its write fails as `database is locked`.
BUSY_SECONDS = 10.0
_MIGRATION_RE = re.compile(r"(\d{4})_([a-z0-9_]+)\.sql")
# The rationale the overseer gives a `done` decision for a ticket the tracker reports closed (DESIGN §7).
CLOSED_RATIONALE = "closed"

# `canopy ticket set --cursor NAME=ID` names, and the column each one updates. The comment cursor is the ticket's; the
# review and ci cursors are a unit's, since each unit has its own PR (DESIGN §18). The message cursor is a private
# ticket's, over journal message ids (DESIGN §22).
TICKET_CURSORS: Mapping[str, str] = {"comment": "last_comment_id", "message": "last_message_id"}
UNIT_CURSORS: Mapping[str, str] = {"review": "last_review_id", "ci": "last_ci_run_id"}
CURSOR_COLUMNS: Mapping[str, str] = {**TICKET_CURSORS, **UNIT_CURSORS}
# The tables of detached runs (DESIGN §6): workers' and splits', chores', and reviews'. Each has the same lifecycle,
# written once below over a table from this closed set: claimed by its process's pid, its agent's pid recorded, its
# report, and its close. A table name in SQL comes from here, never from input.
type RunTable = Literal["runs", "chore_runs", "review_runs"]
RUN_TABLES: tuple[RunTable, ...] = ("runs", "chore_runs", "review_runs")
# What each run table's rows are called in a message, and the column it keeps its agent's pid in: the leader of the
# process group the run's own process starts, which outlives that process if it dies.
RUN_NOUNS: Mapping[RunTable, str] = {"runs": "run", "chore_runs": "chore run", "review_runs": "review run"}
AGENT_PID: Mapping[RunTable, str] = {"runs": "worker_pid", "chore_runs": "agent_pid", "review_runs": "agent_pid"}


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
    """A tracker comment as a mirrored message records it (DESIGN §22): its id, author's account id, and time."""

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
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
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
    """Run the block in a `BEGIN IMMEDIATE` transaction; roll back if it raises."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


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
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone()
        applied = {int(r[0]) for r in conn.execute("SELECT version FROM schema_migrations")} if has_table else set()
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
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (?, ?)",
                (m.version, m.name),
            )
            applied_now.append(m.version)
    return applied_now


def _check_no_live_runs(conn: sqlite3.Connection) -> None:
    """Refuse to migrate while a `_run` is alive: it was started by an earlier canopy, which wrote the old schema.

    A run whose `_run` is gone does not count; the next tick's reconcile closes it (DESIGN §6).

    Raises:
        MigrationError: A run, chore run, or review run is `running` and its process is alive.
    """
    live: list[str] = []
    # Every table of detached runs: each process writes its own row when it ends.
    for table in RUN_TABLES:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
        if not exists:
            continue
        sql = f"SELECT id, pid, log_path FROM {table} WHERE status = 'running' ORDER BY id"  # noqa: S608
        rows = conn.execute(sql)
        live += [f"{RUN_NOUNS[table]} {r['id']}" for r in rows if procs.running(Path(r["log_path"]), r["pid"])]
    if live:
        runs = f"{live[0]} is" if len(live) == 1 else f"{', '.join(live)} are"
        raise MigrationError(
            f"this canopy changes the journal, but {runs} still working for the canopy before it and would fail "
            "writing the old journal. Run canopy again once they finish."
        )


def record_event(conn: sqlite3.Connection, event: Event) -> int:
    """Add `event` to the outbox and return its id. Inside a transaction, it commits or rolls back with the fact.

    Returns:
        The new `notify_events` row's id.
    """
    cur = conn.execute(
        "INSERT INTO notify_events (grp, kind, at, fields) VALUES (?, ?, ?, ?)",
        (event.group, event.kind, now(), json.dumps(dict(event.fields))),
    )
    return _rowid(cur)


def _rowid(cur: sqlite3.Cursor) -> int:
    if cur.lastrowid is None:
        raise sqlite3.DatabaseError("INSERT returned no row id")
    return cur.lastrowid


# Ticks


def start_tick(conn: sqlite3.Connection, *, dry_run: bool) -> int:
    """Insert a `running` tick row and return its id.

    Returns:
        The new tick's id.
    """
    cur = conn.execute("INSERT INTO ticks (started_at, dry_run) VALUES (?, ?)", (now(), int(dry_run)))
    return _rowid(cur)


def finish_tick(conn: sqlite3.Connection, tick_id: int, status: str, summary: str) -> None:
    """Close a tick with its final status and summary."""
    conn.execute(
        "UPDATE ticks SET ended_at = ?, status = ?, summary = ? WHERE id = ?",
        (now(), status, summary, tick_id),
    )


def set_tick_read(conn: sqlite3.Connection, tick_id: int) -> None:
    """Record what a tick has read up to: the newest message, and the time (§6, §22).

    Every message up to it was there to see, and every run that started or ended before it.
    """
    conn.execute(
        "UPDATE ticks SET message_id = (SELECT coalesce(max(id), 0) FROM messages), read_at = ? WHERE id = ?",
        (now(), tick_id),
    )


def set_tick_loop(conn: sqlite3.Connection, tick_id: int, *, idle: bool, woken_by: str) -> None:
    """Record what the loop knew about a tick it ran: whether it was idle, and what ended the wait before it (§6)."""
    conn.execute("UPDATE ticks SET idle = ?, woken_by = ? WHERE id = ?", (int(idle), woken_by, tick_id))


def set_tick_query(conn: sqlite3.Connection, tick_id: int, *, due: bool) -> None:
    """Record whether a tick's state block told the overseer to run the tracker query (§7, Spacing the query)."""
    conn.execute("UPDATE ticks SET query_due = ? WHERE id = ?", (int(due), tick_id))


def last_query_at(conn: sqlite3.Connection) -> str | None:
    """When the newest live `ok` tick that ran the tracker query started (§7, Spacing the query).

    A tick from before `query_due` was recorded ran it. A dry run, and a tick that did not close `ok`, are not counted:
    one that skipped or failed may not have read the query to the end.

    Returns:
        That tick's `started_at`, or None if no tick has run the query.
    """
    row = conn.execute(
        "SELECT max(started_at) FROM ticks WHERE status = 'ok' AND dry_run = 0 AND coalesce(query_due, 1) = 1"
    ).fetchone()
    return None if row is None or row[0] is None else str(row[0])


def previous_tick(conn: sqlite3.Connection, tick_id: int) -> sqlite3.Row | None:
    """Return the tick before `tick_id`, whatever its status, or None if it is the first."""
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM ticks WHERE id < ? ORDER BY id DESC LIMIT 1", (tick_id,)
    ).fetchone()
    return row


def runs_moved_after(conn: sqlite3.Connection, since: str) -> bool:
    """Whether any run, chore run, or review run started or ended after `since`, a time the journal wrote (§6).

    Returns:
        True if at least one did.
    """
    return any(
        conn.execute(
            f"SELECT 1 FROM {table} WHERE started_at > ? OR ended_at > ? LIMIT 1",  # noqa: S608
            (since, since),
        ).fetchone()
        for table in RUN_TABLES
    )


def runs_ended_after(conn: sqlite3.Connection, since: str) -> bool:
    """Whether any run, chore run, or review run ended after `since`, a time the journal wrote (§6).

    Returns:
        True if at least one did.
    """
    return any(
        conn.execute(f"SELECT 1 FROM {table} WHERE ended_at > ? LIMIT 1", (since,)).fetchone()  # noqa: S608
        for table in RUN_TABLES
    )


def starts_moved_after(conn: sqlite3.Connection, since: str) -> bool:
    """Whether the operator started or stopped a subject after `since`, a time the journal wrote (§6, §22).

    Returns:
        True if a start record's latest start or stop is newer.
    """
    row = conn.execute("SELECT 1 FROM starts WHERE started_at > ? OR stopped_at > ? LIMIT 1", (since, since))
    return row.fetchone() is not None


def granted_after(conn: sqlite3.Connection, since: str) -> bool:
    """Whether the operator granted a ticket's attempts or a PR's reviews after `since`, a time the journal wrote (§6).

    Returns:
        True if at least one grant is newer.
    """
    return any(
        conn.execute(f"SELECT 1 FROM {table} WHERE granted_at > ? LIMIT 1", (since,)).fetchone()  # noqa: S608
        for table in ("attempt_grants", "review_grants")
    )


def phases(conn: sqlite3.Connection) -> dict[tuple[str, str | None], str | None]:
    """Every ticket's and unit's recorded phase, to tell which a tick changed (§6, churn).

    Returns:
        The phase by ticket key and repository: None for the ticket's own, the unit's repository for a unit's.
    """
    found: dict[tuple[str, str | None], str | None] = {}
    for key, phase in conn.execute("SELECT key, phase FROM tickets"):
        found[str(key), None] = None if phase is None else str(phase)
    for key, repo, phase in conn.execute("SELECT ticket_key, repo, phase FROM ticket_units"):
        found[str(key), str(repo)] = None if phase is None else str(phase)
    return found


def tickets_snapshot(conn: sqlite3.Connection) -> frozenset[tuple[object, ...]]:
    """Every ticket's and unit's phase, branch, cursors, and done flag, to tell whether a tick changed any (§6).

    Returns:
        One tuple per ticket and per unit. Two snapshots are equal when nothing in them changed.
    """
    tickets = conn.execute(
        "SELECT 'ticket', key, phase, branch, last_comment_id, last_message_id, last_mirrored_id, done FROM tickets"
    )
    units = conn.execute(
        "SELECT 'unit', ticket_key, repo, branch, pr_url, phase, last_review_id, last_ci_run_id FROM ticket_units"
    )
    return frozenset(tuple(r) for rows in (tickets, units) for r in rows)


def acknowledged_message_id(conn: sqlite3.Connection) -> int | None:
    """The newest message the latest `ok` tick read, or None before the first `ok` tick that recorded one (§22).

    Returns:
        That message's id, or None.
    """
    row = conn.execute("SELECT message_id FROM ticks WHERE status = 'ok' ORDER BY id DESC LIMIT 1").fetchone()
    return None if row is None or row[0] is None else int(row[0])


def abandon_unfinished_ticks(conn: sqlite3.Connection) -> list[int]:
    """Close ticks left `running` by a tick process that died. Call only while holding the tick lock.

    Returns:
        The ids of the ticks marked `abandoned`.
    """
    ids = [int(r[0]) for r in conn.execute("SELECT id FROM ticks WHERE status = 'running'")]
    conn.executemany(
        "UPDATE ticks SET ended_at = ?, status = 'abandoned', summary = 'the tick process exited without finishing' "
        "WHERE id = ?",
        [(now(), i) for i in ids],
    )
    return ids


def get_tick(conn: sqlite3.Connection, tick_id: int) -> sqlite3.Row | None:
    """Return the tick row with `tick_id`, or None."""
    row: sqlite3.Row | None = conn.execute("SELECT * FROM ticks WHERE id = ?", (tick_id,)).fetchone()
    return row


def last_tick(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Return the most recent tick row, or None."""
    row: sqlite3.Row | None = conn.execute("SELECT * FROM ticks ORDER BY id DESC LIMIT 1").fetchone()
    return row


# Tickets


def touch_ticket(conn: sqlite3.Connection, key: str, repo: str) -> None:
    """Record that `key` was seen now, creating its row on first sight."""
    ts = now()
    conn.execute(
        "INSERT INTO tickets (key, repo, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (key) DO UPDATE SET last_seen_at = excluded.last_seen_at",
        (key, repo, ts, ts),
    )


def set_ticket(
    conn: sqlite3.Connection,
    key: str,
    repo: str,
    *,
    phase: str | None = None,
    cursors: Mapping[str, str] | None = None,
    done: bool = False,
    title: str | None = None,
) -> None:
    """Record a ticket's own phase, its comment cursor, its done flag, or its title in one transaction."""
    with transaction(conn):
        touch_ticket(conn, key, repo)
        if phase is not None:
            conn.execute("UPDATE tickets SET phase = ? WHERE key = ?", (phase, key))
        if title is not None:
            conn.execute("UPDATE tickets SET title = ? WHERE key = ?", (title, key))
        for name, value in (cursors or {}).items():
            # The column name comes from a fixed mapping, never from input.
            sql = f"UPDATE tickets SET {TICKET_CURSORS[name]} = ? WHERE key = ?"  # noqa: S608
            conn.execute(sql, (value, key))
        if done:
            conn.execute("UPDATE tickets SET done = 1 WHERE key = ?", (key,))


def _ensure_unit(conn: sqlite3.Connection, key: str, unit: str) -> None:
    """Create `key`'s unit in repository `unit` if it has none. Call inside a transaction."""
    conn.execute(
        "INSERT INTO ticket_units (ticket_key, repo) VALUES (?, ?) ON CONFLICT (ticket_key, repo) DO NOTHING",
        (key, unit),
    )


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
        where = "WHERE ticket_key = ? AND repo = ?"
        if phase is not None:
            conn.execute(f"UPDATE ticket_units SET phase = ? {where}", (phase, key, unit))  # noqa: S608
        for name, value in (cursors or {}).items():
            # The column name comes from a fixed mapping, never from input.
            conn.execute(f"UPDATE ticket_units SET {UNIT_CURSORS[name]} = ? {where}", (value, key, unit))  # noqa: S608
        if pr_url is not None:
            conn.execute(f"UPDATE ticket_units SET pr_url = ? {where}", (pr_url, key, unit))  # noqa: S608


def units(conn: sqlite3.Connection, key: str) -> list[sqlite3.Row]:
    """Return `key`'s units, by repository."""
    return conn.execute("SELECT * FROM ticket_units WHERE ticket_key = ? ORDER BY repo", (key,)).fetchall()


def all_units(conn: sqlite3.Connection) -> dict[str, list[sqlite3.Row]]:
    """Return every ticket's units, by ticket key, each list by repository."""
    found: dict[str, list[sqlite3.Row]] = {}
    for row in conn.execute("SELECT * FROM ticket_units ORDER BY ticket_key, repo"):
        found.setdefault(str(row["ticket_key"]), []).append(row)
    return found


def get_ticket(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    """Return the ticket row for `key`, or None."""
    row: sqlite3.Row | None = conn.execute("SELECT * FROM tickets WHERE key = ?", (key,)).fetchone()
    return row


def open_tickets(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return the tickets not marked done, by key."""
    return conn.execute("SELECT * FROM tickets WHERE done = 0 ORDER BY key").fetchall()


def recently_done(conn: sqlite3.Connection, since: str) -> list[sqlite3.Row]:
    """Return the tickets marked done whose newest `done` decision is at or after `since`, by key (DESIGN §7).

    Each row has `key` and `done_at`, that decision's time. Not one: a ticket marked done with no `done` decision since
    the operator last forgot it, or whose newest one says `closed`, since the tracker reports a closed ticket closed,
    and leaving it out lets the query find it again once it is reopened.
    """
    # Each done ticket's newest decision by `decisions_ticket`, not a scan of every decision ever recorded.
    return conn.execute(
        "SELECT t.key, d.created_at AS done_at FROM tickets t JOIN decisions d ON d.id = ("
        "  SELECT max(id) FROM decisions WHERE ticket_key = t.key AND action = 'done'"
        ") WHERE t.done = 1 AND d.created_at >= ? AND d.rationale != ? "
        "AND (t.forgotten_at IS NULL OR d.created_at > t.forgotten_at) ORDER BY t.key",
        (since, CLOSED_RATIONALE),
    ).fetchall()


# The run lifecycle (DESIGN §6, §8): what every table of detached runs shares

# A run with its ticket's title as `ticket_title`, for display (DESIGN §13). Every query a page or `canopy status` shows
# runs from starts here.
_RUNS = "SELECT r.*, t.title AS ticket_title FROM runs r LEFT JOIN tickets t ON t.key = r.ticket_key"
# What a run table's rows are read as: a run with its ticket's title, for display, and any other run as it is.
_RUN_SELECT: Mapping[RunTable, str] = {
    "runs": _RUNS,
    "chore_runs": "SELECT r.* FROM chore_runs r",
    "review_runs": "SELECT r.* FROM review_runs r",
}


def running_runs(conn: sqlite3.Connection, table: RunTable) -> list[sqlite3.Row]:
    """Return `table`'s runs with status `running`, oldest first."""
    return conn.execute(f"{_RUN_SELECT[table]} WHERE r.status = 'running' ORDER BY r.started_at").fetchall()


def claim_run(conn: sqlite3.Connection, table: RunTable, run_id: int, pid: int) -> bool:
    """Record `pid` as the process working a running run in `table`. Only the first process to claim a run gets it.

    The spawn claims with the pid it started, and the process (`_run`, `_chore`, `_review`) claims with its own, which
    is the same pid; a second process for the same run has a different one and is refused.

    Returns:
        True if `pid` now holds the run; False if the run is not running or another pid holds it.
    """
    cur = conn.execute(
        f"UPDATE {table} SET pid = ? WHERE id = ? AND status = 'running' AND (pid IS NULL OR pid = ?)",  # noqa: S608
        (pid, run_id, pid),
    )
    return cur.rowcount == 1


def set_agent_pid(conn: sqlite3.Connection, table: RunTable, run_id: int, pid: int) -> None:
    """Record the pid, and so the process group, of the agent a run in `table` started: a worker, chore, or reviewer."""
    conn.execute(f"UPDATE {table} SET {AGENT_PID[table]} = ? WHERE id = ?", (pid, run_id))  # noqa: S608


def set_run_report(
    conn: sqlite3.Connection,
    table: RunTable,
    run_id: int,
    session_id: str | None,
    usage: Usage | None,
    *,
    digest: str | None = None,
) -> None:
    """Record what the agent runtime reported about a run in `table`: its session, and what it cost (DESIGN §13).

    `digest` names the definitions snapshot the run loaded, recorded only when the runtime reported something.
    """
    _set_report(conn, table, run_id, session_id, usage, digest=digest)


def finish_run(
    conn: sqlite3.Connection,
    table: RunTable,
    run_id: int,
    status: AnyRunStatus,
    result_json: str | None,
    *,
    event: Event | None = None,
) -> bool:
    """Close a running run in `table`, recording `event` with it. Returns False if it was already closed.

    A worker or split run that reports messages closes with `finish_ticket_run` instead. A review run that ends `done`
    also ends its PR's open review request, as `reviewed`, in the same transaction (DESIGN §21): the request asked for
    one review, and this is it.

    Returns:
        True if this call closed the run.
    """
    with transaction(conn):
        closed = _close_run(conn, table, run_id, status, result_json)
        if closed and table == "review_runs" and status == "done":
            conn.execute(
                "UPDATE review_requests SET ended_at = ?, end_reason = 'reviewed' "
                "WHERE ended_at IS NULL AND pr_url = (SELECT pr_url FROM review_runs WHERE id = ?)",
                (now(), run_id),
            )
        if closed and event is not None:
            record_event(conn, event)
    return closed


def _close_run(
    conn: sqlite3.Connection, table: RunTable, run_id: int, status: AnyRunStatus, result_json: str | None
) -> bool:
    """Close a running run in `table`, in the caller's transaction. Nothing changes for one already closed.

    Returns:
        True if this call closed the run.
    """
    cur = conn.execute(
        f"UPDATE {table} SET ended_at = ?, status = ?, result_json = ? "  # noqa: S608
        "WHERE id = ? AND status = 'running'",
        (now(), status, result_json, run_id),
    )
    return cur.rowcount == 1


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
) -> int:
    """Insert a `running` run with no pid yet, logging to `<runs_dir>/<id>.log`, and return its id.

    Each of `slots` is recorded in `run_slots`, and each repository they came from becomes a unit of the ticket with the
    run's branch. A run that does not work in units, a split, leaves the ticket's branch and units as they are: it
    pushes nothing (DESIGN §18). `started` builds the `run.started` event from the run's id, recorded in the same
    transaction, or None when no sink takes it. `private` marks a run on a private ticket (DESIGN §22). `check` runs
    first in the transaction and refuses the run by raising: what it reads cannot change before the row is written.

    Returns:
        The new run's id.
    """
    with transaction(conn):
        if check is not None:
            check()
        cur = conn.execute(
            "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, log_path, private) "
            "VALUES (?, ?, ?, ?, ?, '', ?)",
            (tick_id, key, kind, branch, now(), int(private)),
        )
        run_id = _rowid(cur)
        conn.execute("UPDATE runs SET log_path = ? WHERE id = ?", (str(runs_dir / f"{run_id}.log"), run_id))
        conn.executemany(
            "INSERT INTO run_slots (run_id, repo, slot_path, lease_id, lease_holder, base_branch, pool) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(run_id, s.repo, str(s.slot_path), s.lease_id, s.lease_holder, s.base_branch, s.pool) for s in slots],
        )
        event = started(run_id) if started is not None else None
        if event is not None:
            record_event(conn, event)
        if not works_units:
            return run_id
        conn.execute("UPDATE tickets SET branch = ? WHERE key = ?", (branch, key))
        for slot in slots:
            _ensure_unit(conn, key, slot.repo)
            conn.execute(
                "UPDATE ticket_units SET branch = ? WHERE ticket_key = ? AND repo = ?", (branch, key, slot.repo)
            )
    return run_id


def run_slots(conn: sqlite3.Connection, run_id: int) -> list[sqlite3.Row]:
    """Return the slots run `run_id` leased, by repository."""
    return conn.execute("SELECT * FROM run_slots WHERE run_id = ? ORDER BY repo", (run_id,)).fetchall()


def all_run_slots(conn: sqlite3.Connection, run_ids: Sequence[int]) -> dict[int, list[sqlite3.Row]]:
    """Return the slots of each run in `run_ids`, by run id, each list by repository."""
    found: dict[int, list[sqlite3.Row]] = {i: [] for i in run_ids}
    if not run_ids:
        return found
    # Only the placeholder count is interpolated; the run ids are bound parameters.
    rows = conn.execute(
        f"SELECT * FROM run_slots WHERE run_id IN ({','.join('?' * len(run_ids))}) ORDER BY run_id, repo",  # noqa: S608
        list(run_ids),
    )
    for row in rows:
        found[int(row["run_id"])].append(row)
    return found


def get_run(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row | None:
    """Return the run with `run_id`, or None."""
    row: sqlite3.Row | None = conn.execute(f"{_RUNS} WHERE r.id = ?", (run_id,)).fetchone()
    return row


def set_slot_link(conn: sqlite3.Connection, run_id: int, repo: str, link: bytes | None) -> None:
    """Record what a run's slot's `.git` file held when `_run` started (DESIGN §8)."""
    conn.execute("UPDATE run_slots SET git_link = ? WHERE run_id = ? AND repo = ?", (link, run_id, repo))


def finish_ticket_run(
    conn: sqlite3.Connection,
    run_id: int,
    status: RunStatus,
    result_json: str | None,
    *,
    messages: Sequence[tuple[str, str]] = (),
    event: Callable[[int | None], Event | None] | None = None,
) -> bool:
    """Close a running worker or split run, with the messages it reports and its event, as `finish_run` closes any run.

    `messages` are the run's `(kind, body)` messages about its ticket (DESIGN §22), recorded in order. `event` builds
    the `run.ended` event from the id of the last of them, or None if there are none. Nothing changes for a run already
    closed.

    Returns:
        True if this call closed the run.
    """
    with transaction(conn):
        if not _close_run(conn, "runs", run_id, status, result_json):
            return False
        key = conn.execute("SELECT ticket_key FROM runs WHERE id = ?", (run_id,)).fetchone()[0]
        last: int | None = None
        for kind, body in messages:
            last = insert_message(
                conn, SUBJECT_TICKET, str(key), source="worker", kind=kind, channel="run", body=body, run_id=run_id
            )
        built = event(last) if event is not None else None
        if built is not None:
            record_event(conn, built)
    return True


def set_tick_report(
    conn: sqlite3.Connection, tick_id: int, session_id: str | None, usage: Usage | None, *, digest: str | None = None
) -> None:
    """Record what the agent runtime reported about a tick's overseer run: its session, and what it cost (§6, §13).

    `digest` names the definitions snapshot the overseer loaded, recorded only when the runtime reported something.
    """
    _set_report(conn, "ticks", tick_id, session_id, usage, digest=digest)


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
    with transaction(conn):
        conn.execute("UPDATE runs SET session_id = ? WHERE id = ? AND status = 'running'", (session_id, run_id))
        if usage is not None:
            conn.execute(
                "UPDATE runs SET cost_usd = ?, tokens_input = ?, tokens_output = ?, tokens_reasoning = ?, "
                "tokens_cache_read = ?, tokens_cache_write = ?, tokens_peak_context = ?, tokens_first_call = ?, "
                "tokens_first_cache_write = ? WHERE id = ? AND status = 'running'",
                (*_spent(usage), run_id),
            )
        if did is not None:
            conn.execute(
                "UPDATE runs SET activity_tool = ?, activity = ?, activity_at = ? WHERE id = ? AND status = 'running'",
                (*did, now(), run_id),
            )


def set_tick_session(conn: sqlite3.Connection, tick_id: int, session_id: str) -> None:
    """Record a tick's overseer session while it runs, before what it cost is known (§6, §13)."""
    conn.execute("UPDATE ticks SET session_id = ? WHERE id = ?", (session_id, tick_id))


def usage_of(row: sqlite3.Row | records.Row) -> Usage | None:
    """What a run, chore run, review run, or tick row says its agent cost, or None when the runtime reported nothing.

    Returns:
        The row's cost and token counts, a missing count read as 0 and a missing peak context or first call as
        unknown, or None when it has no cost.
    """
    values = records.columns(row)
    if values["cost_usd"] is None:
        return None
    return agent_output.Usage(
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
    )


def _set_report(
    conn: sqlite3.Connection,
    table: RunTable | Literal["ticks"],
    row_id: int,
    session_id: str | None,
    usage: Usage | None,
    *,
    digest: str | None,
) -> None:
    spent = _spent(usage) if usage is not None else (None,) * 9
    # Only with a report: a template of the operator's that prints plain text may not load the snapshot at all.
    loaded = digest if session_id is not None or usage is not None else None
    conn.execute(
        f"UPDATE {table} SET session_id = ?, cost_usd = ?, tokens_input = ?, tokens_output = ?, "  # noqa: S608
        "tokens_reasoning = ?, tokens_cache_read = ?, tokens_cache_write = ?, tokens_peak_context = ?, "
        "tokens_first_call = ?, tokens_first_cache_write = ?, definitions_digest = ? WHERE id = ?",
        (session_id, *spent, loaded, row_id),
    )


def _spent(usage: Usage) -> tuple[float, int, int, int, int, int, int | None, int | None, int | None]:
    """`usage` as the cost and token columns hold it, in the order `_set_report` and `set_run_progress` write them.

    Returns:
        The cost, each kind of token, the peak context, and the first call's tokens and cache write.
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
    )


def spent_since(conn: sqlite3.Connection, since: str) -> float | None:
    """What every agent run that started at or after `since` cost; None when none of them reported one (§13).

    Worker and split runs, chore runs, review runs, and each tick's overseer: every table an agent run records on.

    Returns:
        The total cost in US dollars, or None when no such run reported one.
    """
    row = conn.execute(
        "SELECT (SELECT SUM(cost_usd) FROM runs WHERE started_at >= ?), "
        "(SELECT SUM(cost_usd) FROM chore_runs WHERE started_at >= ?), "
        "(SELECT SUM(cost_usd) FROM review_runs WHERE started_at >= ?), "
        "(SELECT SUM(cost_usd) FROM ticks WHERE started_at >= ?)",
        (since, since, since, since),
    ).fetchone()
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
    return conn.execute(
        f"{_RUNS} WHERE r.status != 'running' ORDER BY r.ended_at DESC, r.id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def ended_runs_of(conn: sqlite3.Connection, key: str, limit: int) -> list[sqlite3.Row]:
    """Return a ticket's latest `limit` ended runs since any forget, oldest first: id, kind, status, and end."""
    rows = conn.execute(
        "SELECT r.id, r.kind, r.status, r.ended_at FROM runs r LEFT JOIN tickets t ON t.key = r.ticket_key "
        "WHERE r.ticket_key = ? AND r.status != 'running' AND r.id > coalesce(t.forgotten_run_id, 0) "
        "ORDER BY r.id DESC LIMIT ?",
        (key, limit),
    ).fetchall()
    return rows[::-1]


def latest_runs(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    """Return each ticket's most recent run, by ticket key: none for a ticket forgotten since its latest run."""
    rows = conn.execute(
        "SELECT r.* FROM runs r LEFT JOIN tickets t ON t.key = r.ticket_key "
        "WHERE r.id = (SELECT max(id) FROM runs WHERE ticket_key = r.ticket_key) "
        "AND r.id > coalesce(t.forgotten_run_id, 0)"
    ).fetchall()
    return {str(r["ticket_key"]): r for r in rows}


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
) -> int:
    """Insert a decision for `tick_id` and return its id.

    `repo` is set for an item about a repository, `chore` for a decision about a chore, which has no ticket key, and
    `pr` for a decision about a PR the loop reviews, which has a ticket key only for one of the loop's own PRs.

    Returns:
        The new decision's id.
    """
    cur = conn.execute(
        "INSERT INTO decisions (tick_id, ticket_key, action, rationale, repo, chore, pr) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (tick_id, key, action, rationale, repo, chore, pr),
    )
    return _rowid(cur)


# Chore runs (DESIGN §19)


def insert_chore_run(conn: sqlite3.Connection, *, tick_id: int | None, chore: str, logs_dir: Path) -> int:
    """Insert a `running` chore run with no pid yet, logging to `<logs_dir>/<id>.log`, and return its id.

    `tick_id` is the tick whose overseer started the run, or None for one the operator started with `canopy chore try`.

    Returns:
        The new chore run's id.
    """
    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO chore_runs (tick_id, chore, started_at, log_path) VALUES (?, ?, ?, '')",
            (tick_id, chore, now()),
        )
        run_id = _rowid(cur)
        conn.execute("UPDATE chore_runs SET log_path = ? WHERE id = ?", (str(logs_dir / f"{run_id}.log"), run_id))
    return run_id


def get_chore_run(conn: sqlite3.Connection, run_id: int) -> records.ChoreRun | None:
    """Return the chore run with `run_id`, or None."""
    return records.fetch_one(conn, records.ChoreRun, "SELECT * FROM chore_runs WHERE id = ?", (run_id,))


def chore_runs(
    conn: sqlite3.Connection, chore: str, limit: int = 1000, *, before: int | None = None
) -> list[records.ChoreRun]:
    """Return `chore`'s runs, newest first: at most `limit`, and only those before run id `before` if it is given."""
    return records.fetch_all(
        conn,
        records.ChoreRun,
        "SELECT * FROM chore_runs WHERE chore = ? AND id < ? ORDER BY id DESC LIMIT ?",
        (chore, before if before is not None else 2**63 - 1, limit),
    )


def chore_costs_since(conn: sqlite3.Connection, chore: str, since: str) -> tuple[int, list[float]]:
    """How many of `chore`'s runs started at or after `since`, and what each of those that reported a cost cost (§13).

    Returns:
        The runs, a running one included, and the costs reported, in US dollars, cheapest first.
    """
    rows = conn.execute(
        "SELECT cost_usd FROM chore_runs WHERE chore = ? AND started_at >= ?",
        (chore, since),
    ).fetchall()
    return len(rows), sorted(float(r[0]) for r in rows if r[0] is not None)


def dismissals(conn: sqlite3.Connection, chore: str) -> dict[str, str]:
    """Return when the operator dismissed each of `chore`'s findings it dismissed, by finding id (DESIGN §19)."""
    rows = conn.execute("SELECT finding_id, dismissed_at FROM finding_dismissals WHERE chore = ?", (chore,))
    return {str(r["finding_id"]): str(r["dismissed_at"]) for r in rows}


def set_dismissal(conn: sqlite3.Connection, chore: str, finding_id: str, *, channel: str) -> None:
    """Record that the operator dismissed `chore`'s finding `finding_id` now, replacing an earlier dismissal of it."""
    conn.execute(
        "INSERT INTO finding_dismissals (chore, finding_id, dismissed_at, channel) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (chore, finding_id) DO UPDATE SET "
        "dismissed_at = excluded.dismissed_at, channel = excluded.channel",
        (chore, finding_id, now(), channel),
    )


def delete_dismissal(conn: sqlite3.Connection, chore: str, finding_id: str) -> bool:
    """Take back the operator's dismissal of `chore`'s finding `finding_id`.

    Returns:
        Whether there was one to take back.
    """
    cur = conn.execute("DELETE FROM finding_dismissals WHERE chore = ? AND finding_id = ?", (chore, finding_id))
    return cur.rowcount > 0


# Review runs (DESIGN §21)


def insert_review_run(
    conn: sqlite3.Connection,
    *,
    tick_id: int,
    pr_url: str,
    sha: str,
    ticket: str | None,
    repo: str | None,
    purpose: str,
    logs_dir: Path,
) -> int:
    """Insert a `running` review run with no slot or pid yet, logging to `<logs_dir>/<id>.log`, and return its id.

    `purpose` is why it runs (DESIGN §21): `own` for one of the loop's own PRs, `request` for a PR the operator
    asked for, `query` for a `review.query` match.

    Returns:
        The new review run's id.
    """
    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO review_runs (tick_id, pr_url, sha, ticket_key, repo, purpose, started_at, log_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, '')",
            (tick_id, pr_url, sha, ticket, repo, purpose, now()),
        )
        run_id = _rowid(cur)
        conn.execute("UPDATE review_runs SET log_path = ? WHERE id = ?", (str(logs_dir / f"{run_id}.log"), run_id))
    return run_id


def delete_review_run(conn: sqlite3.Connection, run_id: int) -> None:
    """Forget a review run that never started: no slot, or no prompt. It counts toward no limit."""
    conn.execute("DELETE FROM review_runs WHERE id = ? AND pid IS NULL", (run_id,))


def review_dismissals(conn: sqlite3.Connection, run_id: int) -> frozenset[int]:
    """Return the numbers, from 1, of review run `run_id`'s findings the operator dismissed (DESIGN §21)."""
    rows = conn.execute("SELECT finding FROM review_dismissals WHERE review_run_id = ?", (run_id,))
    return frozenset(int(r[0]) for r in rows)


def set_review_dismissal(conn: sqlite3.Connection, run_id: int, finding: int, *, channel: str) -> None:
    """Record that the operator dismissed review run `run_id`'s finding number `finding` now."""
    conn.execute(
        "INSERT INTO review_dismissals (review_run_id, finding, dismissed_at, channel) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (review_run_id, finding) DO UPDATE SET "
        "dismissed_at = excluded.dismissed_at, channel = excluded.channel",
        (run_id, finding, now(), channel),
    )


def delete_review_dismissal(conn: sqlite3.Connection, run_id: int, finding: int) -> bool:
    """Take back the operator's dismissal of review run `run_id`'s finding number `finding`.

    Returns:
        Whether there was one to take back.
    """
    cur = conn.execute("DELETE FROM review_dismissals WHERE review_run_id = ? AND finding = ?", (run_id, finding))
    return cur.rowcount > 0


def set_review_slot(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    slot: Path,
    lease_id: str,
    lease_holder: str,
    base_branch: str,
    pool: PoolKind,
) -> None:
    """Record the slot a review run leased, the base branch it was leased on, and the pool that made the lease."""
    conn.execute(
        "UPDATE review_runs SET slot_path = ?, lease_id = ?, lease_holder = ?, base_branch = ?, pool = ? WHERE id = ?",
        (str(slot), lease_id, lease_holder, base_branch, pool, run_id),
    )


def get_review_run(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row | None:
    """Return the review run with `run_id`, or None."""
    row: sqlite3.Row | None = conn.execute("SELECT * FROM review_runs WHERE id = ?", (run_id,)).fetchone()
    return row


def review_runs_of(conn: sqlite3.Connection, pr_url: str) -> list[sqlite3.Row]:
    """Return a PR's review runs, newest first."""
    return conn.execute("SELECT * FROM review_runs WHERE pr_url = ? ORDER BY id DESC", (pr_url,)).fetchall()


def recent_review_runs(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Return the latest `limit` review runs, newest first."""
    return conn.execute("SELECT * FROM review_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def review_runs_since(conn: sqlite3.Connection, since: str) -> list[sqlite3.Row]:
    """Return the review runs started at or after `since`, newest first."""
    return conn.execute("SELECT * FROM review_runs WHERE started_at >= ? ORDER BY id DESC", (since,)).fetchall()


def is_unit_pr(conn: sqlite3.Connection, key: str, pr_url: str, *, repo: str | None = None) -> bool:
    """Return whether `pr_url` is the PR of one of ticket `key`'s units, or its unit in `repo`: one the loop opened."""
    query = "SELECT 1 FROM ticket_units WHERE ticket_key = ? AND pr_url = ?"
    params: tuple[str, ...] = (key, pr_url)
    if repo is not None:
        query, params = f"{query} AND repo = ?", (*params, repo)
    return conn.execute(query, params).fetchone() is not None


def review_runs_of_prs(conn: sqlite3.Connection, pr_urls: Sequence[str]) -> dict[str, list[sqlite3.Row]]:
    """Return the review runs of each of `pr_urls` that has any, by URL, each list newest first."""
    found: dict[str, list[sqlite3.Row]] = {}
    marks = ", ".join("?" * len(pr_urls))
    query = f"SELECT * FROM review_runs WHERE pr_url IN ({marks}) ORDER BY id DESC"  # noqa: S608  (only `?`s)
    # SQLite takes an empty list, `IN ()`, as matching nothing.
    for row in conn.execute(query, tuple(pr_urls)):
        found.setdefault(str(row["pr_url"]), []).append(row)
    return found


def pull_requests(conn: sqlite3.Connection, limit: int, *, url: str | None = None) -> list[sqlite3.Row]:
    """Return the `limit` PRs with the most recent activity, most recently active first; with `url`, only it (§22).

    A PR is known by a ticket's unit, whose activity is the ticket's last sighting, by a review run, whose activity
    is its start or end, or by the operator's review request, whose activity is when it was made or ended. Each row
    has `url` and `active_at`, and the unit's `ticket_key`, `repo`, `branch`, `phase`, and the ticket's `title`, all
    NULL for a PR no unit records. Decisions are not a source: they are many. Only the candidates `_candidates` finds
    are weighed, so the read costs what `limit` does.
    """
    if limit < 1:
        return []
    with _snapshot(conn):
        urls = json.dumps([url] if url is not None else _candidates(conn, _PR_ACTIVITY, limit))
        return _weighed_pull_requests(conn, urls, limit)


def _weighed_pull_requests(conn: sqlite3.Connection, urls: str, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT k.url, max(k.at) AS active_at, u.ticket_key, u.repo, u.branch, u.phase, t.title "
        "FROM ("
        "  SELECT u.pr_url AS url, t.last_seen_at AS at FROM ticket_units u JOIN tickets t ON t.key = u.ticket_key"
        "  WHERE u.pr_url IN (SELECT value FROM json_each(?))"
        "  UNION ALL SELECT pr_url, coalesce(ended_at, started_at) FROM review_runs"
        "  WHERE pr_url IN (SELECT value FROM json_each(?))"
        "  UNION ALL SELECT pr_url, coalesce(ended_at, created_at) FROM review_requests"
        "  WHERE pr_url IN (SELECT value FROM json_each(?))"
        ") k "
        "LEFT JOIN ticket_units u ON u.pr_url = k.url LEFT JOIN tickets t ON t.key = u.ticket_key "
        "GROUP BY k.url ORDER BY active_at DESC, k.url LIMIT ?",
        (urls, urls, urls, limit),
    ).fetchall()


# Each source of a PR's activity as `pull_requests` weighs it, for `_candidates`: its units by when a tick last saw
# their ticket, its review runs by when each ended, or started while it runs (`finish_run` sets the end), and its
# review requests by when each ended, or was made while it is open.
# CROSS JOIN keeps SQLite reading the tickets in order and each one's units after, rather than sorting every unit.
_PR_ACTIVITY = (
    (
        "SELECT u.pr_url, t.last_seen_at FROM tickets t CROSS JOIN ticket_units u ON u.ticket_key = t.key "
        "WHERE u.pr_url IS NOT NULL ORDER BY t.last_seen_at DESC"
    ),
    "SELECT pr_url, ended_at FROM review_runs WHERE ended_at IS NOT NULL ORDER BY ended_at DESC",
    "SELECT pr_url, started_at FROM review_runs WHERE status = 'running' ORDER BY started_at DESC",
    "SELECT pr_url, coalesce(ended_at, created_at) AS at FROM review_requests ORDER BY at DESC",
)


def _candidates(conn: sqlite3.Connection, sources: Sequence[str], limit: int) -> list[str]:
    """The keys that may be among the `limit` with the most recent activity: each source's newest `limit`.

    Each source is a query of a key and a time, newest first, read in order from an index. A key's activity is its
    newest time in any source. Every key newer than it in that source is newer overall too, so a key among the
    `limit` newest overall is among the `limit` newest of that source. Keys tied with the last of a source's are read
    as well, so a tie never decides which one is left out.

    Returns:
        The candidates' keys, each once.
    """
    found: dict[str, None] = {}
    for sql in sources:
        found.update(dict.fromkeys(_newest(conn, sql, limit)))
    return list(found)


@contextmanager
def _snapshot(conn: sqlite3.Connection) -> Generator[None]:
    """Every read in the block sees one snapshot of the journal: a deferred transaction, which writes nothing.

    The candidates and the weighing of them are separate reads, and a commit between them in autocommit could leave
    out a key that its new activity had just moved among the newest. Inside a transaction already, as the event
    stream's reads are, the block reads in that one.
    """
    if conn.in_transaction:
        yield
        return
    conn.execute("BEGIN")
    try:
        yield
    finally:
        conn.execute("COMMIT")


def _newest(conn: sqlite3.Connection, sql: str, limit: int) -> list[str]:
    seen: dict[str, None] = {}
    cutoff: str | None = None
    # Closed when the walk stops early, so the statement does not hold its read open in autocommit.
    with closing(conn.execute(sql)) as rows:
        for key, at in rows:
            if cutoff is not None and at < cutoff:
                break
            if key not in seen:
                seen[str(key)] = None
                if len(seen) == limit:
                    cutoff = at
    return list(seen)


# Split children


def record_split_children(conn: sqlite3.Connection, parent: str, run_id: int, children: Mapping[str, str]) -> None:
    """Record the children a split run created, each child key with the repository it covers, in one transaction."""
    with transaction(conn):
        conn.executemany(
            "INSERT INTO split_children (child_key, parent_key, repo, run_id) VALUES (?, ?, ?, ?)",
            [(child, parent, repo, run_id) for child, repo in children.items()],
        )


def split_child(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    """Return `key`'s row in `split_children` if a split created it, else None."""
    row: sqlite3.Row | None = conn.execute("SELECT * FROM split_children WHERE child_key = ?", (key,)).fetchone()
    return row


def children_of(conn: sqlite3.Connection, parent: str) -> list[str]:
    """Return the keys of the children a split of `parent` created, sorted."""
    rows = conn.execute("SELECT child_key FROM split_children WHERE parent_key = ? ORDER BY child_key", (parent,))
    return [str(r[0]) for r in rows]


def open_split_children(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return the children of every split whose parent or child is not marked done, with their split run's end."""
    return conn.execute(
        "SELECT c.child_key, c.parent_key, c.repo, c.run_id, r.ended_at FROM split_children c "
        "JOIN runs r ON r.id = c.run_id "
        "LEFT JOIN tickets p ON p.key = c.parent_key LEFT JOIN tickets t ON t.key = c.child_key "
        "WHERE coalesce(p.done, 0) = 0 OR coalesce(t.done, 0) = 0 ORDER BY c.parent_key, c.child_key"
    ).fetchall()


def has_runs(conn: sqlite3.Connection, key: str) -> bool:
    """Return whether any run was ever dispatched for `key`."""
    return conn.execute("SELECT 1 FROM runs WHERE ticket_key = ? LIMIT 1", (key,)).fetchone() is not None


def decisions_for_tick(conn: sqlite3.Connection, tick_id: int) -> list[records.Decision]:
    """Return a tick's decisions in the order they were recorded."""
    return records.fetch_all(
        conn, records.Decision, "SELECT * FROM decisions WHERE tick_id = ? ORDER BY id", (tick_id,)
    )


def decisions_about(conn: sqlite3.Connection, key: str, limit: int) -> list[records.Decision]:
    """Return the latest `limit` decisions about ticket `key`, its units' included, across ticks, newest first."""
    return records.fetch_all(
        conn, records.Decision, "SELECT * FROM decisions WHERE ticket_key = ? ORDER BY id DESC LIMIT ?", (key, limit)
    )


def decisions_about_pr(conn: sqlite3.Connection, url: str, limit: int) -> list[records.Decision]:
    """Return the latest `limit` decisions that name the PR at `url`, across ticks, newest first."""
    return records.fetch_all(
        conn, records.Decision, "SELECT * FROM decisions WHERE pr = ? ORDER BY id DESC LIMIT ?", (url, limit)
    )


def last_decision_of(conn: sqlite3.Connection, key: str) -> str | None:
    """Return the newest decision's action about ticket `key` since it was forgotten, or None if no tick made one.

    The overseer records a decision for every ticket a tick looks at, but a phase only when told to, so this, not
    `tickets.phase`, says whether a tick has seen the ticket.
    """
    row = conn.execute(
        "SELECT d.action FROM decisions d LEFT JOIN tickets t ON t.key = d.ticket_key "
        "WHERE d.ticket_key = ? AND (t.forgotten_at IS NULL OR d.created_at > t.forgotten_at) "
        "ORDER BY d.id DESC LIMIT 1",
        (key,),
    ).fetchone()
    return None if row is None else str(row[0])


def recent_ticks(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Return the latest `limit` ticks, newest first, each with `decisions`, how many it recorded."""
    return conn.execute(
        "SELECT t.*, (SELECT count(*) FROM decisions d WHERE d.tick_id = t.id) AS decisions "
        "FROM ticks t ORDER BY t.id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def decision_count(conn: sqlite3.Connection, tick_id: int) -> int:
    """Return how many decisions a tick recorded."""
    row = conn.execute("SELECT count(*) FROM decisions WHERE tick_id = ?", (tick_id,)).fetchone()
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
) -> int:
    """Record a message and return its id.

    A submission already recorded for the subject records nothing new: its message's id is returned instead. So does a
    tracker comment already mirrored for the subject.

    Returns:
        The id of the new message, or of the one already recorded for the submission or comment.
    """
    if submission is not None:
        found = conn.execute(
            "SELECT id FROM messages WHERE subject_kind = ? AND subject_id = ? AND submission = ?",
            (subject_kind, subject_id, submission),
        ).fetchone()
        if found is not None:
            return int(found[0])
    if comment is not None:
        mirrored = mirrored_comment(conn, subject_kind, subject_id, comment.id)
        if mirrored is not None:
            return int(mirrored["id"])
    cur = conn.execute(
        "INSERT INTO messages (subject_kind, subject_id, at, source, kind, channel, run_id, body, answers, submission, "
        "comment_id, author, commented_at, truncated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            subject_kind,
            subject_id,
            now(),
            source,
            kind,
            channel,
            run_id,
            body,
            answers,
            submission,
            *((comment.id, comment.author, comment.at, int(comment.truncated)) if comment else (None, None, None, 0)),
        ),
    )
    return _rowid(cur)


def mirrored_comment(
    conn: sqlite3.Connection, subject_kind: str, subject_id: str, comment_id: str
) -> sqlite3.Row | None:
    """Return the message a tracker comment was mirrored as, or None if it was not (DESIGN §22)."""
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM messages WHERE subject_kind = ? AND subject_id = ? AND comment_id = ?",
        (subject_kind, subject_id, comment_id),
    ).fetchone()
    return row


def set_mirror_cursor(conn: sqlite3.Connection, key: str, comment_id: str) -> None:
    """Move a ticket's mirror cursor to a tracker comment, the newest mirrored. Call inside a transaction."""
    conn.execute("UPDATE tickets SET last_mirrored_id = ? WHERE key = ?", (comment_id, key))


def count_decisions(conn: sqlite3.Connection, tick_id: int, action: str) -> int:
    """Return how many decisions with `action` a tick recorded."""
    row = conn.execute("SELECT count(*) FROM decisions WHERE tick_id = ? AND action = ?", (tick_id, action)).fetchone()
    return int(row[0])


def get_message(conn: sqlite3.Connection, message_id: int) -> sqlite3.Row | None:
    """Return the message with `message_id`, or None."""
    row: sqlite3.Row | None = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
    return row


def messages_of(
    conn: sqlite3.Connection, subject_kind: str, subject_id: str, limit: int, *, after: int = 0
) -> list[sqlite3.Row]:
    """Return a subject's latest `limit` messages newer than message id `after`, oldest first."""
    rows = conn.execute(
        "SELECT * FROM messages WHERE subject_kind = ? AND subject_id = ? AND id > ? ORDER BY id DESC LIMIT ?",
        (subject_kind, subject_id, after, limit),
    ).fetchall()
    return rows[::-1]


def run_messages(conn: sqlite3.Connection, run_id: int) -> list[sqlite3.Row]:
    """Return the messages a run reported, in order."""
    return conn.execute("SELECT * FROM messages WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()


def latest_message_id(conn: sqlite3.Connection, *, source: str | None = None, subject_kind: str | None = None) -> int:
    """Return the id of the newest message, of the newest from `source`, or about a kind of subject; 0 if none."""
    row = conn.execute(
        "SELECT max(id) FROM messages WHERE (? IS NULL OR source = ?) AND (? IS NULL OR subject_kind = ?)",
        (source, source, subject_kind, subject_kind),
    ).fetchone()
    return int(row[0] or 0)


def get_start(conn: sqlite3.Connection, subject_kind: str, subject_id: str) -> sqlite3.Row | None:
    """Return a subject's start record, or None if the operator never started it."""
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM starts WHERE subject_kind = ? AND subject_id = ?", (subject_kind, subject_id)
    ).fetchone()
    return row


def starts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return every start record, by subject."""
    return conn.execute("SELECT * FROM starts ORDER BY subject_kind, subject_id").fetchall()


def set_start(conn: sqlite3.Connection, subject_kind: str, subject_id: str, *, status: str, channel: str) -> None:
    """Mark a subject started or stopped, creating its record on its first start. Call inside a transaction."""
    ts = now()
    if status == "started":
        conn.execute(
            "INSERT INTO starts (subject_kind, subject_id, status, started_at, channel) "
            "VALUES (?, ?, 'started', ?, ?) ON CONFLICT (subject_kind, subject_id) DO UPDATE SET status = 'started', "
            "started_at = excluded.started_at, stopped_at = NULL, channel = excluded.channel",
            (subject_kind, subject_id, ts, channel),
        )
    else:
        conn.execute(
            "UPDATE starts SET status = 'stopped', stopped_at = ?, channel = ? "
            "WHERE subject_kind = ? AND subject_id = ?",
            (ts, channel, subject_kind, subject_id),
        )


def running_run_of(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    """Return the run working `key` now, if one is."""
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM runs WHERE ticket_key = ? AND status = 'running' ORDER BY id DESC LIMIT 1", (key,)
    ).fetchone()
    return row


def runs_of(conn: sqlite3.Connection, key: str, limit: int | None) -> list[sqlite3.Row]:
    """Return a ticket's latest `limit` runs, newest first; with None, every one."""
    # SQLite reads a negative LIMIT as none.
    return conn.execute(
        f"{_RUNS} WHERE r.ticket_key = ? ORDER BY r.id DESC LIMIT ?",
        (key, -1 if limit is None else limit),
    ).fetchall()


def ticket_cost(conn: sqlite3.Connection, key: str) -> sqlite3.Row:
    """Return what a ticket's runs and the review runs naming it cost, however long ago they ran (§13).

    The row has `runs` and `reviews`, how many of each; `priced`, how many of them reported a cost; and `cost_usd`,
    what those cost, NULL when none did. Not the overseer's: a tick's cost is the whole workspace's.
    """
    row: sqlite3.Row = conn.execute(
        "SELECT r.n AS runs, v.n AS reviews, r.priced + v.priced AS priced, "
        "  CASE WHEN r.priced + v.priced > 0 THEN coalesce(r.cost, 0) + coalesce(v.cost, 0) END AS cost_usd "
        "FROM (SELECT count(*) AS n, count(cost_usd) AS priced, sum(cost_usd) AS cost FROM runs"
        "  WHERE ticket_key = ?) r, "
        "(SELECT count(*) AS n, count(cost_usd) AS priced, sum(cost_usd) AS cost FROM review_runs"
        "  WHERE ticket_key = ?) v",
        (key, key),
    ).fetchone()
    return row


def recent_tickets(conn: sqlite3.Connection, limit: int, *, key: str | None = None) -> list[sqlite3.Row]:
    """Return the `limit` tickets with the most recent activity, most recently active first, each row with `active_at`.

    Activity is a message, a run starting or ending, a start or stop, or a tick seeing the ticket. Every one of those
    times is the journal's own format, so the newest is the greatest string. With `key`, only that ticket.

    Only the candidates `_candidates` finds are weighed, so the read costs what `limit` does, not what the
    journal's history does: the web UI's event stream reads the list on every commit (DESIGN §22).
    """
    if limit < 1:
        return []
    with _snapshot(conn):
        keys = [key] if key is not None else _candidates(conn, _TICKET_ACTIVITY, limit)
        return _weighed_tickets(conn, json.dumps(keys), limit)


def _weighed_tickets(conn: sqlite3.Connection, keys: str, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT t.*, max("
        "  t.last_seen_at,"
        "  coalesce((SELECT max(m.at) FROM messages m WHERE m.subject_kind = ? AND m.subject_id = t.key), ''),"
        "  coalesce((SELECT max(coalesce(r.ended_at, r.started_at)) FROM runs r WHERE r.ticket_key = t.key), ''),"
        "  coalesce((SELECT coalesce(s.stopped_at, s.started_at) FROM starts s"
        "    WHERE s.subject_kind = ? AND s.subject_id = t.key), '')"
        ") AS active_at "
        "FROM tickets t WHERE t.key IN (SELECT value FROM json_each(?)) ORDER BY active_at DESC, t.key LIMIT ?",
        (SUBJECT_TICKET, SUBJECT_TICKET, keys, limit),
    ).fetchall()


# Each source of a ticket's activity as `recent_tickets` weighs it: a ticket key and a time, newest first, read in
# order from an index (migration 0022). A run that ended has its end time (`finish_run`), so the ended runs and the
# running ones between them give each run's time as `recent_tickets` takes it. Messages and start records may name a
# ticket the journal has no row for, which the join leaves out, so one never takes a real ticket's place; CROSS JOIN
# keeps SQLite reading the start records in order from their index, rather than sorting every one.
_TICKET_ACTIVITY = (
    "SELECT key, last_seen_at FROM tickets ORDER BY last_seen_at DESC",
    (
        "SELECT m.subject_id, m.at FROM messages m JOIN tickets t ON t.key = m.subject_id "
        "WHERE m.subject_kind = 'ticket' ORDER BY m.at DESC"
    ),
    "SELECT ticket_key, ended_at FROM runs WHERE ended_at IS NOT NULL ORDER BY ended_at DESC",
    "SELECT ticket_key, started_at FROM runs WHERE status = 'running' ORDER BY started_at DESC",
    (
        "SELECT s.subject_id, coalesce(s.stopped_at, s.started_at) AS at FROM starts s "
        "CROSS JOIN tickets t ON t.key = s.subject_id WHERE s.subject_kind = 'ticket' ORDER BY at DESC"
    ),
)


def latest_message_of(conn: sqlite3.Connection, subject_kind: str, subject_id: str) -> int | None:
    """Return the id of a subject's newest message, or None if it has none."""
    row = conn.execute(
        "SELECT max(id) FROM messages WHERE subject_kind = ? AND subject_id = ?", (subject_kind, subject_id)
    ).fetchone()
    return None if row[0] is None else int(row[0])


def forget_ticket(conn: sqlite3.Connection, key: str) -> None:
    """Clear what the journal knows of a ticket's branch, PRs, and phases, and mark where its loop view begins.

    Call inside a transaction. Runs, messages, the start record, and the cursors stay (DESIGN §22).
    """
    conn.execute(
        "UPDATE tickets SET branch = NULL, phase = NULL, needs_human_since = NULL, done = 0, forgotten_at = ?, "
        "forgotten_run_id = (SELECT max(id) FROM runs WHERE ticket_key = ?), "
        "forgotten_message_id = (SELECT max(id) FROM messages WHERE subject_kind = ? AND subject_id = ?) "
        "WHERE key = ?",
        (now(), key, SUBJECT_TICKET, key, key),
    )
    conn.execute("DELETE FROM ticket_units WHERE ticket_key = ?", (key,))


def forgotten_message_id(conn: sqlite3.Connection, key: str) -> int:
    """Return the newest message of `key` the operator forgot with its work, or 0: the loop reads only later ones."""
    row = conn.execute("SELECT forgotten_message_id FROM tickets WHERE key = ?", (key,)).fetchone()
    return int(row[0] or 0) if row is not None else 0
