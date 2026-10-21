"""The web UI's reviews (DESIGN §21, Reading reviews): canopy's shadow PR review, posted nowhere (D114).

The findings, the diff, and the reviewer's transcript and log are untrusted text. The writes are dismissing a
finding, as `canopy dismiss review:ID`, sending some to a worker, as `canopy send review:ID`, and marking reviews
seen, as `canopy review show ID` does.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from canopy.core import db, gc_passes, review_diff, review_runs
from canopy.core.vocab import ReviewRunStatus
from canopy.serve import mock_reviews
from canopy.serve.api import reviews as reviews_api
from canopy.serve.backend import Backend
from tests.canopy.helpers import present
from tests.canopy.web_helpers import SECRET, client, signed_in


def test_the_reviews_list_is_every_review_run_newest_first(backend: Backend) -> None:
    listed = client(None, backend).get("/api/reviews").json()
    assert [(r["id"], r["pr_url"], r["state"], r["verdict"], r["findings"]) for r in listed] == [
        (5, mock_reviews.PR_14, "done", "findings", 3),
        (4, mock_reviews.PR_88, "done", "findings", 3),
        (3, mock_reviews.PR_91, "failed", None, 0),
        (2, mock_reviews.PR_12, "done", "clean", 0),
        (1, mock_reviews.PR_88, "done", "findings", 1),
    ]
    assert (listed[1]["sha"], listed[1]["ticket_key"], listed[1]["repo"]) == (mock_reviews.SHA_88, "ABC-099", "web")
    assert listed[3]["ticket_key"] is None  # a PR review.query matched, with no ticket
    # Its worst finding, which colors its verdict, and how many are that bad, which its verdict says: none for a clean
    # review or one that reported nothing.
    assert [(r["worst"], r["worst_count"]) for r in listed] == [
        ("major", 1),
        ("major", 1),
        (None, 0),
        (None, 0),
        ("blocking", 1),
    ]
    # The persona each wrote in, which tells apart the reviews of one commit in several (DESIGN §31).
    assert [r["persona"] for r in listed] == ["canopy", "skeptic", "canopy", "canopy", "canopy"]


def test_a_review_is_titled_by_its_prs_own_title_else_its_tickets_else_none(backend: Backend) -> None:
    with backend.open() as ctx:
        ctx.conn.execute("DELETE FROM pr_titles WHERE pr_url IN (?, ?)", (mock_reviews.PR_91, mock_reviews.PR_12))
    listed = client(None, backend).get("/api/reviews").json()
    assert [(r["id"], r["title"]) for r in listed] == [
        (4, "ABC-099: debounce the search box by 250 ms"),
        (3, "Move billing to the v2 API"),  # ABC-103's, its PR having reported none
        (2, None),  # no title of its own, and no ticket
        (1, "ABC-099: debounce the search box by 250 ms"),
    ]


def test_a_requested_pr_is_listed_from_the_request_until_its_review_starts_and_again_if_it_fails(
    backend: Backend,
    tmp_path: Path,
) -> None:
    c = client(None, backend)
    # Asked for from the web UI, and no review of it has run yet: the reviews page shows it waiting on a tick.
    assert [(r["pr_url"], r["channel"]) for r in c.get("/api/review-requests").json()] == [(mock_reviews.PR_95, "web")]
    with backend.open() as ctx:
        run_id = review_runs.insert_review_run(
            ctx.conn,
            tick_id=1,
            pr_url=mock_reviews.PR_95,
            sha="abc1234",
            ticket=None,
            repo="web",
            purpose="request",
            logs_dir=tmp_path,
        )
    # Its review is in the reviews list now, so it is not listed twice.
    assert c.get("/api/review-requests").json() == []
    with backend.open() as ctx:
        db.finish_run(ctx.conn, "review_runs", run_id, ReviewRunStatus.FAILED, None)
    # Only a `done` review ends a request: it waits on the next tick again.
    assert [r["pr_url"] for r in c.get("/api/review-requests").json()] == [mock_reviews.PR_95]


def test_a_review_anchors_its_findings_on_its_diff(backend: Backend) -> None:
    c = client(None, backend)
    found = c.get("/api/reviews/4").json()
    assert found["review"]["impact"] == "normal"
    # Its ticket's title, so its page can lead with it; none for a PR with no ticket.
    assert found["ticket_title"] == "Debounce search input"
    assert c.get("/api/reviews/2").json()["ticket_title"] is None
    assert found["base_branch"] == "main"
    assert found["summary"].startswith("Stale requests are aborted now.")
    files = found["diff"]["files"]
    assert [(f["path"], f["old_path"], f["binary"]) for f in files] == [
        ("src/search/SearchBox.tsx", None, False),
        ("src/search/useSearch.ts", None, False),
    ]
    assert [(f["severity"], f["file"], f["line"]) for f in found["findings"]] == [
        ("major", 1, 15),  # on a line the diff shows
        ("minor", 0, 6),
        ("minor", None, None),  # a file the diff does not touch
    ]
    # The line a finding anchors on, on the new side, is the one it names.
    shown = {ln["new"]: ln["text"] for h in files[1]["hunks"] for ln in h["lines"]}
    assert shown[15].strip() == "setLoading(false)"
    # Line breaks in a finding's detail are kept.
    assert "\n" in found["findings"][0]["detail"]
    # The PR's other review runs, newest first, this one included.
    assert [r["id"] for r in found["runs"]] == [4, 1]
    assert not found["diff"]["truncated"]


def test_a_review_goes_gzipped_to_a_browser_that_takes_it_and_as_it_is_to_one_that_does_not(backend: Backend) -> None:
    c = client(None, backend)
    # httpx asks for gzip, as a browser does, and reads the body back as it was.
    taken = c.get("/api/reviews/4")
    assert (taken.headers["content-encoding"], taken.headers["vary"]) == ("gzip", "Accept-Encoding")
    plain = c.get("/api/reviews/4", headers={"accept-encoding": "identity"})
    assert ("content-encoding" in plain.headers, plain.headers["vary"]) == (False, "Accept-Encoding")
    assert taken.json() == plain.json()
    assert int(taken.headers["content-length"]) < int(plain.headers["content-length"])
    # gzip named among others, or with a weight, is taken; refused with q=0, or only as x-gzip, it is not.
    for accept, gzipped in [
        ("deflate, gzip;q=0.5", True),
        ("br, GZIP", True),
        ("gzip;q=0", False),
        ("gzip; q=0.0, identity", False),
        ("gzip;q=x", False),
        ("x-gzip", False),
    ]:
        sent = c.get("/api/reviews/4", headers={"accept-encoding": accept})
        assert (sent.headers.get("content-encoding") == "gzip") is gzipped, accept
    # A review too short to be worth it goes as it is. The threshold is held just above review 3's length, so a field
    # added to every review does not carry it past.
    length = len(c.get("/api/reviews/3", headers={"accept-encoding": "identity"}).content)
    with mock.patch.object(reviews_api, "_GZIP_FROM", length + 1):
        short = c.get("/api/reviews/3")
    assert "content-encoding" not in short.headers


def test_a_review_without_a_diff_has_none_and_a_failed_one_says_why(backend: Backend) -> None:
    c = client(None, backend)
    first = c.get("/api/reviews/1").json()
    assert first["diff"] is None
    assert [(f["file"], f["line"]) for f in first["findings"]] == [(None, None)]
    failed = c.get("/api/reviews/3").json()
    assert (failed["review"]["status"], failed["note"], failed["findings"]) == (
        "unknown",
        "the reviewer's last line was not a valid result",
        [],
    )


def test_no_such_review_is_a_404_and_its_id_is_a_positive_integer(backend: Backend) -> None:
    c = client(None, backend)
    for path in ("/api/reviews/99", "/api/reviews/99/transcript", "/api/reviews/99/output"):
        missing = c.get(path)
        assert (missing.status_code, missing.json()["detail"]) == (404, "no review run 99"), path
    assert c.get("/api/reviews/0").status_code == 422
    assert c.get("/api/reviews/0/transcript").status_code == 422


def test_a_reviews_run_is_its_log_its_tokens_and_its_reviewers_session(backend: Backend) -> None:
    c = client(None, backend)
    found = c.get("/api/reviews/4").json()
    # Its log is shown from the workspace's root, as a run's is.
    assert found["log_path"] == ".canopy/reviews/4.log"
    transcript = c.get("/api/reviews/4/transcript").json()
    assert (transcript["status"], transcript["session_id"]) == ("read", "ses_review4")
    entries = transcript["entries"]
    assert [e["kind"] for e in entries[:4]] == ["text", "tool", "tool", "step"]
    # Its last text is the result the harness read, which the review's page shows as its findings.
    assert json.loads(entries[-2]["text"])["summary"] == found["summary"]
    # The prompt canopy rendered for the reviewer, kept beside its log as a run's is.
    assert transcript["prompt"]["text"].startswith("# canopy reviewer\n")
    assert c.get("/api/reviews/3/transcript").json()["prompt"] is None
    output = c.get("/api/reviews/4/output").json()
    assert output["status"] == "read"
    assert output["text"].startswith("--- reviewer stdout ---")
    assert output["text"].endswith("--- reviewer exit 0 ---\n")


def test_a_reviews_page_names_the_models_that_served_its_reviewer(backend: Backend) -> None:
    served = client(None, backend).get("/api/reviews/4").json()["models"]
    assert (served["status"], [m["model"] for m in served["models"]]) == ("found", ["openai/gpt-5"])


def test_a_review_that_ended_badly_shows_the_call_it_ended_on(backend: Backend) -> None:
    entries = client(None, backend).get("/api/reviews/3/transcript").json()["entries"]
    failed = [e for e in entries if e["kind"] == "tool" and e["status"] == "error"]
    assert [e["output"] for e in failed] == ["File not found: checkout/src/billing/client.ts"]


def test_a_running_review_has_no_session_yet(backend: Backend, tmp_path: Path) -> None:
    # The reviewer's output reaches the log when it ends, and its session with it.
    with backend.open() as ctx:
        run_id = review_runs.insert_review_run(
            ctx.conn,
            tick_id=1,
            pr_url=mock_reviews.PR_95,
            sha="abc1234",
            ticket=None,
            repo="web",
            purpose="request",
            logs_dir=tmp_path,
        )
    c = client(None, backend)
    assert c.get(f"/api/reviews/{run_id}/transcript").json()["status"] == "no_session"
    assert c.get(f"/api/reviews/{run_id}").json()["new_tokens"] is None


def test_a_diff_that_is_a_link_is_not_followed(backend: Backend, tmp_path: Path) -> None:
    with backend.open() as ctx:
        row = review_runs.get_review_run(ctx.conn, 2)
    assert row is not None
    path = review_diff.path_for(row.log_path)
    elsewhere = tmp_path / "elsewhere.diff"
    elsewhere.write_text(mock_reviews.DIFF_88)
    path.unlink()
    path.symlink_to(elsewhere)
    assert client(None, backend).get("/api/reviews/2").json()["diff"] is None


def test_a_finding_dismissed_from_the_web_is_marked_as_the_cli_marks_it(backend: Backend) -> None:
    c = client(None, backend, key=SECRET)
    headers = signed_in(c)
    url = "/api/reviews/4/dismissals"

    assert c.post(url, json={"finding": 2}, headers={"origin": headers["origin"]}).status_code == 403
    assert c.post(url, json={"finding": 0}, headers=headers).status_code == 422
    for path, finding, guard in [(url, 4, "unknown"), ("/api/reviews/3/dismissals", 1, "unknown")]:
        refused = c.post(path, json={"finding": finding}, headers=headers)
        assert (refused.status_code, refused.json()["detail"]["guard"]) == (409, guard)

    assert c.post(url, json={"finding": 2}, headers=headers).json() == {"run": 4, "finding": 2, "dismissed": True}
    found = c.get("/api/reviews/4").json()
    assert [f["dismissed"] for f in found["findings"]] == [False, True, False]
    with backend.open() as ctx:
        row = ctx.conn.execute("SELECT channel FROM review_dismissals WHERE review_run_id = 4").fetchone()
        assert row["channel"] == "web"

    assert c.post(url, json={"finding": 2, "undo": True}, headers=headers).json()["dismissed"] is False
    assert not any(f["dismissed"] for f in c.get("/api/reviews/4").json()["findings"])


def test_findings_sent_from_the_web_reach_the_ticket_as_the_cli_sends_them(backend: Backend) -> None:
    c = client(None, backend, key=SECRET)
    headers = signed_in(c)
    url = "/api/reviews/4/sends"
    sent = {"findings": [3, 1], "submission": "send-0001"}

    assert c.post(url, json=sent, headers={"origin": headers["origin"]}).status_code == 403
    assert c.post(url, json={**sent, "findings": []}, headers=headers).status_code == 422
    # Review 4 is of ABC-099's own PR; review 2 of a PR review.query matched, which the loop did not open.
    assert c.get("/api/reviews/4").json()["sendable"] is True
    assert c.get("/api/reviews/2").json()["sendable"] is False
    for path, findings, guard in [
        (url, [4], "unknown"),
        ("/api/reviews/3/sends", [1], "unknown"),
    ]:
        refused = c.post(path, json={**sent, "findings": findings}, headers=headers)
        assert (refused.status_code, refused.json()["detail"]["guard"]) == (409, guard)

    recorded = c.post(url, json=sent, headers=headers).json()
    assert {k: recorded[k] for k in ("run", "findings", "ticket_key", "new")} == {
        "run": 4,
        "findings": [1, 3],
        "ticket_key": "ABC-099",
        "new": True,
    }
    with backend.open() as ctx:
        message = present(db.get_message(ctx.conn, recorded["message_id"]))
        assert (message.subject_id, message.source, message.channel) == ("ABC-099", "operator", "web")
        assert message.body == (
            f"Address findings 1 and 3 of canopy's review run 4, of commit {mock_reviews.SHA_88[:12]}. "
            "Leave its finding 2 alone."
        )
    # A retry of the same submission records nothing new.
    again = c.post(url, json=sent, headers=headers).json()
    assert (again["message_id"], again["new"]) == (recorded["message_id"], False)


def test_a_review_seen_from_the_web_is_marked_as_the_cli_marks_it(backend: Backend, tmp_path: Path) -> None:
    """The mock operator has seen every review but review 2; a mark goes through `conversation.see`'s guards (§22)."""
    c = client(None, backend, key=SECRET)
    headers = signed_in(c)

    def seen() -> list[tuple[int, bool]]:
        return [(r["id"], r["seen"]) for r in c.get("/api/reviews").json()]

    assert seen() == [(5, True), (4, True), (3, True), (2, False), (1, True)]
    assert c.get("/api/reviews/2").json()["review"]["seen"] is False
    assert c.post("/api/seen", json={"refs": ["review:2"]}, headers={"origin": headers["origin"]}).status_code == 403
    assert c.post("/api/seen", json={"refs": []}, headers=headers).status_code == 422
    with backend.open() as ctx:
        running = review_runs.insert_review_run(
            ctx.conn,
            tick_id=1,
            pr_url=mock_reviews.PR_95,
            sha="abc1234",
            ticket=None,
            repo="web",
            purpose="request",
            logs_dir=tmp_path,
        )
    for ref, guard in [(f"review:{running}", "running"), ("review:99", "unknown"), ("ABC-099", "unsupported")]:
        refused = c.post("/api/seen", json={"refs": ["review:2", ref]}, headers=headers)
        assert (refused.status_code, refused.json()["detail"]["guard"]) == (409, guard)
    assert seen()[4] == (2, False)

    marked = c.post("/api/seen", json={"refs": ["review:2", "review:4", "review:2"]}, headers=headers).json()
    assert marked == {"refs": ["review:2", "review:4"], "new": ["review:2"]}
    assert all(s for i, s in seen() if i != running)
    with backend.open() as ctx:
        row = ctx.conn.execute("SELECT channel FROM seen WHERE kind = 'review' AND subject = '2'").fetchone()
        assert row["channel"] == "web"


