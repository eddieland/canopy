"""The web UI's chores (DESIGN §19, §22, ROADMAP M23): what `canopy status` and `canopy show chore:NAME` print, and a
note the operator writes there, which the chore's next prompt carries as `canopy reply chore:NAME`'s does."""

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from canopy.chores import start
from canopy.core import chore_view, conversation, db
from canopy.serve import mock
from canopy.serve.backend import Backend
from tests.canopy.test_chores import run_section
from tests.canopy.test_serve import SECRET, client, signed_in

NOTE = "Leave out lodash-advisory until 2026-10-15: the date picker's upgrade is merging."


@pytest.fixture
def backend(tmp_path: Path) -> Backend:
    return mock.seed(tmp_path / "mock")


def at(minutes: int) -> str:
    """A mock time as the API sends it."""
    return mock.at(minutes).replace(".000Z", "Z")


def test_the_chores_list_is_each_configured_chore_as_canopy_status_lists_it(backend: Backend) -> None:
    c = client(None, backend)
    health, deps = c.get("/api/chores").json()

    assert health["name"] == "build-health"
    assert (health["running"]["id"], health["running"]["status"], health["running"]["state"]) == (
        4,
        "running",
        "running",
    )
    assert (health["latest"]["id"], health["latest"]["state"]) == (3, "done")
    assert (health["days"], health["hours"], health["timezone"], health["findings"]) == ([], None, None, [])

    assert (deps["name"], deps["every_minutes"], deps["running"]) == ("deps", 360, None)
    assert (deps["days"], deps["hours"], deps["timezone"]) == (
        ["mon", "tue", "wed", "thu", "fri"],
        "08:00-18:00",
        "UTC",
    )
    assert deps["when"] == "Skip it when nothing has merged to main since the last run."
    # Every 360 minutes after the latest start, which was at -240, inside Thursday's hours.
    assert deps["due_at"] == at(120)
    assert deps["latest"]["summary"] == "One advisory touches web's lockfile."
    [finding] = deps["findings"]
    assert finding == {
        "id": "lodash-advisory",
        "title": "lodash 4.17.20 has a prototype pollution advisory",
        "detail": "web's lockfile pins lodash 4.17.20 through an old date picker; 4.17.21 fixes it.",
        "link": "https://github.com/advisories/GHSA-35jh-r3h4-6jhm",
        # The first of the unbroken `ok` runs reporting it; the run before found nothing.
        "since": at(-240),
    }
    assert deps["latest_note_id"] == 8


def test_a_chores_page_is_what_canopy_show_prints_and_any_other_name_is_refused(backend: Backend) -> None:
    c = client(None, backend)
    page = c.get("/api/chores/deps").json()
    assert page["chore"]["name"] == "deps"
    assert [(r["id"], r["status"], r["findings"]) for r in page["runs"]] == [(2, "ok", 1), (1, "ok", 0)]
    latest = page["runs"][0]
    assert (latest["session_id"], latest["cost_usd"], latest["log_path"]) == (
        "ses_chore2",
        0.26,
        "/home/op/.canopy/chores/2.log",
    )
    [note] = page["notes"]
    assert (note["id"], note["source"], note["kind"], note["channel"]) == (8, "operator", "reply", "cli")

    missing = c.get("/api/chores/nope")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "no chore 'nope' is defined for this workspace"
    bad = c.get("/api/chores/Not_A_Name")
    assert (bad.status_code, bad.json()["detail"]["guard"]) == (409, "bad_ref")


def test_a_chore_turned_off_by_max_chores_leaves_the_list_but_keeps_its_page(backend: Backend) -> None:
    capacity = backend.config.capacity.model_copy(update={"max_chores": 0})
    off = dataclasses.replace(backend, config=backend.config.model_copy(update={"capacity": capacity}))
    c = client(None, off)
    assert c.get("/api/chores").json() == []
    # As `canopy reply chore:NAME` takes a note to a chore defined for the workspace, whether or not it runs.
    assert c.get("/api/chores/deps").status_code == 200


def test_a_note_from_the_web_is_recorded_as_the_cli_records_one_and_the_next_prompt_carries_it(
    backend: Backend,
) -> None:
    c = client(None, backend, key=SECRET)
    headers = signed_in(c)
    url = "/api/chores/deps/replies"
    body = {"body": f"  {NOTE}  ", "submission": "note-0001"}

    assert c.post(url, json=body, headers={"origin": headers["origin"]}).status_code == 403
    first = c.post(url, json=body, headers=headers).json()
    again = c.post(url, json=body, headers=headers).json()
    assert first == {"message_id": 9, "answers": None, "new": True}
    assert again == {**first, "new": False}
    unknown = c.post("/api/chores/nope/replies", json=body, headers=headers)
    assert (unknown.status_code, unknown.json()["detail"]["guard"]) == (409, "unknown")
    empty = c.post(url, json={"body": " ", "submission": "note-0002"}, headers=headers)
    assert (empty.status_code, empty.json()["detail"]["guard"]) == (409, "bad_body")

    with backend.open() as ctx:
        _, note = db.messages_of(ctx.conn, conversation.CHORE, "deps", 10)
        assert (note["source"], note["kind"], note["channel"]) == ("operator", "reply", "web")
        assert (note["body"], note["submission"]) == (NOTE, "web:note-0001")
        state = chore_view.state_of(ctx.conn, "deps", ctx.config.chores["deps"])
        prompt = start.render("Check deps.", state, None, None, conversation.chore_notes(ctx.conn, "deps"))
    notes: list[dict[str, Any]] = run_section(prompt)["operator_notes"]
    assert [(n["id"], n["note"]) for n in notes] == [
        (8, "Leave out the docs site's lockfile: it is never deployed."),
        (9, NOTE),
    ]

    # The list the stream sends changes with the note, so a page showing the chore reads it again.
    [_, deps] = c.get("/api/chores").json()
    assert deps["latest_note_id"] == 9
    assert [n["id"] for n in c.get("/api/chores/deps").json()["notes"]] == [8, 9]
