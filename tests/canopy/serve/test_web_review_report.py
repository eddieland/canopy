"""The web UI's Reviews report (DESIGN §11): who reviews canopy's PRs, how soon, and what answering their feedback cost.

Reads only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from canopy.core import db, records, spend, sql
from canopy.core.vocab import (
    DismissalReason,
    PlanEffort,
    PlanStatus,
    PrState,
    ReviewDraftStatus,
    ReviewItem,
    ReviewRunStatus,
    ReviewState,
    RunKind,
)
from canopy.infra import resources
from tests.canopy.helpers import context, earlier, present, worker_ran
from tests.canopy.web_helpers import client, signed_in_client

if TYPE_CHECKING:
    import sqlite3

    from canopy.serve.backend import Backend
    from tests.conftest import CanopyEnv

TIMED = "https://github.com/acme/web/pull/7"
UNTIMED = "https://github.com/acme/web/pull/8"
OLD = "https://github.com/acme/web/pull/9"


def test_the_reviews_report_reads_the_mocks_week_and_month(backend: Backend) -> None:
    """The mock's week holds PR 88 alone, timed on GitHub's clock; its 30 days the landed PRs, some read before."""
    c = client(None, backend)
    week = c.get("/api/reports/reviews").json()
    assert (week["days"], week["since"], week["until"]) == (7, "2026-10-02T00:00:00Z", "2026-10-09T00:00:00Z")
    [pr] = week["pull_requests"]
    assert (pr["url"], pr["ticket_key"], pr["reviews"], pr["comments"], pr["rounds"]) == (
        "https://github.com/acme/web/pull/88",
        "ABC-099",
        2,
        3,
        1,
    )
    # Asked for at 10:45, alice's first review at 11:12.
    assert (week["first_reviews"], week["median_first_review_hours"], week["untimed"]) == (1, 0.45, 0)
    assert week["per_day"][-1]["first_reviews"] == [1, 0, 0, 0]
    assert [r["author"] for r in week["reviewers"]] == ["alice", "carol", "bob"]
    assert week["canopy_trusted"] is True

    month = c.get("/api/reports/reviews", params={"days": 30}).json()
    assert (month["first_reviews"], month["untimed"]) == (5, 2)
    assert [(e["effort"], e["plans"], e["resumes"]) for e in month["efforts"]] == [
        ("small", 2, 1),
        ("medium", 1, 0),
        (None, 5, 0),
    ]
    assert {r["approved_channel"] for r in month["rounds"]} == {None, "web", "cli", "planner"}
    assert c.get("/api/reports/reviews", params={"days": 0}).status_code == 422
    assert c.get("/api/reports/reviews", params={"days": spend.MAX_DAYS + 1}).status_code == 422


def test_the_reviews_report_reads_feedback_rounds_and_canopys_reviewer_from_the_journal(canopy_env: CanopyEnv) -> None:
    """A journal by hand: a PR with GitHub's times and one without, feedback, plans and their resumes, review runs."""
    canopy_env.write_private('[trust]\ntrusted_reviewers = ["dana", "canopy:review"]\n')
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    conn, now = ctx.conn, datetime.now(UTC)
    worker_ran(conn, RunKind.IMPLEMENT, earlier(now, 3), prs={"web": TIMED}, cost=1.0)
    worker_ran(conn, RunKind.IMPLEMENT, earlier(now, 3), key="PROJ-2", prs={"web": UNTIMED})
    worker_ran(conn, RunKind.IMPLEMENT, earlier(now, 40), key="PROJ-3", prs={"web": OLD})
    # Ready two and a half days ago, a review asked for two hours later, merged a day ago.
    observed(
        conn,
        TIMED,
        ready_at=earlier(now, 2, 12),
        review_requested_at=earlier(now, 2, 10),
        merged_at=earlier(now, 1),
    )
    observed(conn, UNTIMED)
    observed(conn, OLD)
    said(conn, TIMED, "erin", earlier(now, 2, 11), ReviewState.COMMENTED)  # before a review was asked for
    said(conn, TIMED, "dana", earlier(now, 2, 7), ReviewState.CHANGES_REQUESTED)  # three hours after
    said(conn, TIMED, "erin", earlier(now, 2, 5))
    said(conn, TIMED, "dana", earlier(now, 1, 2), ReviewState.APPROVED)
    said(conn, TIMED, "op", earlier(now, 1, 3), ReviewState.COMMENTED)  # the PR's author: not feedback
    said(conn, TIMED, "ci-bot", earlier(now, 1, 3), ReviewState.CHANGES_REQUESTED, bot=True)
    said(conn, TIMED, "dana", earlier(now, 1, 3), ReviewState.PENDING)  # not yet submitted
    said(conn, UNTIMED, "carol", earlier(now, 1), ReviewState.APPROVED)
    said(conn, OLD, "carol", earlier(now, 39), ReviewState.APPROVED)
    # Each plan but the newest superseded by the next, as a ticket holds one current plan.
    first = plan(conn, earlier(now, 2, 4), cost=0.5, effort=PlanEffort.SMALL, channel="planner")
    for cost in (1.5, 0.5):
        resume = worker_ran(conn, RunKind.RESUME, earlier(now, 2, 3), prs={"web": TIMED}, cost=cost)
        records.update(records.Run).set(feedback_plan_id=first).where("id = ?", resume).run(conn)
    plan(conn, earlier(now, 1, 12), cost=None, effort=PlanEffort.MEDIUM, channel="web", current=True)
    plan(conn, earlier(now, 20), cost=0.4, effort=None, channel=None)
    reviewed = [
        reviewed_by(conn, earlier(now, 2), ReviewRunStatus.DONE, cost=0.2),
        reviewed_by(conn, earlier(now, 2), ReviewRunStatus.DONE, cost=0.3),
        reviewed_by(conn, earlier(now, 1), ReviewRunStatus.FAILED, cost=None, purpose="request"),
        reviewed_by(conn, earlier(now, 20), ReviewRunStatus.DONE, cost=0.9),
    ]
    for finding, (reason, at) in enumerate(
        [(DismissalReason.WRONG, earlier(now, 1)), (None, earlier(now, 1)), (DismissalReason.WRONG, earlier(now, 19))],
        start=1,
    ):
        records.insert(
            records.ReviewDismissal,
            review_run_id=reviewed[0],
            finding=finding,
            dismissed_at=at,
            channel="web",
            reason=reason,
        ).run(conn)
    for run_id, status in ((reviewed[0], ReviewDraftStatus.PUBLISHED), (reviewed[1], ReviewDraftStatus.WAITING)):
        records.insert(
            records.ReviewDraft,
            review_run_id=run_id,
            pr_url=TIMED,
            sha="abc",
            status=status,
            created_at=earlier(now, 2),
            publish_version=1 if status is ReviewDraftStatus.PUBLISHED else None,
            published_at=earlier(now, 1) if status is ReviewDraftStatus.PUBLISHED else None,
        ).run(conn)

    c, _ = signed_in_client(ctx)
    found = c.get("/api/reports/reviews").json()
    assert (found["reviews"], found["first_reviews"], found["median_first_review_hours"]) == (4, 1, 3.0)
    assert (found["untimed"], found["waiting"]) == (1, 0), "the PR without GitHub's times is counted apart"
    assert sum(d["first_reviews"][1] for d in found["per_day"]) == 1, "three hours: one to four"
    assert [
        (r["author"], r["trusted"], r["reviews"], r["changes_requested"], r["comments"], r["median_wait_hours"])
        for r in found["reviewers"]
    ] == [
        ("dana", True, 2, 1, 0, 3.0),
        ("erin", False, 1, 0, 1, None),
        ("carol", False, 1, 0, 0, None),
    ]
    timed, untimed = found["pull_requests"]
    assert (timed["url"], timed["first_review_hours"], timed["hours_to_merge"]) == (TIMED, 3.0, 36.0)
    assert (timed["reviews"], timed["changes_requested"], timed["comments"]) == (3, 1, 1)
    assert (timed["rounds"], timed["cost_usd"]) == (2, 2.5)
    assert (untimed["url"], untimed["waiting_since"], untimed["first_review_hours"]) == (UNTIMED, None, None)
    assert [
        (r["effort"], r["approved_channel"], r["resumes"], r["plan_cost_usd"], r["resume_cost_usd"])
        for r in found["rounds"]
    ] == [("medium", "web", 0, None, None), ("small", "planner", 2, 0.5, 2.0)]
    assert [(e["effort"], e["plans"], e["resumes"], e["resume_cost_usd"]) for e in found["efforts"]] == [
        ("small", 1, 2, 2.0),
        ("medium", 1, 0, None),
    ]
    assert [(r["purpose"], r["status"], r["runs"], r["cost_usd"]) for r in found["review_runs"]] == [
        ("own", "done", 2, pytest.approx(0.5)),
        ("request", "failed", 1, None),
    ]
    assert found["dismissals"] == [{"reason": None, "findings": 1}, {"reason": "wrong", "findings": 1}]
    assert found["drafts"] == [{"status": "published", "drafts": 1}, {"status": "waiting", "drafts": 1}]
    assert found["canopy_trusted"] is True


