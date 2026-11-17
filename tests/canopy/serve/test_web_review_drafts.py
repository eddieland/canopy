"""A review's draft in the web API (DESIGN §34): the review page's edits, notes, and publish, which are the CLI's.

The page edits a review's draft through the functions `canopy review edit` calls, asks for a revision with a note
through `canopy reply review:ID`'s, and publishes the version it showed, named by its hash, through
`canopy review publish`'s, so with the same refusals; what reaches GitHub is that version, word for word, as one comment
review on the commit the review read.
"""

import json
import os
from pathlib import Path
from typing import Any, Final
from unittest import mock

from fastapi.testclient import TestClient

from canopy.core import review_drafts, review_revisions, review_runs
from canopy.core.context import Context
from canopy.core.vocab import ReviewDraftAuthor, ReviewDraftStatus
from tests.canopy.helpers import context, present, reads, waits
from tests.canopy.observation_helpers import HEAD, observe_pr
from tests.canopy.review_helpers import FINDINGS, OFF_DIFF, ON_LINE, THEIRS, feature_commit, reviewer_reports
from tests.canopy.scenario_helpers import Scenario, reviews, revises
from tests.canopy.web_helpers import refused, signed_in_client
from tests.conftest import GitPool


def draft_of(c: TestClient, run_id: int) -> dict[str, Any]:
    response = c.get(f"/api/reviews/{run_id}")
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()["draft"]
    return found


def test_a_reviews_page_carries_its_draft_each_comment_on_its_line_of_the_diff(
    scenario: Scenario,
    reviewed: int,
    ctx: Context,
) -> None:
    c, _ = signed_in_client(ctx)
    draft = draft_of(c, reviewed)
    assert (draft["status"], draft["version"], draft["author"], draft["channel"]) == ("waiting", 1, "reviewer", None)
    assert draft["body"] == OFF_DIFF
    # The finding off the diff is a point of the review all the same, held by the body rather than a comment.
    assert draft["in_body"] == [2]
    [comment] = draft["comments"]
    assert (comment["number"], comment["path"], comment["line"], comment["text"], comment["finding"]) == (
        1,
        ON_LINE.path,
        ON_LINE.line,
        ON_LINE.text,
        1,
    )
    assert (comment["file"], comment["diff_line"]) == (0, 1)
    newest = review_drafts.newest(scenario.conn, present(review_drafts.of_review(scenario.conn, reviewed)).id)
    assert draft["hash"] == newest.hash
    assert [(v["number"], v["hash"]) for v in draft["versions"]] == [(1, newest.hash)]
    assert (draft["max_comments"], draft["moved_head"], draft["published_url"]) == (30, None, None)
    assert draft["pr_author"] is None


def test_a_draft_names_the_prs_author_and_its_head_as_canopy_last_read_the_pr(
    scenario: Scenario,
    reviewed: int,
    ctx: Context,
) -> None:
    observe_pr(scenario.conn, url=THEIRS)
    scenario.conn.commit()
    c, _ = signed_in_client(ctx)
    draft = draft_of(c, reviewed)
    assert (draft["pr_author"], draft["moved_head"]) == ("operator", HEAD)


def test_the_page_edits_a_draft_as_the_cli_does_each_change_a_version_through_the_web(
    scenario: Scenario,
    reviewed: int,
    ctx: Context,
) -> None:
    c, write = signed_in_client(ctx)
    base = f"/api/reviews/{reviewed}/draft"
    edited = c.post(f"{base}/comments/1/edit", json={"text": "This never stops."}, headers=write)
    assert edited.status_code == 200, edited.text
    assert [m["text"] for m in edited.json()["comments"]] == ["This never stops."]
    added = c.post(f"{base}/comments", json={"path": "retry.py", "line": 2, "text": "Call what?"}, headers=write)
    assert added.status_code == 200, added.text
    assert [(m["line"], m["finding"]) for m in added.json()["comments"]] == [(1, 1), (2, None)]
    body = c.post(f"{base}/body", json={"text": "Two things, mainly."}, headers=write)
    assert body.status_code == 200, body.text
    dropped = c.post(f"{base}/comments/2/drop", headers=write)
    assert dropped.status_code == 200, dropped.text
    found = dropped.json()
    assert (found["version"], found["body"], found["author"], found["channel"]) == (
        5,
        "Two things, mainly.",
        "operator",
        "web",
    )
    assert [v["change"] for v in found["versions"][1:]] == [
        "edited comment 1",
        "added a comment on retry.py:2",
        "edited the body",
        "dropped comment 2",
    ]
    versions = review_drafts.versions(scenario.conn, present(review_drafts.of_review(scenario.conn, reviewed)).id)
    assert {(v.author, v.channel) for v in versions[1:]} == {(ReviewDraftAuthor.OPERATOR, "web")}
    # Refused as the CLI refuses it, and nothing changes.
    assert refused(c.post(f"{base}/comments/9/drop", headers=write)).startswith("unknown: ")
    off = c.post(f"{base}/comments", json={"path": "retry.py", "line": 40, "text": "Here?"}, headers=write)
    assert refused(off).startswith("off_diff: ")
    hidden = c.post(f"{base}/body", json={"text": "loops\u200b forever"}, headers=write)
    assert refused(hidden).startswith("bad_text: ")
    assert draft_of(c, reviewed)["version"] == 5


