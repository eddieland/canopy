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
        "dismissed": False,
    }
    assert deps["latest_note_id"] == 8


def test_each_chore_carries_what_its_runs_cost_in_the_last_day_and_the_last_30_days(backend: Backend) -> None:
    with backend.open() as ctx:
        for started, cost in [(-3 * 24 * 60, 0.4), (-2 * 24 * 60, None), (-31 * 24 * 60, 9.0)]:
            ctx.conn.execute(
                "INSERT INTO chore_runs (tick_id, chore, started_at, ended_at, status, log_path, cost_usd) "
                "VALUES (1, 'deps', ?, ?, 'failed', 'x.log', ?)",
                (mock.at(started), mock.at(started + 5), cost),
            )
    c = client(None, backend)
    health, deps = c.get("/api/chores").json()

    # A running run counts, as the spend counts it, by when it started.
    assert health["spend"]["day"] == spent(24, 2, [0.05, 0.33])
    assert deps["spend"]["day"] == spent(24, 2, [0.21, 0.26])
    # One run reported no cost, and one started before the window.
    assert deps["spend"]["month"] == spent(720, 4, [0.21, 0.26, 0.4])
    assert c.get("/api/chores/deps").json()["chore"]["spend"] == deps["spend"]


def test_a_chores_p99_is_by_nearest_rank_so_one_dear_run_in_a_hundred_does_not_set_it(backend: Backend) -> None:
    with backend.open() as ctx:
        ctx.conn.executemany(
            "INSERT INTO chore_runs (tick_id, chore, started_at, ended_at, status, log_path, cost_usd) "
            "VALUES (1, 'build-health', ?, ?, 'ok', 'x.log', 0.1)",
            [(mock.at(-2 * 24 * 60), mock.at(-2 * 24 * 60 + 5))] * 198,
        )
    health, _ = client(None, backend).get("/api/chores").json()

    # 200 runs: 0.05, 198 at 0.10, and 0.33. The 198th cheapest is the 99th percentile.
    month = health["spend"]["month"]
    assert (month["priced"], month["p99_usd"], month["mean_usd"]) == (200, 0.1, pytest.approx(20.18 / 200))
    assert month["max_usd"] == 0.33
    # Under 100 runs it is the dearest one.
    assert health["spend"]["day"]["p99_usd"] == 0.33


def spent(hours: int, runs: int, costs: list[float]) -> dict[str, Any]:
    """A chore's spend window as the API sends it, for `runs` runs of which those in `costs` reported one."""
    total = sum(costs)
    return {
        "hours": hours,
        "runs": runs,
        "priced": len(costs),
        "cost_usd": pytest.approx(total),
        "mean_usd": pytest.approx(total / len(costs)),
        "p99_usd": max(costs),
        "max_usd": max(costs),
    }


def test_a_chores_page_is_what_canopy_show_prints_and_any_other_name_is_refused(backend: Backend) -> None:
    c = client(None, backend)
    page = c.get("/api/chores/deps").json()
    assert page["chore"]["name"] == "deps"
    assert [(r["id"], r["status"], r["findings"]) for r in page["runs"]] == [(2, "ok", 1), (1, "ok", 0)]
    latest = page["runs"][0]
    assert (latest["session_id"], latest["cost_usd"], latest["log_path"]) == (
        "ses_chore2",
        0.26,
        ".canopy/chore-runs/deps/2.log",
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


def test_a_finding_dismissed_from_the_web_leaves_the_attention_list_as_the_cli_dismisses_it(backend: Backend) -> None:
    written: list[str] = []
    backend = dataclasses.replace(backend, write_attention=lambda ctx: written.append(ctx.repo))
    c = client(None, backend, key=SECRET)
    headers = signed_in(c)
    url = "/api/chores/deps/dismissals"
    body = {"finding": "lodash-advisory"}

    def listed() -> list[str]:
        return [i["reason"] for i in c.get("/api/attention").json() if i["chore"] == "deps"]

    assert listed() == ["lodash-advisory"]
    assert c.post(url, json=body, headers={"origin": headers["origin"]}).status_code == 403
    for name, finding, guard in [
        ("deps", "stuck/pr-7", "unknown"),
        ("deps", "-bad", "bad_finding"),
        ("nope", "x", "unknown"),
    ]:
        refused = c.post(f"/api/chores/{name}/dismissals", json={"finding": finding}, headers=headers)
        assert (refused.status_code, refused.json()["detail"]["guard"]) == (409, guard)

    assert c.post(url, json=body, headers=headers).json() == {
        "chore": "deps",
        "finding": "lodash-advisory",
        "dismissed": True,
    }
    assert listed() == []
    # The loop's `attention.md` is rewritten at once, as `canopy dismiss` rewrites it.
    assert len(written) == 1
    [finding] = c.get("/api/chores/deps").json()["chore"]["findings"]
    assert (finding["id"], finding["dismissed"]) == ("lodash-advisory", True)
    with backend.open() as ctx:
        row = ctx.conn.execute("SELECT channel FROM finding_dismissals WHERE chore = 'deps'").fetchone()
        assert row["channel"] == "web"

    undone = c.post(url, json={**body, "undo": True}, headers=headers).json()
    assert undone["dismissed"] is False
    assert listed() == ["lodash-advisory"]
