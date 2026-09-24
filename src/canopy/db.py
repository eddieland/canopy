"""The SQLite journal: connection setup, migrations, and the queries the loop makes.

The journal holds facts about the loop only (DESIGN §4, §11). Nothing here is read back as a fact about the world.
Connections run in autocommit mode; anything that must be atomic opens its own transaction.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DB_FILE_NAME = "canopy.db"
_MIGRATION_RE = re.compile(r"(\d{4})_([a-z0-9_]+)\.sql")

# `canopy ticket set --cursor NAME=ID` names, and the column each one updates.
CURSOR_COLUMNS: Mapping[str, str] = {
    "comment": "last_comment_id",
    "review": "last_review_id",
    "ci": "last_ci_run_id",
}


class MigrationError(Exception):
    """The migrations on disk and the database disagree."""


@dataclass(frozen=True)
class Migration:
    """One migration file on disk."""

    version: int
    name: str
    path: Path


def now() -> str:
    """UTC, millisecond precision, the same shape as the schema's own defaults."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def connect(path: Path) -> sqlite3.Connection:
    """Open the journal at `path` in WAL mode with foreign keys on, creating its directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, autocommit=True, timeout=10)
    conn.row_factory = sqlite3.Row
    # WAL must be set outside a transaction; migration 0001 repeats it inside one, where it is then a no-op.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def discover(migrations_dir: Path) -> list[Migration]:
    """Return the migrations in `migrations_dir`, checking names and numbering."""
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
    """Apply pending migrations in order, in one transaction. Returns the versions applied."""
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
            raise MigrationError(f"the journal has migrations this canopy does not know: {sorted(unknown)}")
        for m in known:
            if m.version in applied:
                continue
            conn.executescript(m.path.read_text())
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version, name) VALUES (?, ?)",
                (m.version, m.name),
            )
            applied_now.append(m.version)
    return applied_now


def _rowid(cur: sqlite3.Cursor) -> int:
    if cur.lastrowid is None:
        raise sqlite3.DatabaseError("INSERT returned no row id")
    return cur.lastrowid


# Ticks


def start_tick(conn: sqlite3.Connection, *, dry_run: bool) -> int:
    """Insert a `running` tick row and return its id."""
    cur = conn.execute("INSERT INTO ticks (started_at, dry_run) VALUES (?, ?)", (now(), int(dry_run)))
    return _rowid(cur)


def finish_tick(conn: sqlite3.Connection, tick_id: int, status: str, summary: str) -> None:
    """Close a tick with its final status and summary."""
    conn.execute(
        "UPDATE ticks SET ended_at = ?, status = ?, summary = ? WHERE id = ?",
        (now(), status, summary, tick_id),
    )


def abandon_unfinished_ticks(conn: sqlite3.Connection) -> list[int]:
    """Close ticks left `running` by a tick process that died. Call only while holding the tick lock."""
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
) -> None:
    """Record a ticket's phase, cursors, or done flag in one transaction."""
    with transaction(conn):
        touch_ticket(conn, key, repo)
        if phase is not None:
            conn.execute("UPDATE tickets SET phase = ? WHERE key = ?", (phase, key))
        for name, value in (cursors or {}).items():
            # The column name comes from a fixed mapping, never from input.
            sql = f"UPDATE tickets SET {CURSOR_COLUMNS[name]} = ? WHERE key = ?"  # noqa: S608
            conn.execute(sql, (value, key))
        if done:
            conn.execute("UPDATE tickets SET done = 1 WHERE key = ?", (key,))


def open_tickets(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return the tickets not marked done, by key."""
    return conn.execute("SELECT * FROM tickets WHERE done = 0 ORDER BY key").fetchall()


# Runs and decisions


def running_runs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return runs with status `running`, oldest first."""
    return conn.execute("SELECT * FROM runs WHERE status = 'running' ORDER BY started_at").fetchall()


def insert_run(
    conn: sqlite3.Connection,
    *,
    tick_id: int,
    key: str,
    kind: str,
    slot_path: Path,
    lease_id: str,
    lease_holder: str,
    base_branch: str,
    branch: str,
    runs_dir: Path,
) -> int:
    """Insert a `running` run with no pid yet, logging to `<runs_dir>/<id>.log`, and return its id."""
    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO runs (tick_id, ticket_key, kind, slot_path, lease_id, lease_holder, base_branch, branch, "
            "started_at, log_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '')",
            (tick_id, key, kind, str(slot_path), lease_id, lease_holder, base_branch, branch, now()),
        )
        run_id = _rowid(cur)
        conn.execute("UPDATE runs SET log_path = ? WHERE id = ?", (str(runs_dir / f"{run_id}.log"), run_id))
        conn.execute("UPDATE tickets SET branch = ? WHERE key = ?", (branch, key))
    return run_id


def get_run(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row | None:
    """Return the run with `run_id`, or None."""
    row: sqlite3.Row | None = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    return row


def claim_run(conn: sqlite3.Connection, run_id: int, pid: int) -> bool:
    """Record `pid` as the process working a running run. Only the first process to claim a run gets it.

    `canopy dispatch` claims with the pid it spawned, and `canopy _run` claims with its own, which is the same pid; a
    second `_run` for the same run has a different one and is refused.
    """
    cur = conn.execute(
        "UPDATE runs SET pid = ? WHERE id = ? AND status = 'running' AND (pid IS NULL OR pid = ?)",
        (pid, run_id, pid),
    )
    return cur.rowcount == 1


def set_worker_pid(conn: sqlite3.Connection, run_id: int, pid: int) -> None:
    """Record the pid, and so the process group, of a run's worker agent."""
    conn.execute("UPDATE runs SET worker_pid = ? WHERE id = ?", (pid, run_id))


def finish_run(conn: sqlite3.Connection, run_id: int, status: str, result_json: str | None) -> bool:
    """Close a running run. Returns False if it was already closed, which leaves it as it was."""
    cur = conn.execute(
        "UPDATE runs SET ended_at = ?, status = ?, result_json = ? WHERE id = ? AND status = 'running'",
        (now(), status, result_json, run_id),
    )
    return cur.rowcount == 1


def latest_runs(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    """Return each ticket's most recent run, by ticket key."""
    rows = conn.execute(
        "SELECT * FROM runs r WHERE r.id = (SELECT max(id) FROM runs WHERE ticket_key = r.ticket_key)"
    ).fetchall()
    return {str(r["ticket_key"]): r for r in rows}


def set_pr_url(conn: sqlite3.Connection, key: str, pr_url: str) -> None:
    """Record the PR a worker reported for `key`. Display only, like the phase."""
    conn.execute("UPDATE tickets SET pr_url = ? WHERE key = ?", (pr_url, key))


def record_decision(conn: sqlite3.Connection, tick_id: int, key: str | None, action: str, rationale: str) -> int:
    """Insert a decision for `tick_id` and return its id."""
    cur = conn.execute(
        "INSERT INTO decisions (tick_id, ticket_key, action, rationale) VALUES (?, ?, ?, ?)",
        (tick_id, key, action, rationale),
    )
    return _rowid(cur)


def decisions_for_tick(conn: sqlite3.Connection, tick_id: int) -> list[sqlite3.Row]:
    """Return a tick's decisions in the order they were recorded."""
    return conn.execute("SELECT * FROM decisions WHERE tick_id = ? ORDER BY id", (tick_id,)).fetchall()
