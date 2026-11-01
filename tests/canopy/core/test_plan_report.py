"""How the window's plans were approved, and what their tickets needed after (DESIGN §11, §25, #1872)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from canopy.core import db, plan_report, plans, records
from canopy.core.plan_metrics import Metrics
from canopy.core.plan_report import Outcome
from canopy.core.vocab import PlanEffort, PlannerApproval, PlanStatus, ResumeReason, RunKind
from tests.canopy.helpers import earlier, present, worker_ran

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from tests.conftest import CanopyEnv

# A plan of under a page, one of one to two pages in the plan editor, and one of four pages up with every kind of block
# that is not prose (`plan_metrics`).
SHORT = "# Plan\n\nOne step.\n"
MEDIUM = "# Plan\n\n" + "\n".join(f"- step {i}" for i in range(60)) + "\n"
LONG = (
    "## Steps\n\n"
    + "\n\n".join("word " * 40 for _ in range(100))
    + "\n\n```python\nprint(1)\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```mermaid\nflowchart LR\n  A --> B\n```\n"
)


def test_each_plan_goes_one_way_and_its_ticket_counts_the_resumes_after_its_approval(
    conn: sqlite3.Connection,
    canopy_env: CanopyEnv,
) -> None:
    """The planner's approval, the operator's as written and after a change, a plan sent back, and one dropped."""
    now = datetime.now(UTC)
    state = canopy_env.state_dir
    # PROJ-1: approved by its planner at strict, implemented, then two resumes, one for CI and one for review.
    by_planner = plan(
        conn,
        "PROJ-1",
        earlier(now, 3),
        level=PlannerApproval.STRICT,
        channel="planner",
        text=(state, SHORT),
    )
    worker_ran(conn, RunKind.IMPLEMENT, earlier(now, 2, 23), plan_id=by_planner)
    worker_ran(conn, RunKind.RESUME, earlier(now, 2), reasons=[ResumeReason.CI])
    worker_ran(conn, RunKind.RESUME, earlier(now, 1), reasons=[ResumeReason.CI, ResumeReason.REVIEW])
    # PROJ-2: approved as written an hour after, implemented, no resume, done.
    as_written = plan(
        conn,
        "PROJ-2",
        earlier(now, 3),
        level=PlannerApproval.OFF,
        channel="web",
        wait=1,
        text=(state, MEDIUM),
    )
    worker_ran(conn, RunKind.IMPLEMENT, earlier(now, 2), key="PROJ-2", plan_id=as_written)
    records.update(records.Ticket).set(done=1).where("key = ?", "PROJ-2").run(conn)
    # PROJ-3: a plan commented on and sent back, then its replacement edited and approved after three hours.
    sent_back = plan(conn, "PROJ-3", earlier(now, 4), level=PlannerApproval.OFF)
    commented(conn, "PROJ-3", earlier(now, 3, 22))
    edited = plan(conn, "PROJ-3", earlier(now, 3, 20), level=None, channel="cli", wait=3, text=(state, LONG), edit=True)
    # PROJ-4: superseded with nothing after, a skip; PROJ-5: still waiting, with a comment on it.
    dropped = plan(conn, "PROJ-4", earlier(now, 1), level=PlannerApproval.OFF)
    waiting = plan(conn, "PROJ-5", earlier(now, 0, 2), level=PlannerApproval.OFF, current=True)
    commented(conn, "PROJ-5", earlier(now, 0, 1))
    # Written before the week: outside it.
    plan(conn, "PROJ-6", earlier(now, 10), level=PlannerApproval.OFF, channel="web", wait=1)

    found = plan_report.report(conn, state, now, 7)

    rows = {r.plan_id: r for r in found.plans}
    assert set(rows) == {by_planner, as_written, sent_back, edited, dropped, waiting}
    assert [r.plan_id for r in found.plans] == [waiting, dropped, as_written, by_planner, edited, sent_back]
    outcomes = {
        by_planner: Outcome.PLANNER,
        as_written: Outcome.AS_WRITTEN,
        sent_back: Outcome.REPLACED,
        edited: Outcome.REVISED,
        dropped: Outcome.DROPPED,
        waiting: Outcome.WAITING,
    }
    assert {i: r.outcome for i, r in rows.items()} == outcomes
    planned = rows[by_planner]
    assert (planned.level, planned.implemented, planned.resumes, planned.done) == (
        PlannerApproval.STRICT,
        True,
        2,
        False,
    )
    assert planned.reasons == {ResumeReason.CI: 2, ResumeReason.REVIEW: 1}
    assert (rows[as_written].to_approve, rows[as_written].resumes, rows[as_written].done) == (
        timedelta(hours=1),
        0,
        True,
    )
    assert (rows[sent_back].comments, rows[edited].comments, rows[edited].earlier) == (1, 0, 1)
    assert (rows[edited].edited, rows[edited].level, rows[edited].implemented) == (True, None, False)
    assert rows[waiting].comments == 1

    assert [(g.level, g.outcome, g.plans, g.implemented, g.with_resume, g.resumes, g.done) for g in found.groups] == [
        (PlannerApproval.OFF, Outcome.AS_WRITTEN, 1, 1, 0, 0, 1),
        (PlannerApproval.STRICT, Outcome.PLANNER, 1, 1, 1, 2, 0),
        (None, Outcome.REVISED, 1, 0, 0, 0, 0),
    ]
    # Each plan is measured from its original; one with no file is not measured, and is left out of the lengths.
    assert rows[as_written].metrics == Metrics(words=121, lines=71, code_blocks=0, tables=0, diagrams=0)
    assert rows[edited].metrics == Metrics(words=4_005, lines=232, code_blocks=1, tables=1, diagrams=1)
    assert (rows[by_planner].metrics is not None, rows[sent_back].metrics) == (True, None)
    assert [(g.median_lines, g.median_words) for g in found.groups] == [(71, 121), (3, 3), (232, 4_005)]
    # The planner's approvals take no time, so the lengths are the operator's alone.
    assert [(n.low, n.high, n.plans, n.median_to_approve, n.as_written) for n in found.lengths] == [
        (50, 100, 1, timedelta(hours=1), 1),
        (200, None, 1, timedelta(hours=3), 0),
    ]
    assert (found.count(Outcome.REPLACED), found.count(Outcome.WAITING)) == (1, 1)


def test_a_week_with_no_plan_has_nothing_to_show(conn: sqlite3.Connection, canopy_env: CanopyEnv) -> None:
    """No plan, no rows: the groups and lengths are empty, not zeros."""
    found = plan_report.report(conn, canopy_env.state_dir, datetime.now(UTC), 7)
    assert (found.plans, found.groups, found.lengths) == ([], [], [])


def plan(
    conn: sqlite3.Connection,
    key: str,
    at: str,
    *,
    level: PlannerApproval | None,
    channel: str | None = None,
    wait: float = 0,
    text: tuple[Path, str] | None = None,
    edit: bool = False,
    current: bool = False,
) -> int:
    """A plan for `key` written at `at` by a run offered `level`; its id.

    Approved through `channel` `wait` hours after it was written where one is given, its file edited first with
    `edit`; else superseded unless `current`. Supersedes the ticket's plan before it, as a new plan does. With `text`,
    its files are written in that state directory as a planner's are; without, it has none.
    """
    run_id = worker_ran(conn, RunKind.PLAN, at, key=key)
    written = plans.Written(sha256="0" * 64, size=1) if text is None else plans.write(text[0], key, run_id, text[1])
    records.update(records.Run).set(plan_review=level).where("id = ?", run_id).run(conn)
    records.update(records.Plan).set(status=PlanStatus.SUPERSEDED).where("ticket_key = ?", key).run(conn)
    approved = None if channel is None else db.format_time(db.parse_time(at) + timedelta(hours=wait))
    waits = PlanStatus.PROPOSED if current else PlanStatus.SUPERSEDED
    status = waits if channel is None else PlanStatus.APPROVED
    return present(
        records.insert(
            records.Plan,
            ticket_key=key,
            run_id=run_id,
            created_at=at,
            status=status,
            sha256=written.sha256,
            size=written.size,
            approved_sha256=None if channel is None else "1" * 64 if edit else written.sha256,
            approved_at=approved,
            approved_channel=channel,
            approved_reason="a one-line fix" if channel == "planner" else None,
            effort=PlanEffort.SMALL,
        )
        .run(conn)
        .lastrowid,
    )


def commented(conn: sqlite3.Connection, key: str, at: str) -> None:
    """The operator's comment on `key`'s plan at `at`."""
    records.insert(
        records.PlanThread,
        ticket_key=key,
        quote="q",
        prefix="",
        suffix="",
        body="Why this file?",
        created_at=at,
    ).run(conn)