def test_a_diff_retention_removed_says_after_how_many_days(backend: Backend) -> None:
    c = client(None, backend)
    assert c.get("/api/reviews/4").json()["diff_removed_after_days"] is None
    with backend.open() as ctx:
        gc_passes.record(
            ctx.conn,
            tick_id=None,
            started_at=datetime(2026, 11, 1, tzinfo=UTC),
            run_files_days=30,
            tick_files_days=7,
            run_cutoff="2026-10-20T00:00:00.000Z",
            tick_cutoff="2026-10-20T00:00:00.000Z",
            removed={},
            failures=0,
            error=None,
        )
        review_diff.path_for(present(review_runs.get_review_run(ctx.conn, 4)).log_path).unlink()
    found = c.get("/api/reviews/4").json()
    assert (found["diff"], found["diff_removed_after_days"]) == (None, 30)


def test_the_mock_drafts_a_review_of_a_coworkers_pr_and_its_poster_publishes_it(backend: Backend) -> None:
    """Carol's PR's review is a draft (DESIGN §34): two comments on its diff, a finding in the body, posted nowhere."""
    c = client(None, backend, key=SECRET)
    headers = signed_in(c)
    draft = c.get("/api/reviews/5").json()["draft"]
    assert (draft["status"], draft["version"]) == ("waiting", 1)
    assert [(m["path"], m["line"], m["finding"], m["file"]) for m in draft["comments"]] == [
        ("api/upstream.py", 15, 1, 0),
        ("api/upstream.py", 9, 2, 0),
    ]
    assert "No test stops the backoff" in draft["body"]
    # The clean review has one too, its summary alone; one of the loop's own PRs has none.
    assert c.get("/api/reviews/2").json()["draft"]["comments"] == []
    assert c.get("/api/reviews/4").json()["draft"] is None
    published = c.post("/api/reviews/5/draft/publish", json={"hash": draft["hash"], "submit": True}, headers=headers)
    assert published.status_code == 200, published.text
    done = published.json()["draft"]
    assert done["status"] == "published"
    assert done["published_url"].startswith(f"{mock_reviews.PR_14}#pullrequestreview-")
