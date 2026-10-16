"""The web UI's pull requests (DESIGN §22): each PR the journal knows, with its runs, reviews, and decisions.

Nothing here writes to a PR; a review request is the journal's.
"""

import json

import pytest

from canopy.core import conversation, db
from canopy.core.vocab import TickStatus
from canopy.serve import mock_reviews, pull_requests
from canopy.serve.backend import Backend
from tests.canopy.web_helpers import client


def test_the_list_has_each_pr_once_with_its_ticket_branch_and_latest_review(backend: Backend) -> None:
    by_url = {p["url"]: p for p in client(None, backend).get("/api/pull-requests").json()}
    assert set(by_url) == {mock_reviews.PR_88, mock_reviews.PR_91, mock_reviews.PR_12, mock_reviews.PR_95}
    ours = by_url[mock_reviews.PR_88]
    assert (ours["ticket_key"], ours["ticket_title"], ours["branch"], ours["phase"], ours["reviews"]) == (
        "ABC-099",
        "Debounce search input",
        "agent/ABC-099-search",
        "in_review",
        2,
    )
    assert ours["latest_review"]["id"] == 4  # the newest of its two review runs
    theirs = by_url[mock_reviews.PR_12]
    assert (theirs["ticket_key"], theirs["branch"], theirs["latest_review"]["verdict"]) == (None, None, "clean")
    # A PR the operator asked to have reviewed is listed before its first review, with its request and repository.
    requested = by_url[mock_reviews.PR_95]
    assert (requested["reviews"], requested["review_request"]["end_reason"]) == (0, None)
    assert theirs["review_request"] is None


def test_a_prs_page_has_the_runs_that_pushed_to_it_its_reviews_and_its_decisions(backend: Backend) -> None:
    page = client(None, backend).get("/api/pull-request", params={"url": mock_reviews.PR_88}).json()
    assert [(r["id"], r["kind"]) for r in page["runs"]] == [(39, "implement")]
    assert [r["id"] for r in page["reviews"]] == [4, 1]
    assert {d["action"] for d in page["decisions"]} == {"wait", "attention:needs_reviewer"}
    assert all(d["pr"] == mock_reviews.PR_88 for d in page["decisions"])


def test_a_prs_cost_is_every_run_that_pushed_to_it_and_every_review_of_it(backend: Backend) -> None:
    with backend.open() as ctx:
        for table, row_id, cost in (("runs", 39, 1.5), ("review_runs", 1, None), ("review_runs", 4, 0.25)):
            ctx.conn.execute(f"UPDATE {table} SET cost_usd = ? WHERE id = ?", (cost, row_id))  # noqa: S608
    page = client(None, backend).get("/api/pull-request", params={"url": mock_reviews.PR_88}).json()
    assert page["cost"] == {"runs": 1, "reviews": 2, "priced": 2, "cost_usd": pytest.approx(1.75)}


def test_a_prs_cost_counts_its_runs_past_the_20_its_page_lists(backend: Backend) -> None:
    result = json.dumps({"status": "done", "prs": {"web": mock_reviews.PR_88}})
    with backend.open() as ctx:
        ctx.conn.execute("UPDATE review_runs SET cost_usd = NULL")
        ctx.conn.execute("UPDATE runs SET cost_usd = 0.5 WHERE id = 39")
        for _ in range(pull_requests.PR_RUNS):
            ctx.conn.execute(
                "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, ended_at, status, result_json, "
                "log_path, cost_usd) SELECT tick_id, ticket_key, kind, branch, started_at, ended_at, status, ?, "
                "log_path, 1.0 FROM runs WHERE id = 39",
                (result,),
            )
    page = client(None, backend).get("/api/pull-request", params={"url": mock_reviews.PR_88}).json()
    assert len(page["runs"]) == pull_requests.PR_RUNS
    assert (page["cost"]["runs"], page["cost"]["cost_usd"]) == (pull_requests.PR_RUNS + 1, pytest.approx(20.5))


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
            "UPDATE runs SET result_json = ? WHERE id = 39",
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
    assert page["cost"] == {"runs": 0, "reviews": 0, "priced": 0, "cost_usd": None}
    assert c.get("/api/pull-request", params={"url": "https://github.com/acme/web/pull/404"}).status_code == 404
    for bad in ("javascript:alert(1)", "https://example.test/a b", "https://" + "a" * 300):
        assert c.get("/api/pull-request", params={"url": bad}).status_code == 422


def test_a_tickets_title_is_one_printable_line(backend: Backend) -> None:
    with backend.open() as ctx:
        db.set_ticket(ctx.conn, "ABC-099", ctx.repo, title="Debounce\x1b[2J\n search")
    [ours] = [p for p in client(None, backend).get("/api/pull-requests").json() if p["ticket_key"] == "ABC-099"]
    assert ours["ticket_title"] == " ".join(conversation.printable("Debounce\x1b[2J\n search").split())
