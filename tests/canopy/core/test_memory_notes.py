"""Ticket notes at `record` (DESIGN §28, ROADMAP M50 stage 1): workers write, and no agent reads what they wrote."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

import pydantic
import pytest

from canopy.cli.main import main
from canopy.core import db, memory, prompts
from canopy.core.config import load
from canopy.core.vocab import MemoryMode, MemoryStatus, ResumeReason, RunKind, RunStatus
from canopy.runs import worker
from tests.canopy.helpers import (
    BRANCH,
    KEY,
    PROMPT_VALUES,
    agent_runs,
    in_run,
    in_tick,
    memories,
    present,
    ticket_sets,
    with_memory,
    worker_does,
    worker_result,
)
from tests.canopy.scenario_helpers import Ran, Scenario, dispatches, pushes

if TYPE_CHECKING:
    from pydantic import JsonValue

    from tests.conftest import CanopyEnv, GitPool

#: The overseer dispatches KEY's implement on its `work` branch.
WORK = dispatches(slug="work")
#: The overseer dispatches a resume of KEY to fix CI.
FIX_CI = dispatches(kind=RunKind.RESUME, reasons=[ResumeReason.CI])
#: Ticket notes at `record`, in the workspace's private file.
RECORDING = {"ticket_notes": "record"}
NOTE = "The lint job fails on a cold cache: run `make lint` twice before trusting it."
#: What the run's note says when its `result` tool took no result.
NO_RESULT = "the worker reported no result"


@pytest.mark.parametrize(
    "sent",
    [{"notes": [{"key": "lint", "text": NOTE}]}, {"proposals": [{"key": "x", "text": "y"}]}],
    ids=["notes", "proposals"],
)
def test_with_memory_off_a_note_a_worker_sends_is_stored_nowhere(
    scenario: Scenario,
    git_pool: GitPool,
    agent_log: Path,
    sent: dict[str, object],
) -> None:
    """A run no tier reaches is asked for no memory field, so its tool refuses a result that carries one."""
    conn = scenario.conn
    run = scenario.run(WORK, worker=pushes(**sent))
    assert not set(memory.GROUPS) & set(asked_of(agent_log))
    assert (run.status, harness_note(run)) == (RunStatus.UNKNOWN, NO_RESULT)
    assert memories(conn) == []
    assert memory.run_memory(conn, run.id) is None
    assert "notes" not in str(run.row["result_json"])
    assert conn.execute("SELECT count(*) FROM memory_reads").fetchone()[0] == 0


def test_at_record_a_note_is_stored_and_reaches_no_prompt(
    scenario: Scenario,
    git_pool: GitPool,
    agent_log: Path,
) -> None:
    scenario.configures("private", memory=RECORDING)
    first = scenario.run(WORK, worker=pushes(notes=[{"key": "lint", "text": f"  {NOTE} "}]))
    [note] = memories(scenario.conn)
    assert (note.ticket_key, note.key, note.body, note.status) == (KEY, "lint", NOTE, MemoryStatus.ACTIVE)
    assert (note.run_id, note.tick_id, note.author) == (first.id, first.row["tick_id"], "worker")
    assert note.head is not None
    assert len(note.head) == 12
    assert "notes" not in str(first.row["result_json"])
    # The run's `result` tool asked for notes, and the next one's does too, without serving the one written.
    assert "notes" in asked_of(agent_log)
    text = scenario.run(FIX_CI).prompt
    assert "notes" in asked_of(agent_log)
    assert NOTE not in text
    assert "## Notes from earlier runs" not in text


def test_at_record_a_run_is_journaled_with_its_modes_and_no_ids(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures("private", memory=RECORDING)
    scenario.run(WORK, worker=pushes(notes=[{"key": "lint", "text": NOTE}]))
    second = scenario.run(FIX_CI, worker=pushes())
    rendered = present(memory.run_memory(scenario.conn, second.id))
    assert (rendered.ticket_notes, rendered.proposals) == (MemoryMode.RECORD, MemoryMode.OFF)
    assert memory.read_by(scenario.conn, second.id) == []


@pytest.mark.parametrize("field", ["memory_used", "memory_wrong", "drop_notes"])
def test_at_record_what_only_use_asks_for_is_refused_and_changes_nothing(
    scenario: Scenario,
    git_pool: GitPool,
    agent_log: Path,
    field: str,
) -> None:
    """A run shown no note is asked to cite and to drop none: its tool refuses a result that does."""
    scenario.configures("private", memory=RECORDING)
    scenario.run(WORK, worker=pushes(notes=[{"key": "lint", "text": NOTE}]))
    [note] = memories(scenario.conn)
    run = scenario.run(FIX_CI, worker=pushes(**{field: ["lint"] if field == "drop_notes" else [note.id]}))
    assert not {"cited", "drop_notes"} & set(asked_of(agent_log))
    assert (run.status, harness_note(run)) == (RunStatus.UNKNOWN, NO_RESULT)
    [after] = memories(scenario.conn)
    assert after == note


def test_at_record_the_journal_drops_what_only_use_asks_for(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> None:
    """Behind the tool, the write itself changes nothing for a field the run's modes did not ask for."""
    first = recording_run(canopy_env, conn)
    memory.record_run(conn, first, memory.Fields(notes=[{"key": "lint", "text": NOTE}]), head=None)
    [note] = memories(conn)
    fields = memory.Fields(memory_used=[note.id], memory_wrong=[note.id], drop_notes=["lint"])
    assert memory.record_run(conn, recording_run(canopy_env, conn), fields, head=None) == []
    [after] = memories(conn)
    assert after == note


