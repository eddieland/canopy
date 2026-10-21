"""Ticket notes at `use` (DESIGN §28, ROADMAP M50 stage 1): a ticket's later runs read its notes, as data."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest

from canopy.cli.main import main
from canopy.core import memory
from canopy.core.vocab import MemoryCited, MemoryStatus
from tests.canopy.helpers import (
    KEY,
    WORK,
    dispatch_in_tick,
    dispatch_refused,
    last_run,
    memories,
    prompt_of,
    run_with,
    with_memory,
)

if TYPE_CHECKING:
    from tests.conftest import CanopyEnv

FIX_CI = ("--label", "agent-ready-tester", "--kind", "resume", "--reason", "ci")
NOTE = "The lint job fails on a cold cache: run `make lint` twice before trusting it."
HEADING = "## Notes from earlier runs\n\n"
OTHER = "PROJ-2"

pytestmark = pytest.mark.usefixtures("git_pool")


def test_a_note_reaches_its_tickets_next_run_and_no_other_tickets(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
) -> None:
    with_memory(canopy_env, ticket_notes="use")
    first = run_with(conn, *WORK, notes=[{"key": "lint", "text": NOTE}])
    # A ticket with no note in force gets no section.
    assert HEADING not in prompt_of(canopy_env, int(first["id"]))
    [note] = memories(conn)

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
    assert HEADING not in other


def test_a_note_recorded_at_record_is_served_once_the_tier_is_in_use(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
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
    theirs, lint, stale, cause = memories(conn)
    run_with(
        conn,
        *FIX_CI,
        memory_used=[lint.id, cause.id, theirs.id, "x", True],
        memory_wrong=[cause.id, theirs.id, 99_999],
        drop_notes=["stale", "theirs", "never-shown"],
    )
    by_id = {m.id: m for m in memories(conn)}
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
    # What it said of each is kept by run, so each memory names the runs that relied on it.
    run_id = int(last_run(conn)["id"])
    assert memory.citations(conn, run_id) == {lint.id: MemoryCited.USED, cause.id: MemoryCited.WRONG}
    assert (memory.used_by(conn, lint.id), memory.used_by(conn, cause.id)) == ([run_id], [])


def test_a_memory_names_the_latest_runs_that_relied_on_it_newest_first(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
) -> None:
    with_memory(canopy_env, ticket_notes="use")
    run_with(conn, *WORK, notes=[{"key": "lint", "text": NOTE}])
    [note] = memories(conn)
    # A resume for review, which no cooldown holds back, so one may follow another.
    resume = (*FIX_CI[:-1], "review")
    relied = [int(run_with(conn, *resume, memory_used=[note.id])["id"]) for _ in range(3)]
    # Shown it, and cited it in neither list: read, but not among those that relied on it.
    quiet = int(run_with(conn, *resume)["id"])
    assert memory.citations(conn, quiet) == {}
    assert memory.used_by(conn, note.id) == relied[::-1]
    assert memory.used_by(conn, note.id, limit=2) == relied[:0:-1]


def test_a_note_written_at_use_supersedes_by_key(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    with_memory(canopy_env, ticket_notes="use")
    run_with(conn, *WORK, notes=[{"key": "lint", "text": NOTE}])
    run_with(conn, *FIX_CI, notes=[{"key": "lint", "text": "Fixed on main; lint is reliable again."}])
    old, new = memories(conn)
    assert (old.status, new.status, new.supersedes) == (MemoryStatus.SUPERSEDED, MemoryStatus.ACTIVE, old.id)
    assert dispatch_in_tick(conn, *WORK).code == 0
    text = prompt_of(canopy_env, int(last_run(conn)["id"]))
    assert "Fixed on main; lint is reliable again." in text
    assert NOTE not in text


def test_at_use_an_override_without_the_notes_is_refused(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text(
        "Work on {{KEY}}, labels {{LABELS}}.\n{{MEMORY_CONTRACT}}{{DRAFTS}}\n",
    )
    with_memory(canopy_env, ticket_notes="record")
    assert dispatch_in_tick(conn, *WORK).code == 0
    conn.execute("UPDATE runs SET status = 'crashed', ended_at = 'x' WHERE status = 'running'")
    with_memory(canopy_env, ticket_notes="use")
    [(action, rationale)] = dispatch_refused(conn, *WORK)[-1:]
    assert action == "refused:bad_prompt"
    assert "missing required placeholder {{TICKET_MEMORY}}" in rationale


def test_memory_list_says_the_digest_is_served_and_what_a_run_read(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with_memory(canopy_env, ticket_notes="use")
    run_with(conn, *WORK, notes=[{"key": "lint", "text": NOTE}])
    second = run_with(conn, *FIX_CI, memory_used=[memories(conn)[0].id])
    capsys.readouterr()
    assert main(["memory", "list", KEY, "--digest"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("ticket notes: In use. A ticket's later runs read its notes.\n")
    assert f"{KEY}'s notes, served to its next run:" in out
    assert main(["memory", "list", "--run", str(second["id"])]) == 0
    out = capsys.readouterr().out
    assert "Read:\n" in out
    assert "read by 1 run (last at " in out
    assert "cited by 1 (last at " in out


def test_the_listings_count_the_runs_that_read_a_note_apart_from_those_that_cited_it(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with_memory(canopy_env, ticket_notes="use")
    run_with(conn, *WORK, notes=[{"key": "lint", "text": NOTE}])
    [note] = memories(conn)
    # A resume for review, which no cooldown holds back, so one may follow another.
    resume = (*FIX_CI[:-1], "review")
    run_with(conn, *resume, memory_used=[note.id])
    # Shown it and silent on it: a worker may rely on a note and leave `memory_used` unsaid, so these count as reads.
    quiet = [run_with(conn, *resume) for _ in range(2)]
    [cited] = memories(conn)
    use = f"read by 3 runs (last at {quiet[-1]['started_at']}), cited by 1 (last at {cited.last_used_at})"
    capsys.readouterr()
    for args in (
        ["memory", "list"],
        ["memory", "history", str(note.id)],
        ["memory", "list", "--run", str(quiet[0]["id"])],
    ):
        assert main(args) == 0
        assert use in capsys.readouterr().out
    assert main(["memory", "list", "--json"]) == 0
    [found] = json.loads(capsys.readouterr().out)["notes"]
    assert {k: found[k] for k in ("read_count", "last_read_at", "use_count", "last_used_at")} == {
        "read_count": 3,
        "last_read_at": quiet[-1]["started_at"],
        "use_count": 1,
        "last_used_at": cited.last_used_at,
    }
