"""Agent memory in the web API (DESIGN §28, ROADMAP M50): each tier's mode in words, and what it holds, read only."""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import db
from canopy.infra import resources
from canopy.serve import mock
from tests.canopy.helpers import context, with_memory
from tests.canopy.web_helpers import client, signed_in_client

if TYPE_CHECKING:
    from canopy.core.context import Context
    from canopy.serve.backend import Backend
    from tests.conftest import CanopyEnv


def at(minutes: int) -> str:
    """A mock time as the API sends it."""
    return mock.at(minutes).replace(".000Z", "Z")


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
    assert (overview["state"], overview["notes"], overview["lessons_digest"]) == (None, [], None)


def test_recording_is_never_called_in_use(canopy_env: CanopyEnv) -> None:
    with_memory(canopy_env, ticket_notes="record")
    c, _ = signed_in_client(migrated(canopy_env))
    state = c.get("/api/loop").json()["memory"]
    assert (state["readout"], state["ticket_notes"]["words"]) == ("memory: recording", "recording")


def test_the_overview_holds_the_notes_in_force_the_proposals_and_the_lessons(backend: Backend) -> None:
    overview = client(None, backend).get("/api/memory").json()
    assert [(n["id"], n["ticket_key"], n["key"]) for n in overview["notes"]] == [
        (3, "ABC-100", "ci-cache"),
        (2, "ABC-100", "flaky-checkout"),
        (4, "ABC-102", "export-encoding"),
    ]
    # Sent as the journal holds it, a hand-written zero-width space and all: the UI names it.
    assert "\u200b" in overview["notes"][0]["text"]
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
