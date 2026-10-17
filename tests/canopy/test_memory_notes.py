"""Ticket notes at `record` (DESIGN §28, ROADMAP M50 stage 1): workers write, and no agent reads what they wrote."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import db, memory, prompts, records
from canopy.core.config import load
from canopy.core.vocab import MemoryMode, MemoryStatus, RunKind
from tests.canopy.helpers import (
    KEY,
    PROMPT_VALUES,
    WORK,
    InlineRunner,
    commit_and_push,
    dispatch_and_run,
    dispatch_in_tick,
    dispatch_refused,
    in_tick,
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
CONTRACT = "That JSON object may also carry these fields"


def stored(conn: sqlite3.Connection) -> list[records.Memory]:
    return records.fetch_all(conn, records.Memory, "SELECT * FROM memories ORDER BY id")


def run_with(conn: sqlite3.Connection, *args: str, **fields: object) -> sqlite3.Row:
    """Dispatch and run KEY's next run with `args`, its worker committing, pushing, and sending `fields`."""
    with worker_does(*commit_and_push(BRANCH), result=worker_result(**fields)):
        return dispatch_and_run(conn, *args, runner=InlineRunner())


@pytest.mark.usefixtures("git_pool")
def test_with_memory_off_a_note_a_worker_sends_is_stored_nowhere(conn: sqlite3.Connection) -> None:
    run = run_with(conn, *WORK, notes=[{"key": "lint", "text": NOTE}], proposals=[{"key": "x", "text": "y"}])
    assert run["status"] == "done"
    assert stored(conn) == []
    assert memory.run_memory(conn, int(run["id"])) is None
    assert "notes" not in str(run["result_json"])
    assert conn.execute("SELECT count(*) FROM memory_reads").fetchone()[0] == 0


