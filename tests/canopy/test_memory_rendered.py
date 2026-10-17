"""What agent memory adds to a worker's prompt, whole, rendered from journals written by hand, against snapshots.

DESIGN §28. The contract at each pair of modes, the ticket digest, and the lessons digest. Other tests assert on the
part their behavior needs; these hold the whole text, so a change to its wording or shape is a diff in review. The
snapshots are syrupy's, in `__snapshots__/test_memory_rendered/`; `make snapshots` records the ones that differ.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from canopy.core import db, memory
from canopy.core.vocab import MemoryMode, RunKind, RunStatus
from tests.canopy.helpers import KEY, in_tick

if TYPE_CHECKING:
    import sqlite3

    from syrupy.assertion import SnapshotAssertion

# Every pair of modes but both off, which renders no contract.
MODES = [
    (notes, proposals)
    for notes in MemoryMode
    for proposals in MemoryMode
    if MemoryMode.OFF not in (notes, proposals) or notes is not proposals
]


@pytest.mark.parametrize(("notes", "proposals"), MODES, ids=[f"notes-{n}-proposals-{p}" for n, p in MODES])
def test_the_memory_contract(markdown_snapshot: SnapshotAssertion, notes: MemoryMode, proposals: MemoryMode) -> None:
    assert memory.memory_contract(memory.Modes(ticket_notes=notes, proposals=proposals)) == markdown_snapshot


def test_the_ticket_digest_of_a_ticket_with_notes(
    conn: sqlite3.Connection, markdown_snapshot: SnapshotAssertion
) -> None:
    first = run(conn, RunKind.IMPLEMENT, RunStatus.FAILED)
    second = run(conn, RunKind.FIX_CI, RunStatus.DONE)
    run(conn, RunKind.RESUME, RunStatus.DONE)
    note(
        conn,
        first,
        "cause-ci-timeout",
        "CI times out in the integration job. Evidence: test_sync_large hangs past 600s. Next: mark it slow.",
        head="repo@1a2b3c4",
        status="superseded",
    )
    note(
        conn,
        second,
        "cause-ci-timeout",
        "The integration job waits on a lock. Evidence: src/sync.py:88. Next: release it in teardown.",
        head="repo@5d6e7f8",
    )
    note(
        conn,
        first,
        "dead-end-mock-clock",
        "Mocking the clock\u200b does not help. Evidence: the test still hangs. Next: skip this approach.",
    )
    assert memory.ticket_digest(conn, KEY).text == markdown_snapshot


def test_the_ticket_digest_of_a_ticket_without_notes(
    conn: sqlite3.Connection, markdown_snapshot: SnapshotAssertion
) -> None:
    run(conn, RunKind.IMPLEMENT, RunStatus.DONE)
    assert memory.ticket_digest(conn, KEY).text == markdown_snapshot


@pytest.mark.parametrize(
    ("repos", "cite"), [(("api",), True), (("web",), False)], ids=["a-run-in-api-that-cites", "a-plan-in-web"]
)
def test_the_lessons_digest(
    conn: sqlite3.Connection, markdown_snapshot: SnapshotAssertion, repos: tuple[str, ...], *, cite: bool
) -> None:
    lesson(conn, "tests-need-docker", "Start Docker before the tests. Why: they fail without it. When: any test run.")
    lesson(conn, "api-schema-first", "Change the schema before the client. Why: CI checks it. When: API work.", "api")
    conn.execute(
        "INSERT INTO memories (scope, ticket_key, key, body, status, author, run_id, created_at) "
        "VALUES ('proposal', ?, 'pending-one', 'Never shown: a proposal waits on the operator.', 'pending', "
        "'worker', ?, '2026-10-16T09:00:00Z')",
        (KEY, run(conn, RunKind.IMPLEMENT, RunStatus.DONE)),
    )
    assert memory.lessons_digest(conn, repos, cite=cite).text == markdown_snapshot


def run(conn: sqlite3.Connection, kind: RunKind, status: RunStatus) -> int:
    """A run of `KEY` that ended `status`."""
    with in_tick(conn) as tick_id:
        db.touch_ticket(conn, KEY, "repo")
        run_id = db.insert_run(
            conn, tick_id=tick_id, key=KEY, kind=kind, branch="agent/PROJ-1-work", slots=(), runs_dir=Path("/runs")
        )
        conn.execute("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))
    return run_id


def note(
    conn: sqlite3.Connection, run_id: int, key: str, body: str, *, head: str | None = None, status: str = "active"
) -> None:
    """A note of `KEY` that run `run_id` wrote."""
    conn.execute(
        "INSERT INTO memories (scope, ticket_key, key, body, status, author, run_id, head, created_at) "
        "VALUES ('ticket', ?, ?, ?, ?, 'worker', ?, ?, '2026-10-16T09:00:00Z')",
        (KEY, key, body, status, run_id, head),
    )


def lesson(conn: sqlite3.Connection, key: str, body: str, repo: str | None = None) -> None:
    """A lesson in force, as the operator promoted it."""
    conn.execute(
        "INSERT INTO memories (scope, repo, key, body, status, author, created_at, approved_at) "
        "VALUES ('lesson', ?, ?, ?, 'active', 'operator', '2026-10-16T09:00:00Z', '2026-10-16T09:00:00Z')",
        (repo, key, body),
    )
