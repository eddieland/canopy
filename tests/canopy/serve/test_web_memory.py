"""Agent memory in the web API (DESIGN §28, ROADMAP M50 and M52): each tier's mode in words, what it holds, and the
operator's verbs on it, which are `canopy memory`'s."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from canopy.core import db
from canopy.core.vocab import RunKind
from canopy.infra import resources
from tests.canopy.helpers import BRANCH, KEY, context, in_run, in_tick, with_memory
from tests.canopy.web_helpers import ORIGIN, at, client, refused, signed_in_client

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
        "proposals_waiting": 2,
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


def test_the_loop_state_counts_the_proposals_waiting_only_while_proposals_are_on(canopy_env: CanopyEnv) -> None:
    with_memory(canopy_env, ticket_notes="record", proposals="record")
    ctx = migrated(canopy_env)
    with in_tick(ctx.conn) as tick_id:
        db.touch_ticket(ctx.conn, KEY, "repo")
        run_id = db.insert_run(
            ctx.conn, tick_id=tick_id, key=KEY, kind=RunKind.IMPLEMENT, branch=BRANCH, slots=(), runs_dir=Path("/r")
        )
    ctx.conn.executemany(
        "INSERT INTO memories (scope, ticket_key, run_id, key, body, status, author, created_at) "
        "VALUES ('proposal', ?, ?, ?, 'A proposal.', ?, 'worker', '2026-10-01T00:00:00.000Z')",
        [(KEY, run_id, key, status) for key, status in [("waits", "pending"), ("also", "pending"), ("no", "invalid")]],
    )
    c, _ = signed_in_client(ctx)
    assert c.get("/api/loop").json()["memory"]["proposals_waiting"] == 2
    with_memory(canopy_env, ticket_notes="record")
    c, _ = signed_in_client(migrated(canopy_env))
    assert c.get("/api/loop").json()["memory"]["proposals_waiting"] == 0


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
    # It names the run that relied on it; a note no run relied on names none.
    assert (found["notes"][2]["used_by"], found["notes"][0]["used_by"]) == ([40], [])
    assert (found["digest"]["ids"], found["digest"]["served"]) == ([3, 2], True)
    assert c.get("/api/tickets/ABC-999/memory").status_code == 404


def test_a_runs_memory_is_what_it_wrote_read_and_had_refused(backend: Backend) -> None:
    c = client(None, backend)
    found = c.get("/api/runs/40/memory").json()
    assert found["rendered"] == {"ticket_notes": "use", "lessons": "record"}
    assert [m["id"] for m in found["wrote"]] == [2, 3]
    assert [m["id"] for m in found["read"]] == [1]
    assert (found["used"], found["wrong"]) == ([1], [])
    assert found["refused"] == [
        {"field": "notes", "key": "staging-login", "why": "its text looks like it holds a secret"}
    ]
    # Rendered while notes were recording: it read nothing because nothing was served.
    recorded = c.get("/api/runs/37/memory").json()
    assert (recorded["rendered"], recorded["read"]) == ({"ticket_notes": "record", "lessons": "record"}, [])
    # Rendered with memory off: no row at all.
    assert c.get("/api/runs/41/memory").json() == {
        "rendered": None,
        "wrote": [],
        "read": [],
        "used": [],
        "wrong": [],
        "refused": [],
    }
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


# A write to the mock needs no session, but an Origin naming the server (guard.py).
WRITE = {"origin": ORIGIN}


def test_promote_makes_a_proposal_a_lesson_recorded_and_served_to_no_run(backend: Backend) -> None:
    c = client(None, backend)
    promoted = c.post("/api/memory/5/promote", json={}, headers=WRITE).json()
    lesson = promoted["lesson"]
    # As written: the proposal's text and repository, the operator's now.
    assert (lesson["scope"], lesson["key"], lesson["repo"], lesson["promoted_from"]) == (
        "lesson",
        "web-tests",
        "web",
        5,
    )
    assert lesson["text"] == promoted["source"]["text"]
    assert (promoted["source"]["status"], promoted["superseded"], promoted["served"]) == ("pending", None, False)
    overview = c.get("/api/memory").json()
    assert [p["entry"]["id"] for p in overview["proposals"]] == [6]
    assert lesson["id"] in [m["id"] for m in overview["lessons"]]


def test_promote_takes_the_operators_words_and_repository_and_supersedes_under_the_key(backend: Backend) -> None:
    c = client(None, backend)
    # A note's lesson is every repository's unless one is named; a superseded note's text still teaches.
    first = c.post("/api/memory/1/promote", json={}, headers=WRITE).json()
    assert (first["lesson"]["repo"], first["source"]["scope"]) == (None, "ticket")
    words = "  Wait on the payment iframe's load event in checkout.spec.ts. "
    again = c.post("/api/memory/2/promote", json={"text": words, "repo": "mobile"}, headers=WRITE).json()
    assert (again["lesson"]["text"], again["lesson"]["repo"]) == (words.strip(), "mobile")
    assert again["superseded"] == first["lesson"]["id"]
    # The notes stay their ticket's.
    notes = c.get("/api/tickets/ABC-100/memory").json()["notes"]
    assert {n["id"]: n["status"] for n in notes}[2] == "active"


@pytest.mark.parametrize(
    ("memory_id", "body", "guard"),
    [
        (999, {}, "unknown: no proposal or note has id 999"),
        (8, {}, "unknown: no proposal or note has id 8"),
        (7, {}, "not_pending: proposal 7 is superseded: promoted to lesson 8"),
        (4, {"repo": "nowhere"}, "unknown_repo: 'nowhere' is not a repository in this workspace (api, mobile, web)"),
        (4, {"text": "x" * 601}, "bad_text"),
        # As written, the note's hand-written zero-width space is refused, as the CLI refuses it.
        (3, {}, "bad_text"),
        (4, {"text": "bad\u202etext"}, "bad_text"),
    ],
)
def test_promote_is_refused_as_the_cli_refuses_it(
    backend: Backend, memory_id: int, body: dict[str, str], guard: str
) -> None:
    c = client(None, backend)
    assert refused(c.post(f"/api/memory/{memory_id}/promote", json=body, headers=WRITE)).startswith(guard)
    assert len(c.get("/api/memory").json()["lessons"]) == 1


def test_reject_ends_a_proposal_once(backend: Backend) -> None:
    c = client(None, backend)
    assert c.post("/api/memory/6/reject", headers=WRITE).json() == {"id": 6}
    assert [p["entry"]["id"] for p in c.get("/api/memory").json()["proposals"]] == [5]
    assert refused(c.post("/api/memory/6/reject", headers=WRITE)) == "not_pending: proposal 6 is invalid: rejected"
    assert refused(c.post("/api/memory/6/promote", json={}, headers=WRITE)).startswith("not_pending")
    assert refused(c.post("/api/memory/2/reject", headers=WRITE)) == "unknown: no proposal has id 2"


def test_renew_pushes_a_lessons_review_out(backend: Backend) -> None:
    c = client(None, backend)
    renewed = c.post("/api/memory/8/renew", headers=WRITE).json()
    due = datetime.fromisoformat(renewed["review_at"])
    assert renewed["id"] == 8
    assert abs(due - (datetime.now(UTC) + timedelta(days=90))) < timedelta(minutes=5)
    assert refused(c.post("/api/memory/5/renew", headers=WRITE)) == "unknown: no lesson in force has id 5"


def test_forget_needs_the_ref_typed_and_then_deletes_the_text(backend: Backend) -> None:
    c = client(None, backend)

    def text_of(memory_id: int) -> str | None:
        notes = c.get("/api/tickets/ABC-100/memory").json()["notes"]
        return {n["id"]: n["text"] for n in notes}[memory_id]

    # The challenge is checked before anything is read: a wrong or missing ref forgets nothing.
    for typed in ("2", "memory:20", "Memory:2"):
        assert refused(c.post("/api/memory/2/forget", json={"confirm": typed}, headers=WRITE)) == (
            "not_confirmed: type memory:2 to confirm forgetting its text"
        )
    assert c.post("/api/memory/2/forget", json={}, headers=WRITE).status_code == 422
    assert text_of(2) is not None
    forgot = c.post("/api/memory/2/forget", json={"confirm": "memory:2"}, headers=WRITE).json()
    assert (forgot["id"], forgot["scope"], forgot["key"]) == (2, "ticket", "flaky-checkout")
    assert text_of(2) is None
    assert refused(c.post("/api/memory/2/forget", json={"confirm": "memory:2"}, headers=WRITE)).startswith("forgotten")
    assert refused(c.post("/api/memory/2/promote", json={}, headers=WRITE)).startswith("forgotten")
    assert refused(c.post("/api/memory/99/forget", json={"confirm": "memory:99"}, headers=WRITE)) == (
        "unknown: no memory has id 99"
    )
    # Forgetting a lesson retires it.
    assert c.post("/api/memory/8/forget", json={"confirm": "memory:8"}, headers=WRITE).json()["scope"] == "lesson"
    assert c.get("/api/memory").json()["lessons"] == []


@pytest.mark.parametrize(
    ("verb", "body"), [("promote", {}), ("reject", None), ("renew", None), ("forget", {"confirm": "memory:6"})]
)
def test_every_verb_is_refused_inside_a_run(backend: Backend, verb: str, body: dict[str, str] | None) -> None:
    c = client(None, backend)
    before = c.get("/api/memory").json()
    memory_id = 8 if verb == "renew" else 6
    with in_run(7):
        response = c.post(f"/api/memory/{memory_id}/{verb}", json=body, headers=WRITE)
    assert refused(response).startswith("inside_run")
    assert c.get("/api/memory").json() == before


def test_with_proposals_off_promote_reject_and_renew_are_refused(canopy_env: CanopyEnv) -> None:
    with_memory(canopy_env, ticket_notes="record")
    c, headers = signed_in_client(migrated(canopy_env))
    calls: list[tuple[str, dict[str, str] | None]] = [("promote", {}), ("reject", None), ("renew", None)]
    for verb, body in calls:
        assert refused(c.post(f"/api/memory/1/{verb}", json=body, headers=headers)).startswith("off: memory.proposals")


def test_the_overview_names_the_workspaces_repositories_and_a_private_runs_memory(backend: Backend) -> None:
    overview = client(None, backend).get("/api/memory").json()
    assert overview["repos"] == ["api", "mobile", "web"]
    assert [(p["entry"]["id"], p["entry"]["private"]) for p in overview["proposals"]] == [(5, False), (6, True)]
    c = client(None, backend)
    # As written, a private run's words carry the CLI's warning; in the operator's own, they do not.
    assert c.post("/api/memory/6/promote", json={}, headers=WRITE).json()["private"] is True
    assert c.post("/api/memory/4/promote", json={"text": "Mine."}, headers=WRITE).json()["private"] is False
