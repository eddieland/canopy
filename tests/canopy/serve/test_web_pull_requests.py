"""The web UI's pull requests (DESIGN §22): each PR the journal knows, with its runs, reviews, and decisions.

Nothing here writes to a PR; a review request is the journal's.
"""

import json
from unittest import mock

import pytest

from canopy.core import conversation, db
from canopy.core.vocab import TickStatus
from canopy.infra import procs
from canopy.serve import mock_reviews, pull_requests
from canopy.serve.backend import Backend
from tests.canopy.web_helpers import SECRET, client, signed_in


def test_the_list_has_each_pr_once_with_its_ticket_branch_and_latest_review(backend: Backend) -> None:
    by_url = {p["url"]: p for p in client(None, backend).get("/api/pull-requests").json()}
    assert set(by_url) == {mock_reviews.PR_88, mock_reviews.PR_91, mock_reviews.PR_12, mock_reviews.PR_95}
    ours = by_url[mock_reviews.PR_88]
    assert (ours["ticket_key"], ours["ticket_title"], ours["branch"], ours["phase"], ours["reviews"]) == (
        "ABC-099",
        "Debounce search input",
        "agent/ABC-099-search",
        "review_pending",
        2,
    )
    assert ours["latest_review"]["id"] == 4  # the newest of its two review runs
    assert ours["title"] == "ABC-099: debounce the search box by 250 ms"  # the PR's own, not its ticket's
    theirs = by_url[mock_reviews.PR_12]
    assert (theirs["ticket_key"], theirs["branch"], theirs["latest_review"]["verdict"]) == (None, None, "clean")
    # A PR the operator asked to have reviewed is listed before its first review, with its request and repository.
    requested = by_url[mock_reviews.PR_95]
    assert (requested["reviews"], requested["review_request"]["end_reason"]) == (0, None)
    assert theirs["review_request"] is None
    assert theirs["title"] == "Bump the retry budget for flaky upstreams"  # its review reported it


def test_a_prs_page_has_the_runs_that_pushed_to_it_its_reviews_and_its_decisions(backend: Backend) -> None:
    page = client(None, backend).get("/api/pull-request", params={"url": mock_reviews.PR_88}).json()
    assert [(r["id"], r["kind"]) for r in page["runs"]] == [(45, "resume"), (39, "implement")]
    assert [r["id"] for r in page["reviews"]] == [4, 1]
    assert page["threads"]  # run 45 drafted replies to its threads, which canopy read
    assert {d["action"] for d in page["decisions"]} == {"wait", "attention:needs_reviewer"}
    assert all(d["pr"] == mock_reviews.PR_88 for d in page["decisions"])


def test_a_prs_cost_is_every_run_that_pushed_to_it_and_every_review_of_it(backend: Backend) -> None:
    with backend.open() as ctx:
        for table, row_id, cost in (
            ("runs", 39, 1.5),
            ("runs", 45, 0.5),
            ("review_runs", 1, None),
            ("review_runs", 4, 0.25),
        ):
            ctx.conn.execute(f"UPDATE {table} SET cost_usd = ? WHERE id = ?", (cost, row_id))  # noqa: S608
    page = client(None, backend).get("/api/pull-request", params={"url": mock_reviews.PR_88}).json()
    assert page["cost"] == {"runs": 2, "reviews": 2, "priced": 3, "cost_usd": pytest.approx(2.25)}


def test_a_prs_cost_counts_its_runs_past_the_20_its_page_lists(backend: Backend) -> None:
    result = json.dumps({"status": "done", "prs": {"web": mock_reviews.PR_88}})
    with backend.open() as ctx:
        ctx.conn.execute("UPDATE review_runs SET cost_usd = NULL")
        ctx.conn.execute("UPDATE runs SET cost_usd = 0.25 WHERE id IN (39, 45)")
        for _ in range(pull_requests.PR_RUNS):
            ctx.conn.execute(
                "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, ended_at, status, result_json, "
                "log_path, cost_usd) SELECT tick_id, ticket_key, kind, branch, started_at, ended_at, status, ?, "
                "log_path, 1.0 FROM runs WHERE id = 39",
                (result,),
            )
    page = client(None, backend).get("/api/pull-request", params={"url": mock_reviews.PR_88}).json()
    assert len(page["runs"]) == pull_requests.PR_RUNS
    assert (page["cost"]["runs"], page["cost"]["cost_usd"]) == (pull_requests.PR_RUNS + 2, pytest.approx(20.5))


def test_a_loop_pr_with_no_review_is_listed_with_the_run_working_it(backend: Backend) -> None:
    pr = "https://github.com/acme/mobile/pull/5"
    with backend.open() as ctx:
        db.set_unit(ctx.conn, "ABC-101", ctx.repo, "mobile", phase="ci_failing", pr_url=pr)
    c = client(None, backend)
    [listed] = [p for p in c.get("/api/pull-requests").json() if p["url"] == pr]
    # Run 41 implements ABC-101 now: it has no result yet, so the PR's page keeps it.
    assert (listed["ticket_key"], listed["running_run"], listed["reviews"]) == ("ABC-101", 41, 0)
    page = c.get("/api/pull-request", params={"url": pr}).json()
    assert [r["id"] for r in page["runs"]] == [41]
    assert (page["pull_request"]["phase"], page["reviews"], page["decisions"]) == ("ci_failing", [], [])