def test_the_page_publishes_the_version_it_showed_verbatim_once(
    scenario: Scenario,
    reviewed: int,
    ctx: Context,
    github_state: Path,
) -> None:
    c, write = signed_in_client(ctx)
    path = f"/api/reviews/{reviewed}/draft/publish"
    shown = draft_of(c, reviewed)["hash"]
    c.post(
        f"/api/reviews/{reviewed}/draft/comments",
        json={"path": "retry.py", "line": 2, "text": "Why?"},
        headers=write,
    )
    # The page showed an older version: nothing posts.
    assert refused(c.post(path, json={"hash": shown, "submit": True}, headers=write)).startswith("stale: ")
    current = draft_of(c, reviewed)["hash"]
    with mock.patch.dict(os.environ, {"CANOPY_RUN_ID": "review-9"}):
        inside = c.post(path, json={"hash": current, "submit": True}, headers=write)
    assert refused(inside).startswith("inside_run: ")
    assert reads(github_state, "post") == []

    published = c.post(path, json={"hash": current, "submit": True}, headers=write)
    assert published.status_code == 200, published.text
    done = published.json()
    assert (done["published"], done["failed"], done["draft"]["status"]) == (2, None, "published")
    assert done["draft"]["published_url"] is not None
    sha = present(review_runs.get_review_run(scenario.conn, reviewed)).sha
    [request] = reads(github_state, "post")
    assert request == {
        "pr": THEIRS,
        "commit": sha,
        "delete_pending": None,
        "body": OFF_DIFF,
        "comments": [
            {"path": "retry.py", "line": 1, "text": ON_LINE.text},
            {"path": "retry.py", "line": 2, "text": "Why?"},
        ],
    }
    found = present(review_drafts.of_review(scenario.conn, reviewed))
    assert (found.status, found.publish_channel) == (ReviewDraftStatus.PUBLISHED, "web")
    # A draft publishes once, and takes no edit after.
    assert refused(c.post(path, json={"hash": current, "submit": True}, headers=write)).startswith("published: ")
    again = c.post(f"/api/reviews/{reviewed}/draft/body", json={"text": "More."}, headers=write)
    assert refused(again).startswith("published: ")
    assert len(reads(github_state, "post")) == 1


def test_the_page_stages_by_default_and_names_why_a_post_posted_nothing(
    reviewed: int,
    ctx: Context,
    github_state: Path,
) -> None:
    c, write = signed_in_client(ctx)
    path = f"/api/reviews/{reviewed}/draft/publish"
    github_state.write_text(json.dumps({"prs": {THEIRS: {}}, "refuse_lines": ["retry.py:1"]}))
    failed = c.post(path, json={"hash": draft_of(c, reviewed)["hash"], "submit": True}, headers=write)
    assert failed.status_code == 200, failed.text
    assert failed.json()["draft"]["status"] == "waiting"
    assert "GitHub refused comment 1, on retry.py:1" in failed.json()["failed"]
    github_state.write_text(json.dumps({"prs": {THEIRS: {}}}))
    staged = c.post(path, json={"hash": draft_of(c, reviewed)["hash"]}, headers=write)
    assert staged.status_code == 200, staged.text
    assert (staged.json()["draft"]["status"], staged.json()["failed"]) == ("staged", None)
    assert reads(github_state, "post")[-1]["submit"] is False