def observed(
    conn: sqlite3.Connection,
    url: str,
    *,
    ready_at: str | None = None,
    review_requested_at: str | None = None,
    merged_at: str | None = None,
) -> None:
    """The reader's read of `url`, authored by `op`, with GitHub's times where given: none, as one read before."""
    records.insert(
        records.ObservedPr,
        url=url,
        repository="acme/web",
        number=int(url.rsplit("/", 1)[-1]),
        state=PrState.OPEN if merged_at is None else PrState.MERGED,
        draft=False,
        author="op",
        observed_at=db.format_time(datetime.now(UTC)),
        created_at=ready_at,
        ready_at=ready_at,
        review_requested_at=review_requested_at,
        merged_at=merged_at,
    ).run(conn)


def said(
    conn: sqlite3.Connection,
    url: str,
    author: str,
    at: str,
    state: ReviewState | None = None,
    *,
    bot: bool = False,
) -> None:
    """A review of `url` in `state` by `author` at `at`, or a comment without a state."""
    [(count,)] = sql.execute(conn, sql.select("count(*)").from_("observed_reviews")).fetchall()
    records.insert(
        records.ObservedReview,
        pr_url=url,
        item=ReviewItem.COMMENT if state is None else ReviewItem.REVIEW,
        id=100 + int(count),
        author=author,
        bot=bot,
        state=state,
        created_at=at,
        body="b",
        thread_id=None if state is not None else f"t{count}",
        observed_at=at,
    ).run(conn)