def test_a_run_that_reported_another_pr_is_not_this_ones(backend: Backend) -> None:
    with backend.open() as ctx:
        ctx.conn.execute(
            "UPDATE runs SET result_json = ? WHERE id IN (39, 45)",
            (json.dumps({"status": "done", "prs": {"web": "https://github.com/acme/web/pull/1"}}),),
        )
    page = client(None, backend).get("/api/pull-request", params={"url": mock_reviews.PR_88}).json()
    assert page["runs"] == []


def test_a_pr_only_decisions_name_has_a_page_and_anything_else_is_refused(backend: Backend) -> None:
    pr = "https://github.com/acme/api/pull/13"
    with backend.open() as ctx:
        tick_id = db.start_tick(ctx.conn, dry_run=False)
        db.record_decision(ctx.conn, tick_id, None, "wait", "checks still running", pr=pr)
        db.finish_tick(ctx.conn, tick_id, TickStatus.OK, "test")
    c = client(None, backend)
    assert pr not in {p["url"] for p in c.get("/api/pull-requests").json()}  # decisions are not a source
    page = c.get("/api/pull-request", params={"url": pr}).json()
    assert (page["runs"], page["reviews"], [d["action"] for d in page["decisions"]]) == ([], [], ["wait"])
    assert not page["threads"]
    assert page["cost"] == {"runs": 0, "reviews": 0, "priced": 0, "cost_usd": None}
    assert c.get("/api/pull-request", params={"url": "https://github.com/acme/web/pull/404"}).status_code == 404
    for bad in ("javascript:alert(1)", "https://example.test/a b", "https://" + "a" * 300):
        assert c.get("/api/pull-request", params={"url": bad}).status_code == 422


def test_a_tickets_title_is_one_printable_line(backend: Backend) -> None:
    with backend.open() as ctx:
        db.set_ticket(ctx.conn, "ABC-099", ctx.repo, title="Debounce\x1b[2J\n search")
    [ours] = [p for p in client(None, backend).get("/api/pull-requests").json() if p["ticket_key"] == "ABC-099"]
    assert ours["ticket_title"] == " ".join(conversation.printable("Debounce\x1b[2J\n search").split())


def test_a_prs_own_title_is_the_latest_reported_one_printable_and_outlives_its_unit(backend: Backend) -> None:
    with backend.open() as ctx:
        db.set_pr_title(ctx.conn, mock_reviews.PR_88, "ABC-099: debounce\x1b[2J\n the box")
        with db.transaction(ctx.conn):
            db.forget_ticket(ctx.conn, "ABC-099", channel="cli", branch=None, prs=[])
    page = client(None, backend).get("/api/pull-request", params={"url": mock_reviews.PR_88}).json()
    assert page["pull_request"]["title"] == " ".join(
        conversation.printable("ABC-099: debounce\x1b[2J\n the box").split()
    )


def test_the_mock_journal_places_run_45s_drafts_on_the_threads_of_pr_88(backend: Backend) -> None:
    found = client(None, backend).get("/api/pull-request/threads", params={"url": mock_reviews.PR_88}).json()
    assert (found["diff_run"], found["diff_head"]) == (45, found["head_sha"])
    assert [(t["path"], t["diff_line"], [d["number"] for d in t["drafts"]]) for t in found["threads"]] == [
        ("src/search/SearchBox.tsx", 6, [2]),
        ("src/search/useSearch.ts", None, []),  # outdated and resolved: under its file, answered by nothing
        ("src/search/useSearch.ts", 16, [1]),
    ]
    assert [(d["number"], d["kind"]) for d in found["pr_drafts"]] == [(3, "pr")]
    assert found["threads"][0]["drafts"][0]["edited"]


def test_a_draft_sent_from_the_mock_posts_nothing_and_reads_as_sent(backend: Backend) -> None:
    c = client(None, backend, key=SECRET)
    headers = signed_in(c)
    found = c.get("/api/pull-request/threads", params={"url": mock_reviews.PR_88}).json()
    wanted = [{"run": d["run"], "number": d["number"], "hash": d["hash"]} for d in found["threads"][2]["drafts"]]
    # The stand-in answers for both GitHub programs: nothing starts a process.
    with mock.patch.object(procs.SubprocessRunner, "run", autospec=True) as ran:
        sent = c.post("/api/drafts/send", json={"drafts": wanted}, headers=headers)
    assert sent.status_code == 200, sent.text
    ran.assert_not_called()
    [posted] = sent.json()["posted"]
    assert (posted["number"], posted["status"]) == (1, "sent")
    assert posted["sent_url"].startswith(f"{mock_reviews.PR_88}#discussion_r")
