"""Agent memory in the web API (DESIGN §28, ROADMAP M50): each tier's mode in words, and what it holds, read only."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import db
from canopy.core.vocab import RunKind
from canopy.infra import resources
from tests.canopy.helpers import BRANCH, KEY, context, in_tick, with_memory
from tests.canopy.web_helpers import at, client, signed_in_client

if TYPE_CHECKING:
    from canopy.core.context import Context
    from canopy.serve.backend import Backend
    from tests.conftest import CanopyEnv


def test_the_loop_state_names_each_tiers_mode_in_words(backend: Backend) -> None:
    state = client(None, backend).get("/api/loop").json()["memory"]
    assert state == {
        "readout": "memory: in use",
        "tiers": "ticket notes: in use, lessons: recording",
        "ticket_notes": {"mode": "use", "words": "in use", "band": "In use. A ticket's later runs read its notes."},
        "lessons": {
            "mode": "record",
            "words": "recording",
            "band": "Recording only. Workers propose lessons and you may promote them; no run reads them.",
        },
    }


def migrated(canopy_env: CanopyEnv) -> Context:
    """The workspace's context, read with the config as it stands, its journal migrated."""
    found = context(canopy_env)
    db.migrate(found.conn, resources.migrations_dir())
    return found


def test_with_memory_off_the_loop_state_has_no_memory(canopy_env: CanopyEnv) -> None:
    c, _ = signed_in_client(migrated(canopy_env))
    assert c.get("/api/loop").json()["memory"] is None
    overview = c.get("/api/memory").json()
    assert (overview["state"], overview["tickets"], overview["lessons_digest"]) == (None, [], None)


def test_recording_is_never_called_in_use(canopy_env: CanopyEnv) -> None:
    with_memory(canopy_env, ticket_notes="record")
    c, _ = signed_in_client(migrated(canopy_env))
    state = c.get("/api/loop").json()["memory"]
    assert (state["readout"], state["ticket_notes"]["words"]) == ("memory: recording", "recording")


def test_the_overview_counts_the_notes_in_force_by_ticket_and_holds_the_proposals_and_lessons(
    backend: Backend,
) -> None:
    overview = client(None, backend).get("/api/memory").json()
    # By ticket, the newest note first: a ticket's own memory lists them.
    assert [(t["ticket_key"], t["count"], t["used"]) for t in overview["tickets"]] == [
        ("ABC-102", 1, 0),
        ("ABC-100", 2, 0),
    ]
    assert [(p["entry"]["id"], p["run_kind"], p["private"], p["ticket_done"]) for p in overview["proposals"]] == [
        (5, "implement", False, False),
        (6, "implement", True, False),
    ]
    [lesson] = overview["lessons"]
    assert (lesson["id"], lesson["scope"], lesson["repo"], lesson["promoted_from"]) == (8, "lesson", "web", 7)
    digest = overview["lessons_digest"]
    assert (digest["ids"], digest["served"], digest["left_out"]) == ([8], False, 0)
    assert digest["text"].startswith("## Lessons from the operator")


def test_a_tickets_memory_is_every_note_and_the_digest_its_next_run_gets(backend: Backend) -> None:
    c = client(None, backend)
    found = c.get("/api/tickets/ABC-100/memory").json()
    assert [(n["id"], n["status"], n["why"]) for n in found["notes"]] == [
        (3, "active", None),
        (2, "active", None),
        (1, "superseded", "superseded by note 2"),
    ]
    # Sent as the journal holds it, a hand-written zero-width space and all: the UI names it.
    assert "\u200b" in found["notes"][0]["text"]
    assert found["notes"][2]["use_count"] == 1
    assert found["notes"][2]["last_used_at"] == at(-115)
    assert (found["digest"]["ids"], found["digest"]["served"]) == ([3, 2], True)
    assert c.get("/api/tickets/ABC-999/memory").status_code == 404


def test_a_runs_memory_is_what_it_wrote_read_and_had_refused(backend: Backend) -> None:
    c = client(None, backend)
    found = c.get("/api/runs/40/memory").json()
    assert found["rendered"] == {"ticket_notes": "use", "lessons": "record"}
    assert [m["id"] for m in found["wrote"]] == [2, 3]
    assert [m["id"] for m in found["read"]] == [1]
    assert found["refused"] == [
        {"field": "notes", "key": "staging-login", "why": "its text looks like it holds a secret"}
    ]
    # Rendered while notes were recording: it read nothing because nothing was served.
    recorded = c.get("/api/runs/37/memory").json()
    assert (recorded["rendered"], recorded["read"]) == ({"ticket_notes": "record", "lessons": "record"}, [])
    # Rendered with memory off: no row at all.
    assert c.get("/api/runs/41/memory").json() == {"rendered": None, "wrote": [], "read": [], "refused": []}
    assert c.get("/api/runs/999/memory").status_code == 404


def test_the_overview_lists_lessons_reported_wrong_first_then_by_review_date(canopy_env: CanopyEnv) -> None:
    with_memory(canopy_env, proposals="use")
    ctx = migrated(canopy_env)
    with in_tick(ctx.conn) as tick_id:
        db.touch_ticket(ctx.conn, KEY, "repo")
        run_id = db.insert_run(
            ctx.conn, tick_id=tick_id, key=KEY, kind=RunKind.IMPLEMENT, branch=BRANCH, slots=(), runs_dir=Path("/r")
        )
    ctx.conn.executemany(
        "INSERT INTO memories (id, scope, key, body, status, author, created_at, review_at, wrong_at, wrong_run_id) "
        "VALUES (?, 'lesson', ?, 'A lesson.', 'active', 'operator', '2026-10-01T00:00:00.000Z', ?, ?, ?)",
        [
            (1, "a-due-last", "2027-03-01T00:00:00.000Z", None, None),
            (2, "b-due-first", "2027-01-01T00:00:00.000Z", None, None),
            (3, "c-reported-wrong", "2027-06-01T00:00:00.000Z", "2026-10-01T00:00:00.000Z", run_id),
        ],
    )
    c, _ = signed_in_client(ctx)
    assert [lesson["id"] for lesson in c.get("/api/memory").json()["lessons"]] == [3, 2, 1]
