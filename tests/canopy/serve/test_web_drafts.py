"""Review replies in the web API (DESIGN §29): a PR's threads on its diff, and the operator's verbs on its drafts,
which are `canopy draft`'s."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from canopy.core import db, drafts_manage
from canopy.infra import resources
from tests.canopy.helpers import (
    DRAFTS_PR,
    all_drafts,
    approving,
    comment,
    context,
    github_has,
    reads,
    run_drafting,
    thread,
)
from tests.canopy.web_helpers import refused, signed_in_client

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

    from canopy.core.context import Context
    from tests.conftest import CanopyEnv

PR = DRAFTS_PR
OLD = "2020-01-01T00:00:00Z"


def migrated(canopy_env: CanopyEnv) -> Context:
    found = context(canopy_env)
    db.migrate(found.conn, resources.migrations_dir())
    return found


def drafted(canopy_env: CanopyEnv, conn: sqlite3.Connection, state: Path) -> tuple[TestClient, dict[str, str], int]:
    """A run under `approve` whose two drafts were checked, and a browser signed in to the server over its journal."""
    approving(canopy_env)
    github_has(state, {**comment(501), "time": OLD}, {**comment(502, "PRRT_2", body="Why?"), "time": OLD})
    run = run_drafting(conn, [thread(501), {"on": "pr", "pr": PR, "text": "Fixed the lint job."}, thread(999)])
    c, write = signed_in_client(migrated(canopy_env))
    return c, write, int(run["id"])


def threads_of(c: TestClient) -> dict[str, Any]:
    response = c.get("/api/pull-request/threads", params={"url": PR})
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found


@pytest.mark.usefixtures("git_pool")
def test_a_prs_threads_carry_the_drafts_that_answer_them_on_the_runs_diff(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, github_state: Path
) -> None:
    c, _, run_id = drafted(canopy_env, conn, github_state)
    found = threads_of(c)
    assert (found["review_replies"], found["head_sha"], found["diff_run"]) == ("approve", "abc1234", run_id)
    assert found["diff"] == {"files": [], "truncated": False}
    assert found["diff_head"] is not None
    first, second = found["threads"]
    assert (first["id"], first["path"], first["line"], first["side"]) == ("PRRT_1", "src/app.py", 12, "right")
    assert [(m["id"], m["author"], m["body"], m["operator_sent"]) for m in first["comments"]] == [
        (501, "alice", "Rename this.", False)
    ]
    [draft] = first["drafts"]
    assert (draft["run"], draft["number"], draft["kind"], draft["status"], draft["stance"]) == (
        run_id,
        1,
        "thread",
        "waiting",
        "changed",
    )
    assert (draft["text"], draft["hash"], draft["edited"]) == ("Renamed.", drafts_manage.hash_of("Renamed."), False)
    assert (second["id"], second["drafts"]) == ("PRRT_2", [])
    assert [(d["number"], d["text"]) for d in found["pr_drafts"]] == [(2, "Fixed the lint job.")]
    assert [(d["number"], d["status"]) for d in found["unplaced"]] == [(3, "refused")]


@pytest.mark.usefixtures("git_pool")
def test_the_page_edits_and_sends_drafts_as_one_review(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, github_state: Path
) -> None:
    c, write, run_id = drafted(canopy_env, conn, github_state)
    edited = c.post(f"/api/runs/{run_id}/drafts/1/edit", json={"text": "Renamed it to `retries`."}, headers=write)
    assert edited.status_code == 200, edited.text
    draft = edited.json()
    assert (draft["text"], draft["edited"]) == ("Renamed it to `retries`.", True)
    body = threads_of(c)["pr_drafts"][0]
    wanted = [{"run": run_id, "number": 1, "hash": draft["hash"]}, {"run": run_id, "number": 2, "hash": body["hash"]}]
    sent = c.post("/api/drafts/send", json={"drafts": wanted}, headers=write)
    assert sent.status_code == 200, sent.text
    assert [(d["number"], d["status"]) for d in sent.json()["posted"]] == [(1, "sent"), (2, "sent")]
    [posted] = reads(github_state, "post")
    assert posted["replies"] == [{"comment": 501, "text": "Renamed it to `retries`."}]
    assert posted["body"] == "Fixed the lint job."
    [reply, *_] = all_drafts(conn)
    assert reply.sent_channel == "web"


@pytest.mark.usefixtures("git_pool")
def test_a_send_of_text_the_page_no_longer_shows_is_refused_stale(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, github_state: Path
) -> None:
    c, write, run_id = drafted(canopy_env, conn, github_state)
    seen = threads_of(c)["threads"][0]["drafts"][0]["hash"]
    c.post(f"/api/runs/{run_id}/drafts/1/edit", json={"text": "Edited in another tab."}, headers=write)
    sent = c.post("/api/drafts/send", json={"drafts": [{"run": run_id, "number": 1, "hash": seen}]}, headers=write)
    assert refused(sent).startswith("stale: ")
    assert reads(github_state, "post") == []


@pytest.mark.usefixtures("git_pool")
def test_the_page_drops_a_draft_and_takes_the_drop_back(
    canopy_env: CanopyEnv, conn: sqlite3.Connection, github_state: Path
) -> None:
    c, write, run_id = drafted(canopy_env, conn, github_state)
    assert c.post(f"/api/runs/{run_id}/drafts/1/drop", json={}, headers=write).json()["status"] == "dropped"
    assert threads_of(c)["threads"][0]["drafts"][0]["status"] == "dropped"
    undone = c.post(f"/api/runs/{run_id}/drafts/1/drop", json={"undo": True}, headers=write).json()
    assert undone["status"] == "waiting"
    assert refused(c.post(f"/api/runs/{run_id}/drafts/9/drop", json={}, headers=write)).startswith("unknown: ")


def test_a_pr_the_journal_knows_nothing_of_is_not_found_and_a_bad_url_refused(canopy_env: CanopyEnv) -> None:
    c, _ = signed_in_client(migrated(canopy_env))
    assert c.get("/api/pull-request/threads", params={"url": PR}).status_code == 404
    assert c.get("/api/pull-request/threads", params={"url": "ftp://x/1"}).status_code == 422
