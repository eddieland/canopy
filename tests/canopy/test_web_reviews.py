"""The web UI's reviews (DESIGN §21, Reading reviews): canopy's shadow PR review, posted nowhere (D114).

The findings and the diff are untrusted text. The one write is dismissing a finding, as `canopy dismiss review:ID`.
"""

from pathlib import Path

import pytest

from canopy.core import db, review_diff
from canopy.serve import mock, mock_reviews
from canopy.serve.backend import Backend
from tests.canopy.test_serve import SECRET, client, signed_in


@pytest.fixture
def backend(tmp_path: Path) -> Backend:
    return mock.seed(tmp_path / "mock")


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
    # Its worst finding, which colors its verdict: none for a clean review or one that reported nothing.
    assert [r["worst"] for r in listed] == ["major", None, None, "blocking"]


def test_a_review_anchors_its_findings_on_its_diff(backend: Backend) -> None:
    found = client(None, backend).get("/api/reviews/4").json()
    assert found["review"]["impact"] == "normal"
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
    path = review_diff.path_for(str(row["log_path"]))
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
