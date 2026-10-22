"""A review's draft in the web API (DESIGN §34): the review page's edits and publish, which are `canopy review`'s.

The page edits a review's draft through the functions `canopy review edit` calls, and publishes the version it showed,
named by its hash, through `canopy review publish`'s, so with the same refusals; what reaches GitHub is that version,
word for word, as one comment review on the commit the review read.
"""

import json
import os
from pathlib import Path
from typing import Any
from unittest import mock

from fastapi.testclient import TestClient

from canopy.core import review_drafts, review_runs
from canopy.core.context import Context
from canopy.core.vocab import ReviewDraftAuthor, ReviewDraftStatus
from tests.canopy.helpers import present, reads, waits
from tests.canopy.observation_helpers import HEAD, observe_pr
from tests.canopy.review_helpers import FINDINGS, OFF_DIFF, ON_LINE, THEIRS, feature_commit, reviewer_reports
from tests.canopy.scenario_helpers import Scenario, reviews
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
    assert draft["body"] == f"Two defects.\n\n{OFF_DIFF}"
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
        "body": f"Two defects.\n\n{OFF_DIFF}",
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