def plan(
    conn: sqlite3.Connection,
    at: str,
    *,
    cost: float | None,
    effort: PlanEffort | None,
    channel: str | None,
    current: bool = False,
) -> int:
    """A feedback plan for PROJ-1 that read `TIMED`, written at `at` by a run that cost `cost`; its id.

    Approved through `channel` where one is given, and superseded unless `current`.
    """
    run_id = worker_ran(conn, RunKind.FEEDBACK_PLAN, at, cost=cost)
    plan_id = present(
        records.insert(
            records.FeedbackPlan,
            ticket_key="PROJ-1",
            run_id=run_id,
            created_at=at,
            status=PlanStatus.SUPERSEDED if not current else PlanStatus.APPROVED,
            sha256="0" * 64,
            size=1,
            approved_sha256=None if channel is None else "0" * 64,
            approved_at=None if channel is None else at,
            approved_channel=channel,
            approved_reason="a one-line fix" if channel == "planner" else None,
            effort=effort,
        )
        .run(conn)
        .lastrowid,
    )
    records.update(records.Run).set(feedback_plan_id=plan_id).where("id = ?", run_id).run(conn)
    records.insert(records.FeedbackPlanPr, plan_id=plan_id, pr_url=TIMED).run(conn)
    return plan_id


def reviewed_by(
    conn: sqlite3.Connection,
    at: str,
    status: ReviewRunStatus,
    *,
    cost: float | None,
    purpose: str = "own",
) -> int:
    """A review run of `TIMED` that started at `at` and ended in `status`; its id."""
    tick = present(records.insert(records.Tick, started_at=at, dry_run=0).run(conn).lastrowid)
    return present(
        records.insert(
            records.ReviewRun,
            tick_id=tick,
            pr_url=TIMED,
            sha="abc",
            started_at=at,
            status=status,
            log_path="l",
            purpose=purpose,
            cost_usd=cost,
        )
        .run(conn)
        .lastrowid,
    )