@pytest.mark.usefixtures("git_pool")
def test_at_record_a_note_is_stored_and_reaches_no_prompt(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    with_memory(canopy_env, ticket_notes="record")
    first = run_with(conn, *WORK, notes=[{"key": "lint", "text": f"  {NOTE} "}])
    [note] = stored(conn)
    assert (note.ticket_key, note.key, note.body, note.status) == (KEY, "lint", NOTE, MemoryStatus.ACTIVE)
    assert (note.run_id, note.tick_id, note.author) == (first["id"], first["tick_id"], "worker")
    assert note.head is not None
    assert len(note.head) == 12
    assert "notes" not in str(first["result_json"])
    # The run's prompt asked for notes, and the next one does too, without serving the one written.
    assert CONTRACT in prompt_of(canopy_env, int(first["id"]))
    assert dispatch_in_tick(conn, *FIX_CI).code == 0
    text = prompt_of(canopy_env, int(last_run(conn)["id"]))
    assert CONTRACT in text
    assert NOTE not in text
    assert "## Notes from earlier runs" not in text


@pytest.mark.usefixtures("git_pool")
def test_at_record_a_run_is_journaled_with_its_modes_and_no_ids(
    canopy_env: CanopyEnv, conn: sqlite3.Connection
) -> None:
    with_memory(canopy_env, ticket_notes="record")
    run_with(conn, *WORK, notes=[{"key": "lint", "text": NOTE}])
    second = run_with(conn, *FIX_CI)
    rendered = memory.run_memory(conn, int(second["id"]))
    assert rendered is not None
    assert (rendered.ticket_notes, rendered.proposals) == (MemoryMode.RECORD, MemoryMode.OFF)
    assert memory.read_by(conn, int(second["id"])) == []


@pytest.mark.usefixtures("git_pool")
def test_at_record_what_only_use_asks_for_changes_nothing(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    with_memory(canopy_env, ticket_notes="record")
    run_with(conn, *WORK, notes=[{"key": "lint", "text": NOTE}])
    [note] = stored(conn)
    run_with(conn, *FIX_CI, memory_used=[note.id], memory_wrong=[note.id], drop_notes=["lint"])
    [after] = stored(conn)
    assert after == note


@pytest.mark.usefixtures("git_pool")
def test_a_note_under_a_key_supersedes_the_one_before_it(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    with_memory(canopy_env, ticket_notes="record")
    run_with(conn, *WORK, notes=[{"key": "lint", "text": NOTE}])
    run_with(conn, *FIX_CI, notes=[{"key": "lint", "text": "The lint job is fixed on main."}])
    old, new = stored(conn)
    assert (old.status, old.why) == (MemoryStatus.SUPERSEDED, f"superseded by note {new.id}")
    assert old.body == NOTE
    assert (new.status, new.supersedes, new.body) == (MemoryStatus.ACTIVE, old.id, "The lint job is fixed on main.")


@pytest.mark.usefixtures("git_pool")
def test_notes_from_a_failed_run_are_kept(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    with_memory(canopy_env, ticket_notes="record")
    line = worker_result(notes=[{"key": "dead-end", "text": "Pinning the parser does not help."}])
    with worker_does(result=line.replace('"done"', '"failed"', 1)):
        run = dispatch_and_run(conn, *WORK, runner=InlineRunner())
    assert run["status"] == "failed"
    assert [n.key for n in stored(conn)] == ["dead-end"]


@pytest.mark.usefixtures("git_pool")
def test_a_note_is_its_own_runs_tickets_whatever_the_result_names(
    canopy_env: CanopyEnv, conn: sqlite3.Connection
) -> None:
    with_memory(canopy_env, ticket_notes="record")
    run_with(conn, *WORK, ticket="OTHER-9", notes=[{"key": "lint", "text": NOTE, "ticket": "OTHER-9"}])
    assert [n.ticket_key for n in stored(conn)] == [KEY]


@pytest.mark.usefixtures("git_pool")
def test_entries_past_the_bounds_are_refused_alone_and_recorded(
    canopy_env: CanopyEnv, conn: sqlite3.Connection
) -> None:
    with_memory(canopy_env, ticket_notes="record")
    first = run_with(
        conn,
        *WORK,
        notes=[
            {"key": "lint", "text": NOTE},
            {"key": "Not A Slug", "text": "fine text"},
            {"key": "bidi", "text": "safe \u202eevil"},
            {"key": "zero-width", "text": "a\u200bb"},
            {"key": "secret", "text": "use token=ghp_abcdefghijklmnopqrstuvwxyz0123456789"},
        ],
    )
    second = run_with(
        conn,
        *FIX_CI,
        notes=[
            {"key": "long", "text": "x" * 401},
            {"key": "repeat", "text": f"  {NOTE.upper()}"},
            "not an object",
            {"key": "fourth", "text": "Four."},
            {"key": "fifth", "text": "Five."},
            {"key": "sixth", "text": "Past the cap."},
        ],
    )
    lint = stored(conn)[0]
    assert [n.key for n in stored(conn)] == ["lint", "fourth", "fifth"]
    assert refusals(conn, first) == [
        ("notes", None, "its key is not lowercase words joined by hyphens, at most 40 characters"),
        ("notes", "bidi", "its text holds U+202E (RIGHT-TO-LEFT OVERRIDE), a character that hides text"),
        ("notes", "zero-width", "its text holds U+200B (ZERO WIDTH SPACE), a character that hides text"),
        ("notes", "secret", "its text looks like it holds a secret"),
    ]
    assert refusals(conn, second) == [
        ("notes", "long", "its text is 401 characters, over 400"),
        ("notes", "repeat", f"it repeats note {lint.id}"),
        ("notes", None, "it is not an object with a key and a text"),
        ("notes", "sixth", "past the 5 notes a run may write"),
    ]


def refusals(conn: sqlite3.Connection, run: sqlite3.Row) -> list[tuple[str, str | None, str]]:
    rendered = memory.run_memory(conn, int(run["id"]))
    assert rendered is not None
    return [(r.field, r.key, r.why) for r in memory.refused_of(rendered)]


@pytest.mark.usefixtures("git_pool")
def test_notes_that_are_not_a_list_are_refused(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    with_memory(canopy_env, ticket_notes="record")
    run = run_with(conn, *WORK, notes={"key": "lint", "text": NOTE})
    rendered = memory.run_memory(conn, int(run["id"]))
    assert rendered is not None
    assert [(r.field, r.why) for r in memory.refused_of(rendered)] == [("notes", "`notes` is not a list")]
    assert stored(conn) == []


@pytest.mark.parametrize(
    ("kind", "private"), [(k, False) for k in prompts.WORKER] + [(k, True) for k in prompts.WORKER_PRIVATE]
)
def test_at_record_each_prompt_differs_from_its_off_self_by_the_contract_alone(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, kind: str, *, private: bool
) -> None:
    values = {
        **PROMPT_VALUES,
        "AUTHORIZATION": prompts.plan_authorization(KEY, ["agent-ready-alice"], private=False),
        "PLAN_FILE": ".canopy-plan.md",
        "PLAN_OUT": ".canopy-new-plan.md",
        "MAX_PLAN_CHARS": "100,000",
        "CONVERSATION": "No messages yet.",
    }
    off = prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, values, private=private)
    with_memory(canopy_env, ticket_notes="record")
    cfg = load(canopy_env.root, canopy_env.user_file)
    rendered = memory.render(conn, cfg, kind=kind)
    if kind not in memory.NOTE_KINDS:
        assert rendered is None
        return
    assert rendered is not None
    contract = rendered.values[memory.MEMORY_CONTRACT]
    assert contract.startswith("\n\nThat JSON object may also carry these fields")
    assert '`"notes":' in contract
    assert "drop_notes" not in contract
    assert "memory_used" not in contract
    assert "proposals" not in contract
    on = prompts.render_worker(cfg, kind, {**values, **rendered.values}, private=private, required=rendered.required)
    assert on == off.removesuffix("\n") + contract + "\n"


@pytest.mark.usefixtures("git_pool")
def test_an_override_without_the_contract_serves_until_a_tier_records(
    canopy_env: CanopyEnv, conn: sqlite3.Connection
) -> None:
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("Work on {{KEY}}, labels {{LABELS}}.\n")
    assert dispatch_in_tick(conn, *WORK).code == 0
    # Ended, so the next dispatch is refused for its prompt alone.
    conn.execute("UPDATE runs SET status = 'crashed', ended_at = 'x' WHERE status = 'running'")
    with_memory(canopy_env, ticket_notes="record")
    [(action, rationale)] = dispatch_refused(conn, *WORK)[-1:]
    assert action == "refused:bad_prompt"
    assert "missing required placeholder {{MEMORY_CONTRACT}}" in rationale


@pytest.mark.usefixtures("git_pool")
@pytest.mark.parametrize("how", ["done", "forget"])
def test_done_and_forget_invalidate_a_tickets_notes(canopy_env: CanopyEnv, conn: sqlite3.Connection, how: str) -> None:
    with_memory(canopy_env, ticket_notes="record")
    run_with(conn, *WORK, notes=[{"key": "lint", "text": NOTE}])
    if how == "done":
        with in_tick(conn):
            assert main(["ticket", "set", KEY, "--done"]) == 0
        why = "ticket done"
    else:
        assert main(["forget", KEY]) == 0
        why = "forgotten work"
    [note] = stored(conn)
    assert (note.status, note.why, note.body) == (MemoryStatus.INVALID, why, NOTE)
    assert note.invalidated_at is not None


def hand_written(conn: sqlite3.Connection, body: str, *, key: str = "hand") -> int:
    """A note written to the journal by hand, past the bounds, for the surfaces' tests."""
    with in_tick(conn) as tick_id:
        db.touch_ticket(conn, KEY, "repo")
        run_id = db.insert_run(
            conn, tick_id=tick_id, key=KEY, kind=RunKind.IMPLEMENT, branch=BRANCH, slots=(), runs_dir=Path("/runs")
        )
        cur = conn.execute(
            "INSERT INTO memories (scope, ticket_key, key, body, status, author, run_id, tick_id, created_at) "
            "VALUES ('ticket', ?, ?, ?, 'active', 'worker', ?, ?, 'x')",
            (KEY, key, body, run_id, tick_id),
        )
    return int(cur.lastrowid or 0)


def test_memory_list_says_the_mode_first_and_shows_what_a_worker_wrote_plainly(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    with_memory(canopy_env, ticket_notes="record")
    hand_written(conn, "See [the fix](https://evil.test) \u202eeht\u202c and\u200bthis\x1b[2J.")
    assert main(["memory", "list"]) == 0
    out = capsys.readouterr().out
    assert out.startswith(
        "ticket notes: recording. Recording only. Workers write these notes; no run reads them.\nlessons: off.\n"
    )
    assert "See [the fix](https://evil.test) <U+202E>eht<U+202C> and<U+200B>this<U+001B>[2J." in out
    assert "read by no run" in out
    assert "\u202e" not in out
    assert "\x1b" not in out


@pytest.mark.usefixtures("git_pool")
def test_memory_list_of_a_run_says_it_read_nothing_while_recording(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    with_memory(canopy_env, ticket_notes="record")
    run = run_with(conn, *WORK, notes=[{"key": "lint", "text": NOTE}, {"key": "Bad", "text": "x"}])
    assert main(["memory", "list", "--run", str(run["id"])]) == 0
    out = capsys.readouterr().out
    assert f"Run {run['id']} (implement of {KEY}), rendered with ticket notes recording, lessons off." in out
    assert NOTE in out
    assert "Read: none, recording only" in out
    assert "Refused:\n  notes: its key is not lowercase words joined by hyphens" in out


@pytest.mark.usefixtures("git_pool")
def test_memory_list_prints_the_digest_that_would_be_served(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    with_memory(canopy_env, ticket_notes="record")
    run = run_with(conn, *WORK, notes=[{"key": "lint", "text": NOTE}])
    [note] = stored(conn)
    assert main(["memory", "list", KEY, "--digest"]) == 0
    out = capsys.readouterr().out
    assert f"{KEY}'s notes, would be served at use:\n\n## Notes from earlier runs\n\n" in out
    assert (
        f"Note {note.id}, `lint`, from run {run['id']} (`implement`, ended `done`), 1 run before this one, "
        f"against `{note.head}`:\n> {NOTE}"
    ) in out


def test_the_digest_keeps_the_most_recently_used_within_its_cap(conn: sqlite3.Connection) -> None:
    ids = [hand_written(conn, f"note {i} " + "y" * 380, key=f"k{i:02d}") for i in range(12)]
    conn.execute("UPDATE memories SET last_used_at = 'z' WHERE id = ?", (ids[0],))
    digest = memory.ticket_digest(conn, KEY)
    assert ids[0] in digest.ids
    assert ids[1] not in digest.ids
    assert digest.left_out == 12 - len(digest.ids)
    assert f"[{digest.left_out} older notes are left out of this prompt.]" in digest.text
    keys = [line.split("`")[1] for line in digest.text.splitlines() if line.startswith("Note ")]
    assert keys == sorted(keys)
    assert len(digest.text.encode()) < memory.MAX_TICKET_DIGEST + 1024


@pytest.mark.parametrize("args", [["forget", "1"], ["purge", "--all"]])
def test_forget_and_purge_refuse_inside_a_run(canopy_env: CanopyEnv, args: list[str]) -> None:
    with_memory(canopy_env, ticket_notes="record")
    with mock.patch.dict(os.environ, {"CANOPY_RUN_ID": "7"}):
        assert main(["memory", *args]) == 1


@pytest.mark.parametrize("args", [["forget"], ["purge", "--ticket", KEY], ["purge", "--all"]])
def test_forget_and_purge_leave_no_text_in_the_journal_file(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, args: list[str]
) -> None:
    leaked = "the staging password is hunter2-but-longer"
    note_id = hand_written(conn, leaked)
    assert main(["memory", *args, *([str(note_id)] if args == ["forget"] else [])]) == 0
    [note] = stored(conn)
    assert (note.body, note.status) == (None, MemoryStatus.INVALID)
    files = [canopy_env.state_dir / name for name in ("canopy.db", "canopy.db-wal")]
    for path in files:
        if path.exists():
            assert leaked.encode() not in path.read_bytes(), path