def test_a_note_under_a_key_supersedes_the_one_before_it(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures("private", memory=RECORDING)
    scenario.run(WORK, worker=pushes(notes=[{"key": "lint", "text": NOTE}]))
    scenario.run(FIX_CI, worker=pushes(notes=[{"key": "lint", "text": "The lint job is fixed on main."}]))
    old, new = memories(scenario.conn)
    assert (old.status, old.why) == (MemoryStatus.SUPERSEDED, f"superseded by note {new.id}")
    assert old.body == NOTE
    assert (new.status, new.supersedes, new.body) == (MemoryStatus.ACTIVE, old.id, "The lint job is fixed on main.")


def test_notes_from_a_failed_run_are_kept(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures("private", memory=RECORDING)
    line = worker_result(notes=[{"key": "dead-end", "text": "Pinning the parser does not help."}])
    run = scenario.run(WORK, worker=worker_does(result=line.replace('"done"', '"failed"', 1)))
    assert run.status == "failed"
    assert [n.key for n in memories(scenario.conn)] == ["dead-end"]


@pytest.mark.parametrize(
    "named",
    [
        {"ticket": "OTHER-9", "notes": [{"key": "lint", "text": NOTE}]},
        {"notes": [{"key": "lint", "text": NOTE, "ticket": "OTHER-9"}]},
    ],
    ids=["the-result", "the-note"],
)
def test_a_result_cannot_name_a_notes_ticket(named: dict[str, object]) -> None:
    """A note is its own run's ticket's: the tool's input has no field that names another."""
    asked = worker.WORKER.input(["notes"])
    asked.model_validate({"status": "done", "notes": [{"key": "lint", "text": NOTE}]})
    with pytest.raises(pydantic.ValidationError, match="ticket"):
        asked.model_validate({"status": "done", **named})


def test_a_note_is_its_own_runs_tickets_whatever_the_fields_name(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
) -> None:
    """Behind the tool, the write takes the ticket from the run's row, whatever an entry names."""
    run_id = recording_run(canopy_env, conn)
    fields = memory.Fields(notes=[{"key": "lint", "text": NOTE, "ticket": "OTHER-9"}])
    assert memory.record_run(conn, run_id, fields, head=None) == []
    assert [n.ticket_key for n in memories(conn)] == [KEY]


def test_entries_past_the_bounds_are_refused_alone_and_recorded(scenario: Scenario, git_pool: GitPool) -> None:
    conn = scenario.conn
    scenario.configures("private", memory=RECORDING)
    first = scenario.run(
        WORK,
        worker=pushes(
            notes=[
                {"key": "lint", "text": NOTE},
                {"key": "Not A Slug", "text": "fine text"},
                {"key": "bidi", "text": "safe \u202eevil"},
                {"key": "zero-width", "text": "a\u200bb"},
                {"key": "secret", "text": "use token=ghp_abcdefghijklmnopqrstuvwxyz0123456789"},
            ],
        ),
    )
    second = scenario.run(
        FIX_CI,
        worker=pushes(
            notes=[
                {"key": "long", "text": "x" * 401},
                {"key": "repeat", "text": f"  {NOTE.upper()}"},
                {"key": "Third One", "text": "Three."},
                {"key": "fourth", "text": "Four."},
                {"key": "fifth", "text": "Five."},
                {"key": "sixth", "text": "Past the cap."},
            ],
        ),
    )
    lint = memories(conn)[0]
    assert [n.key for n in memories(conn)] == ["lint", "fourth", "fifth"]
    assert refusals(conn, first.id) == [
        ("notes", None, "its key is not lowercase words joined by hyphens, at most 40 characters"),
        ("notes", "bidi", "its text holds U+202E (RIGHT-TO-LEFT OVERRIDE), a character that hides text"),
        ("notes", "zero-width", "its text holds U+200B (ZERO WIDTH SPACE), a character that hides text"),
        ("notes", "secret", "its text looks like it holds a secret"),
    ]
    assert refusals(conn, second.id) == [
        ("notes", "long", "its text is 401 characters, over 400"),
        ("notes", "repeat", f"it repeats note {lint.id}"),
        ("notes", None, "its key is not lowercase words joined by hyphens, at most 40 characters"),
        ("notes", "sixth", "past the 5 notes a run may write"),
    ]


def test_a_note_keeps_its_line_breaks_and_each_line_is_quoted(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures("private", memory=RECORDING)
    text = "The lint job fails on a cold cache.\nEvidence: `make lint` twice.\nNext: run it twice."
    scenario.run(WORK, worker=pushes(notes=[{"key": "lint", "text": text}]))
    [note] = memories(scenario.conn)
    assert note.body == text
    digest = memory.ticket_digest(scenario.conn, KEY).text
    assert "\n> The lint job fails on a cold cache.\n> Evidence: `make lint` twice.\n> Next: run it twice." in digest
    listed = scenario.operator("memory", "list").out
    assert "\n      The lint job fails on a cold cache.\n      Evidence: `make lint` twice.\n" in listed
    assert "<U+000A>" not in listed


def refusals(conn: sqlite3.Connection, run_id: int) -> list[tuple[str, str | None, str]]:
    rendered = present(memory.run_memory(conn, run_id))
    return [(r.field, r.key, r.why) for r in memory.refused_of(rendered)]


#: Notes of the wrong shape: not a list, and an entry that is not an object of a key and a text.
MISSHAPEN: list[JsonValue] = [
    {"key": "lint", "text": NOTE},
    ["not an object"],
    [{"key": "lint"}],
    [{"key": "lint", "text": 7}],
]


@pytest.mark.parametrize("notes", MISSHAPEN, ids=["not-a-list", "not-an-object", "no-text", "text-not-a-string"])
def test_the_tool_refuses_notes_of_the_wrong_shape(scenario: Scenario, git_pool: GitPool, notes: JsonValue) -> None:
    """The run's tool holds each note to its shape, so the worker is told while it can still send it again."""
    with pytest.raises(pydantic.ValidationError, match="notes"):
        worker.WORKER.input(["notes"]).model_validate({"status": "done", "notes": notes})
    # A worker that never sends it right reported no result, and wrote nothing.
    scenario.configures("private", memory=RECORDING)
    run = scenario.run(WORK, worker=pushes(notes=notes))
    assert (run.status, harness_note(run)) == (RunStatus.UNKNOWN, NO_RESULT)
    assert memories(scenario.conn) == []


def test_behind_the_tool_notes_of_the_wrong_shape_are_refused_alone(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
) -> None:
    """The write checks each entry itself, whatever the tool let through: a bad one costs only itself."""
    run_id = recording_run(canopy_env, conn)
    assert [
        (r.field, r.why) for r in memory.record_run(conn, run_id, memory.Fields(notes=MISSHAPEN[0]), head=None)
    ] == [
        ("notes", "`notes` is not a list"),
    ]
    assert memories(conn) == []
    fields = memory.Fields(notes=["not an object", {"key": "lint"}, {"key": "lint", "text": NOTE}])
    assert [
        (r.field, r.key, r.why) for r in memory.record_run(conn, recording_run(canopy_env, conn), fields, head=None)
    ] == [
        ("notes", None, "it is not an object with a key and a text"),
        ("notes", "lint", "its text is not a string"),
    ]
    assert [n.key for n in memories(conn)] == ["lint"]
    assert refusals(conn, run_id) == [("notes", None, "`notes` is not a list")]


def recording_run(canopy_env: CanopyEnv, conn: sqlite3.Connection) -> int:
    """An implement of KEY rendered with ticket notes at `record`, at work, for a test of the write behind the tool."""
    with_memory(canopy_env, ticket_notes="record")
    rendered = present(
        memory.render(conn, load(canopy_env.root, canopy_env.user_file), key=KEY, kind="implement", repos=("repo",)),
    )
    with in_tick(conn) as tick_id:
        db.touch_ticket(conn, KEY, "repo")
        run_id = db.insert_run(
            conn,
            tick_id=tick_id,
            key=KEY,
            kind=RunKind.IMPLEMENT,
            branch=BRANCH,
            slots=(),
            runs_dir=Path("/runs"),
        )
        memory.record_rendered(conn, run_id, rendered)
    return run_id


def asked_of(agent_log: Path) -> list[str]:
    """The groups of fields the latest agent run's `result` tool asked for, as canopy told its run."""
    _, _, groups = str(agent_runs(agent_log)[-1]["env"]["CANOPY_RESULT"]).partition(":")
    return groups.split(",") if groups else []


def harness_note(run: Ran) -> str | None:
    """What the harness said of how `run` ended, in its recorded result."""
    note: str | None = json.loads(run.row["result_json"] or "{}").get("harness")
    return note


@pytest.mark.parametrize(
    ("kind", "private"),
    [(k, False) for k in prompts.WORKER] + [(k, True) for k in prompts.WORKER_PRIVATE],
)
def test_at_record_each_prompt_is_its_off_self(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    kind: str,
    *,
    private: bool,
) -> None:
    """While a tier records, the prompt carries nothing of memory: the run's `result` tool alone asks for notes."""
    values = {
        **PROMPT_VALUES,
        "AUTHORIZATION": prompts.plan_authorization(["agent-ready-alice"], private=False),
        "PLAN_FILE": ".canopy-plan.md",
        "PLAN_OUT": ".canopy-new-plan.md",
        "MAX_PLAN_CHARS": "100,000",
        "CONVERSATION": "No messages yet.",
    }
    off = prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, values, private=private)
    with_memory(canopy_env, ticket_notes="record")
    cfg = load(canopy_env.root, canopy_env.user_file)
    rendered = memory.render(conn, cfg, key=KEY, kind=kind, repos=("repo",))
    if kind not in memory.NOTE_KINDS:
        assert rendered is None
        return
    assert rendered is not None
    assert (rendered.values, rendered.required) == ({}, ())
    assert prompts.render_worker(cfg, kind, values, private=private, required=rendered.required) == off
    # What the prompt no longer says, the tool's input does: the notes, and nothing only `use` asks for.
    groups = memory.asked_groups(rendered.modes)
    assert groups == ["notes"]
    added = set(worker.WORKER.input(groups).model_fields) - set(worker.WORKER.input().model_fields)
    assert added == {"notes"}


def test_an_override_from_before_memory_serves_while_a_tier_records(
    scenario: Scenario,
    git_pool: GitPool,
    agent_log: Path,
) -> None:
    """The fields memory asks for are the tool's, so a prompt that never heard of memory still has its notes written."""
    overrides = scenario.env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("Work on {{KEY}}, labels {{LABELS}}.\n{{DRAFTS}}\n")
    scenario.configures("private", memory=RECORDING)
    run = scenario.run(WORK, worker=pushes(notes=[{"key": "lint", "text": NOTE}]))
    assert run.prompt.startswith(f"Work on {KEY}, labels ")
    assert "notes" in asked_of(agent_log)
    assert [n.key for n in memories(scenario.conn)] == ["lint"]


@pytest.mark.parametrize("how", ["done", "forget"])
def test_done_and_forget_invalidate_a_tickets_notes(scenario: Scenario, git_pool: GitPool, how: str) -> None:
    scenario.configures("private", memory=RECORDING)
    scenario.run(WORK, worker=pushes(notes=[{"key": "lint", "text": NOTE}]))
    if how == "done":
        scenario.overseer(ticket_sets(KEY, done=True))
        why = "ticket done"
    else:
        scenario.operator("forget", KEY)
        why = "forgotten work"
    [note] = memories(scenario.conn)
    assert (note.status, note.why, note.body) == (MemoryStatus.INVALID, why, NOTE)
    assert note.invalidated_at is not None


def hand_written(conn: sqlite3.Connection, body: str, *, key: str = "hand") -> int:
    """A note written to the journal by hand, past the bounds, for the surfaces' tests."""
    with in_tick(conn) as tick_id:
        db.touch_ticket(conn, KEY, "repo")
        run_id = db.insert_run(
            conn,
            tick_id=tick_id,
            key=KEY,
            kind=RunKind.IMPLEMENT,
            branch=BRANCH,
            slots=(),
            runs_dir=Path("/runs"),
        )
        cur = conn.execute(
            "INSERT INTO memories (scope, ticket_key, key, body, status, author, run_id, tick_id, created_at) "
            "VALUES ('ticket', ?, ?, ?, 'active', 'worker', ?, ?, 'x')",
            (KEY, key, body, run_id, tick_id),
        )
    return int(cur.lastrowid or 0)


def test_memory_list_says_the_mode_first_and_shows_what_a_worker_wrote_plainly(scenario: Scenario) -> None:
    scenario.configures("private", memory=RECORDING)
    hand_written(scenario.conn, "See [the fix](https://evil.test) \u202eeht\u202c and\u200bthis\x1b[2J.")
    out = scenario.operator("memory", "list").out
    assert out.startswith(
        "ticket notes: Recording only. Workers write these notes; no run reads them.\n"
        "lessons: Off. Workers propose no lessons, and no run reads them.\n",
    )
    assert "See [the fix](https://evil.test) <U+202E>eht<U+202C> and<U+200B>this<U+001B>[2J." in out
    assert "read by no run" in out
    assert "\u202e" not in out
    assert "\x1b" not in out


def test_memory_list_of_a_run_says_it_read_nothing_while_recording(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures("private", memory=RECORDING)
    run = scenario.run(WORK, worker=pushes(notes=[{"key": "lint", "text": NOTE}, {"key": "Bad", "text": "x"}]))
    out = scenario.operator("memory", "list", "--run", str(run.id)).out
    assert f"Run {run.id} (implement of {KEY}), rendered with ticket notes recording, lessons off." in out
    assert NOTE in out
    assert "Read: none, recording only" in out
    assert "Refused:\n  notes: its key is not lowercase words joined by hyphens" in out


def test_memory_list_prints_the_digest_that_would_be_served(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures("private", memory=RECORDING)
    run = scenario.run(WORK, worker=pushes(notes=[{"key": "lint", "text": NOTE}]))
    [note] = memories(scenario.conn)
    out = scenario.operator("memory", "list", KEY, "--digest").out
    assert f"{KEY}'s notes, would be served at use:\n\n## Notes from earlier runs\n\n" in out
    assert (
        f"Note {note.id}, `lint`, from run {run.id} (`implement`, ended `done`), 1 run before this one, "
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


def test_ticket_notes_counts_each_tickets_notes_in_force_the_newest_first(conn: sqlite3.Connection) -> None:
    used, _, replaced = (hand_written(conn, f"note {i}", key=f"k{i}") for i in range(3))
    conn.execute("UPDATE memories SET use_count = 2 WHERE id = ?", (used,))
    conn.execute("UPDATE memories SET status = 'superseded' WHERE id = ?", (replaced,))
    # Another ticket's, written after: its row comes first.
    conn.execute(
        "INSERT INTO tickets (key, repo, title, first_seen_at, last_seen_at) "
        "VALUES ('PROJ-2', 'repo', 'Later', 'x', 'x')",
    )
    conn.execute(
        "INSERT INTO memories (scope, ticket_key, key, body, status, author, run_id, created_at) "
        "SELECT 'ticket', 'PROJ-2', 'later', 'A later note.', 'active', 'worker', run_id, 'y' "
        "FROM memories WHERE id = ?",
        (used,),
    )
    assert memory.ticket_notes(conn) == [
        memory.TicketNotes("PROJ-2", count=1, used=0, latest_at="y", title="Later"),
        memory.TicketNotes(KEY, count=2, used=1, latest_at="x"),
    ]


@pytest.mark.parametrize("args", [["forget", "1"], ["purge", "--all"]])
def test_forget_and_purge_refuse_inside_a_run(canopy_env: CanopyEnv, args: list[str]) -> None:
    with_memory(canopy_env, ticket_notes="record")
    with in_run(7):
        assert main(["memory", *args]) == 1


@pytest.mark.parametrize("args", [["forget"], ["purge", "--ticket", KEY], ["purge", "--all"]])
def test_forget_and_purge_leave_no_text_in_the_journal_file(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    args: list[str],
) -> None:
    leaked = "the staging password is hunter2-but-longer"
    note_id = hand_written(conn, leaked)
    assert main(["memory", *args, *([str(note_id)] if args == ["forget"] else [])]) == 0
    [note] = memories(conn)
    assert (note.body, note.status) == (None, MemoryStatus.INVALID)
    files = [canopy_env.state_dir / name for name in ("canopy.db", "canopy.db-wal")]
    for path in files:
        if path.exists():
            assert leaked.encode() not in path.read_bytes(), path