def test_the_lists_say_where_a_reviews_draft_stands(reviewed: int, ctx: Context, github_state: Path) -> None:
    c, write = signed_in_client(ctx)

    def listed() -> tuple[str | None, dict[str, Any] | None]:
        [review] = [r for r in c.get("/api/reviews").json() if r["id"] == reviewed]
        [pr] = [p for p in c.get("/api/pull-requests").json() if p["url"] == THEIRS]
        return review["draft"], pr["draft"]

    assert listed() == ("waiting", {"review_id": reviewed, "status": "waiting"})
    github_state.write_text(json.dumps({"prs": {THEIRS: {}}}))
    staged = c.post(
        f"/api/reviews/{reviewed}/draft/publish",
        json={"hash": draft_of(c, reviewed)["hash"]},
        headers=write,
    )
    assert staged.status_code == 200, staged.text
    assert listed() == ("staged", {"review_id": reviewed, "status": "staged"})
    pr = c.get("/api/pull-request", params={"url": THEIRS}).json()["pull_request"]
    assert pr["draft"] == {"review_id": reviewed, "status": "staged"}


def test_a_review_of_the_loops_own_pr_has_no_draft_to_edit_or_publish(
    scenario: Scenario,
    reviewing: object,
    git_pool: GitPool,
    tmp_path: Path,
    ctx: Context,
) -> None:
    del reviewing
    sha = feature_commit(git_pool, tmp_path)
    own = scenario.review(reviews(sha, ticket="PROJ-1"), reviewer=reviewer_reports(FINDINGS)).id
    c, write = signed_in_client(ctx)
    assert c.get(f"/api/reviews/{own}").json()["draft"] is None
    assert c.get("/api/reviews").json()[0]["draft"] is None
    body = c.post(f"/api/reviews/{own}/draft/body", json={"text": "Mine."}, headers=write)
    assert refused(body).startswith("no_draft: ")
    publish = c.post(f"/api/reviews/{own}/draft/publish", json={"hash": "0" * 12}, headers=write)
    assert refused(publish).startswith("no_draft: ")


def test_staging_from_the_page_takes_a_requested_review_off_the_attention_list(
    scenario: Scenario,
    requested: int,
    ctx: Context,
    github_state: Path,
) -> None:
    c, write = signed_in_client(ctx)
    scenario.tick(*waits("PROJ-1", rationale="its PR is out for review"))
    [item] = [i for i in c.get("/api/attention").json() if i["reason"] == "review_waiting"]
    assert (item["pr"], item["ticket_key"]) == (THEIRS, None)
    assert f"review:{requested}" in item["detail"]
    github_state.write_text(json.dumps({"prs": {THEIRS: {}}}))
    staged = c.post(
        f"/api/reviews/{requested}/draft/publish",
        json={"hash": draft_of(c, requested)["hash"]},
        headers=write,
    )
    assert staged.status_code == 200, staged.text
    assert "review_waiting" not in [i["reason"] for i in c.get("/api/attention").json()]
    assert "review_waiting" not in (scenario.env.state_dir / "attention.md").read_text()


def test_discarding_from_the_page_posts_nothing_and_takes_a_requested_review_off_the_attention_list(
    scenario: Scenario,
    requested: int,
    ctx: Context,
    github_state: Path,
) -> None:
    c, write = signed_in_client(ctx)
    scenario.tick(*waits("PROJ-1", rationale="its PR is out for review"))
    path = f"/api/reviews/{requested}/draft/discard"
    with mock.patch.dict(os.environ, {"CANOPY_RUN_ID": "review-9"}):
        assert refused(c.post(path, headers=write)).startswith("inside_run: ")
    discarded = c.post(path, headers=write)
    assert discarded.status_code == 200, discarded.text
    assert discarded.json()["status"] == ReviewDraftStatus.DISCARDED
    assert present(review_drafts.of_review(scenario.conn, requested)).why == "discarded by you through web"
    assert "review_waiting" not in [i["reason"] for i in c.get("/api/attention").json()]
    assert "review_waiting" not in (scenario.env.state_dir / "attention.md").read_text()
    assert refused(c.post(path, headers=write)).startswith("discarded: ")
    assert reads(github_state, "post") == []


#: What the operator's note asks of a revision, and what the reviser reports on it: the body alone, gentler.
NOTE: Final = "Say it more gently."
GENTLER: Final[dict[str, object]] = {"status": "done", "body": "One defect, gently put.", "comments": []}


