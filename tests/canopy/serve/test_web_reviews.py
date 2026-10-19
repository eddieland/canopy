"""The web UI's reviews (DESIGN §21, Reading reviews): canopy's shadow PR review, posted nowhere (D114).

The findings and the diff are untrusted text. The writes are dismissing a finding, as `canopy dismiss review:ID`, and
sending some to a worker, as `canopy send review:ID`.
"""

from pathlib import Path

from canopy.core import db, review_diff
from canopy.core.vocab import ReviewRunStatus
from canopy.serve import mock_reviews
from canopy.serve.backend import Backend
from tests.canopy.helpers import present
from tests.canopy.web_helpers import SECRET, client, signed_in


def test_the_reviews_list_is_every_review_run_newest_first(backend: Backend) -> None:
    listed = client(None, backend).get("/api/reviews").json()
    assert [(r["id"], r["pr_url"], r["state"], r["verdict"], r["findings"]) for r in listed] == [
        (4, mock_reviews.PR_88, "done", "findings", 3),
        (3, mock_reviews.PR_91, "failed", None, 0),
        (2, mock_reviews.PR_12, "done", "clean", 0),
        (1, mock_reviews.PR_88, "done", "findings", 1),
    ]
    assert (listed[0]["sha"], listed[0]["ticket_key"], listed[0]["repo"]) == (mock_reviews.SHA_88, "ABC-099", "web")
    assert listed[2]["ticket_key"] is None  # a PR review.query matched, with no ticket
    # Its worst finding, which colors its verdict, and how many are that bad, which its verdict says: none for a clean
    # review or one that reported nothing.
    assert [(r["worst"], r["worst_count"]) for r in listed] == [("major", 1), (None, 0), (None, 0), ("blocking", 1)]


def test_a_requested_pr_is_listed_from_the_request_until_its_review_starts_and_again_if_it_fails(
    backend: Backend, tmp_path: Path
) -> None:
    c = client(None, backend)
    # Asked for from the web UI, and no review of it has run yet: the reviews page shows it waiting on a tick.
    assert [(r["pr_url"], r["channel"]) for r in c.get("/api/review-requests").json()] == [(mock_reviews.PR_95, "web")]
    with backend.open() as ctx:
        run_id = db.insert_review_run(
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
    # A review too short to be worth it goes as it is.
    short = c.get("/api/reviews/3")
    assert len(short.content) < 1024
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
    missing = c.get("/api/reviews/99")
    assert (missing.status_code, missing.json()["detail"]) == (404, "no review run 99")
    assert c.get("/api/reviews/0").status_code == 422


def test_a_diff_that_is_a_link_is_not_followed(backend: Backend, tmp_path: Path) -> None:
    with backend.open() as ctx:
        row = db.get_review_run(ctx.conn, 2)
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
        assert (message["subject_id"], message["source"], message["channel"]) == ("ABC-099", "operator", "web")
        assert message["body"] == (
            f"Address findings 1 and 3 of canopy's review run 4, of commit {mock_reviews.SHA_88[:12]}. "
            "Leave its finding 2 alone."
        )
    # A retry of the same submission records nothing new.
    again = c.post(url, json=sent, headers=headers).json()
    assert (again["message_id"], again["new"]) == (recorded["message_id"], False)
