"""Ticket notes at `use` (DESIGN §28, ROADMAP M50 stage 1): a ticket's later runs read its notes, as data."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from canopy.cli.main import main
from canopy.core import memory, records
from canopy.core.vocab import MemoryStatus
from tests.canopy.helpers import (
    KEY,
    WORK,
    InlineRunner,
    commit_and_push,
    dispatch_and_run,
    dispatch_in_tick,
    dispatch_refused,
    last_run,
    prompt_of,
    with_memory,
    worker_does,
    worker_result,
)

if TYPE_CHECKING:
    from tests.conftest import CanopyEnv

BRANCH = f"agent/{KEY}-work"
FIX_CI = ("--label", "agent-ready-tester", "--kind", "fix-ci")
NOTE = "The lint job fails on a cold cache: run `make lint` twice before trusting it."
HEADING = "## Notes from earlier runs\n\n"
OTHER = "PROJ-2"

pytestmark = pytest.mark.usefixtures("git_pool")


def stored(conn: sqlite3.Connection) -> list[records.Memory]:
    return records.fetch_all(conn, records.Memory, "SELECT * FROM memories ORDER BY id")


def run_with(conn: sqlite3.Connection, *args: str, key: str = KEY, **fields: object) -> sqlite3.Row:
    """Dispatch and run `key`'s next run with `args`, its worker committing, pushing, and sending `fields`."""
    branch = f"agent/{key}-work"
    line = worker_result(**fields).replace(BRANCH, branch)
    with worker_does(*commit_and_push(branch), result=line):
        return dispatch_and_run(conn, *args, key=key, runner=InlineRunner())


def test_a_note_reaches_its_tickets_next_run_and_no_other_tickets(
    canopy_env: CanopyEnv, conn: sqlite3.Connection
) -> None:
    with_memory(canopy_env, ticket_notes="use")
    first = run_with(conn, *WORK, notes=[{"key": "lint", "text": NOTE}])
    assert f"{HEADING}Notes this ticket's earlier runs wrote" in prompt_of(canopy_env, int(first["id"]))
    assert "None: no earlier run of this ticket left a note." in prompt_of(canopy_env, int(first["id"]))
    [note] = stored(conn)

    assert dispatch_in_tick(conn, *FIX_CI).code == 0
    run_id = int(last_run(conn)["id"])
    text = prompt_of(canopy_env, run_id)
    assert (
        f"Note {note.id}, `lint`, from run {first['id']} (`implement`, ended `done`), 1 run before this one, "
        f"against `{note.head}`:\n> {NOTE}"
    ) in text
    assert '`"drop_notes":["<key>"]`' in text
    assert '`"memory_used":[<id>]` and `"memory_wrong":[<id>]`' in text
    assert [m.id for m in memory.read_by(conn, run_id)] == [note.id]

    assert dispatch_in_tick(conn, *WORK, key=OTHER).code == 0
    other = prompt_of(canopy_env, int(last_run(conn)["id"]))
    assert NOTE not in other
    assert "None: no earlier run of this ticket left a note." in other


def test_a_note_recorded_at_record_is_served_once_the_tier_is_in_use(
    canopy_env: CanopyEnv, conn: sqlite3.Connection
) -> None:
    with_memory(canopy_env, ticket_notes="record")
    run_with(conn, *WORK, notes=[{"key": "lint", "text": NOTE}])
    with_memory(canopy_env, ticket_notes="use")
    assert dispatch_in_tick(conn, *FIX_CI).code == 0
    assert f"> {NOTE}" in prompt_of(canopy_env, int(last_run(conn)["id"]))


def test_a_run_renews_drops_and_retires_only_what_it_was_shown(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    with_memory(canopy_env, ticket_notes="use")
    run_with(conn, *WORK, key=OTHER, notes=[{"key": "theirs", "text": "Another ticket's note."}])
    run_with(
        conn,
        *WORK,
        notes=[
            {"key": "lint", "text": NOTE},
            {"key": "stale", "text": "The API test is skipped on main."},
            {"key": "cause", "text": "The cache key leaves out the lockfile."},
        ],
    )
    theirs, lint, stale, cause = stored(conn)
    run_with(
        conn,
        *FIX_CI,
        memory_used=[lint.id, cause.id, theirs.id, "x", True],
        memory_wrong=[cause.id, theirs.id, 99_999],
        drop_notes=["stale", "theirs", "never-shown"],
    )
    by_id = {m.id: m for m in stored(conn)}
    assert (by_id[lint.id].use_count, by_id[lint.id].status) == (1, MemoryStatus.ACTIVE)
    assert by_id[lint.id].last_used_at is not None
    assert (by_id[stale.id].status, by_id[stale.id].why) == (
        MemoryStatus.INVALID,
        f"dropped by run {last_run(conn)['id']}",
    )
    # Reported wrong wins over used, and the note is retired.
    assert (by_id[cause.id].status, by_id[cause.id].use_count) == (MemoryStatus.INVALID, 0)
    assert by_id[cause.id].why == f"wrong, says run {last_run(conn)['id']}"
    # Another ticket's note was never in this run's prompt: nothing it sent touches it.
    assert by_id[theirs.id] == theirs


def test_a_note_written_at_use_supersedes_by_key(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    with_memory(canopy_env, ticket_notes="use")
    run_with(conn, *WORK, notes=[{"key": "lint", "text": NOTE}])
    run_with(conn, *FIX_CI, notes=[{"key": "lint", "text": "Fixed on main; lint is reliable again."}])
    old, new = stored(conn)
    assert (old.status, new.status, new.supersedes) == (MemoryStatus.SUPERSEDED, MemoryStatus.ACTIVE, old.id)
    assert dispatch_in_tick(conn, *WORK).code == 0
    text = prompt_of(canopy_env, int(last_run(conn)["id"]))
    assert "Fixed on main; lint is reliable again." in text
    assert NOTE not in text


def test_at_use_an_override_without_the_notes_is_refused(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("Work on {{KEY}}, labels {{LABELS}}.\n{{MEMORY_CONTRACT}}\n")
    with_memory(canopy_env, ticket_notes="record")
    assert dispatch_in_tick(conn, *WORK).code == 0
    conn.execute("UPDATE runs SET status = 'crashed', ended_at = 'x' WHERE status = 'running'")
    with_memory(canopy_env, ticket_notes="use")
    [(action, rationale)] = dispatch_refused(conn, *WORK)[-1:]
    assert action == "refused:bad_prompt"
    assert "missing required placeholder {{TICKET_MEMORY}}" in rationale


def test_memory_list_says_the_digest_is_served_and_what_a_run_read(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    with_memory(canopy_env, ticket_notes="use")
    run_with(conn, *WORK, notes=[{"key": "lint", "text": NOTE}])
    second = run_with(conn, *FIX_CI, memory_used=[stored(conn)[0].id])
    capsys.readouterr()
    assert main(["memory", "list", KEY, "--digest"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("ticket notes: in use. In use. A ticket's later runs read its notes.\n")
    assert f"{KEY}'s notes, served to its next run:" in out
    assert main(["memory", "list", "--run", str(second["id"])]) == 0
    out = capsys.readouterr().out
    assert "Read:\n" in out
    assert "used by 1 run, last at" in out