def test_the_page_asks_for_a_revision_with_a_note_and_shows_it_asked_running_and_made(
    scenario: Scenario,
    reviewed: int,
    ctx: Context,
    github_state: Path,
) -> None:
    c, write = signed_in_client(ctx)
    path = f"/api/reviews/{reviewed}/draft/notes"
    before = draft_of(c, reviewed)
    assert (before["notes"], before["revisions"], before["revision_limit"]) == ([], [], 3)
    noted = c.post(path, json={"text": f"  {NOTE}\n"}, headers=write)
    assert noted.status_code == 200, noted.text
    found = noted.json()
    assert found["after_version"] == 1
    [note] = found["draft"]["notes"]
    assert (note["id"], note["body"], note["channel"], note["after_version"]) == (found["note"], NOTE, "web", 1)
    draft_id = present(review_drafts.of_review(scenario.conn, reviewed)).id
    assert [(n.body, n.channel) for n in review_revisions.pending(scenario.conn, draft_id)] == [(NOTE, "web")]

    # While the revision runs, the page says so, and a note or a publish is refused as the CLI refuses it.
    revising = scenario.starts_review(revises(reviewed), reviewer=reviewer_reports(GENTLER))
    [running] = draft_of(c, reviewed)["revisions"]
    assert (running["id"], running["state"], running["revised"], running["ended_at"]) == (
        revising.id,
        "running",
        1,
        None,
    )
    assert refused(c.post(path, json={"text": "And shorter."}, headers=write)).startswith("revising: ")
    publish = f"/api/reviews/{reviewed}/draft/publish"
    held = c.post(publish, json={"hash": before["hash"], "submit": True}, headers=write)
    assert refused(held).startswith("revising: ")

    # Its result is the new version, which answers the note.
    revising.finishes()
    after = draft_of(c, reviewed)
    assert (after["version"], after["author"], after["body"], after["notes"]) == (
        2,
        "reviser",
        "One defect, gently put.",
        [],
    )
    [made] = after["revisions"]
    assert (made["id"], made["status"], made["state"]) == (revising.id, "done", "done")
    assert reads(github_state, "post") == []


def test_a_note_from_the_page_is_refused_as_the_clis_is(
    scenario: Scenario,
    reviewed: int,
    ctx: Context,
    github_state: Path,
) -> None:
    c, write = signed_in_client(ctx)
    path = f"/api/reviews/{reviewed}/draft/notes"
    assert refused(c.post(path, json={"text": "  "}, headers=write)).startswith("bad_body: ")
    assert refused(c.post(path, json={"text": "x" * 4001}, headers=write)).startswith("bad_body: ")
    with mock.patch.dict(os.environ, {"CANOPY_RUN_ID": "review-9"}):
        assert refused(c.post(path, json={"text": NOTE}, headers=write)).startswith("inside_run: ")
    sha = present(review_runs.get_review_run(scenario.conn, reviewed)).sha
    own = scenario.review(reviews(sha, ticket="PROJ-1"), reviewer=reviewer_reports(FINDINGS)).id
    assert refused(c.post(f"/api/reviews/{own}/draft/notes", json={"text": NOTE}, headers=write)).startswith(
        "no_draft: ",
    )
    draft_id = present(review_drafts.of_review(scenario.conn, reviewed)).id
    assert review_revisions.pending(scenario.conn, draft_id) == []

    # At its limit, the page reads the limit the config sets, and the note is refused; it says how to grant more.
    scenario.configures(policy={"max_revisions_per_draft": 1})
    scenario.operator("reply", f"review:{reviewed}", NOTE)
    scenario.review(revises(reviewed), reviewer=reviewer_reports(GENTLER))
    c, write = signed_in_client(context(scenario.env))
    spent = draft_of(c, reviewed)
    assert (len(spent["revisions"]), spent["revision_limit"]) == (1, 1)
    limit = refused(c.post(path, json={"text": "Once more."}, headers=write))
    assert limit.startswith("revision_limit: ")
    assert f"canopy grant review:{reviewed} revision" in limit

    # A draft published takes no note.
    scenario.operator("grant", f"review:{reviewed}", "revision")
    current = draft_of(c, reviewed)
    assert current["revision_limit"] == 2
    published = c.post(
        f"/api/reviews/{reviewed}/draft/publish",
        json={"hash": current["hash"], "submit": True},
        headers=write,
    )
    assert published.status_code == 200, published.text
    assert len(reads(github_state, "post")) == 1
    assert refused(c.post(path, json={"text": "Too late."}, headers=write)).startswith("published: ")
