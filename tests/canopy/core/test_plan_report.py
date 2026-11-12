"""How the window's plans were approved, and what their tickets needed after (DESIGN §25, #1872): `canopy plans`."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from canopy.cli import plan_report as plan_report_cli
from canopy.cli.main import main
from canopy.core import db, plan_report, plans, records
from canopy.core.plan_metrics import Metrics
from canopy.core.plan_report import Outcome
from canopy.core.vocab import PlanEffort, PlannerApproval, PlanStatus, ResumeReason, RunKind
from tests.canopy.helpers import earlier, in_zone, present, worker_ran

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    import pytest
    from syrupy.assertion import SnapshotAssertion

    from tests.conftest import CanopyEnv

#: When the snapshot's journal is read: its plans are written in the week before.
NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)

# A plan of under a page, one of one to two pages in the plan editor, and one of four to six pages with every kind of
# block that is not prose (`plan_metrics`).
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
    ids = journal_of_plans(conn, state, now)
    by_planner, as_written, sent_back, edited = ids["planner"], ids["as_written"], ids["sent_back"], ids["edited"]
    dropped, waiting = ids["dropped"], ids["waiting"]

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
    # The revised plan was edited, and replaced one sent back; the comment was on the plan it replaced.
    assert [(g.edited, g.commented, g.replanned) for g in found.groups] == [(0, 0, 0), (0, 0, 0), (1, 0, 1)]
    # Each plan is measured from its original; one with no file is not measured, and is left out of the lengths.
    assert rows[as_written].metrics == Metrics(words=121, lines=71, code_blocks=0, tables=0, diagrams=0)
    assert rows[edited].metrics == Metrics(words=4_005, lines=232, code_blocks=1, tables=1, diagrams=1)
    assert (rows[by_planner].metrics is not None, rows[sent_back].metrics) == (True, None)
    assert [(g.median_lines, g.median_words) for g in found.groups] == [(71, 121), (3, 3), (232, 4_005)]
    # The planner's approvals take no time, so the lengths are the operator's alone.
    assert [(n.low, n.high, n.plans, n.median_to_approve, n.as_written) for n in found.lengths] == [
        (50, 100, 1, timedelta(hours=1), 1),
        (200, 300, 1, timedelta(hours=3), 0),
    ]
    assert (found.count(Outcome.REPLACED), found.count(Outcome.WAITING)) == (1, 1)


def test_a_long_plan_goes_in_a_bucket_by_two_pages_up_to_ten(conn: sqlite3.Connection, canopy_env: CanopyEnv) -> None:
    """Past six pages the lengths cut at eight and ten, and ten pages and up is the last."""
    now = datetime.now(UTC)
    for key, steps in (("PROJ-1", 330), ("PROJ-2", 430), ("PROJ-3", 600)):
        steps_text = "# Plan\n\n" + "\n".join(f"- step {i}" for i in range(steps)) + "\n"
        plan(
            conn,
            key,
            earlier(now, 1),
            level=PlannerApproval.OFF,
            channel="web",
            wait=1,
            text=(canopy_env.state_dir, steps_text),
        )

    found = plan_report.report(conn, canopy_env.state_dir, now, 7)

    assert [(n.low, n.high, n.plans) for n in found.lengths] == [(300, 400, 1), (400, 500, 1), (500, None, 1)]


def test_a_week_with_no_plan_has_nothing_to_show(conn: sqlite3.Connection, canopy_env: CanopyEnv) -> None:
    """No plan, no rows: the groups and lengths are empty, not zeros."""
    found = plan_report.report(conn, canopy_env.state_dir, datetime.now(UTC), 7)
    assert (found.plans, found.groups, found.lengths) == ([], [], [])


def test_the_report_is_printed_as_tables(
    conn: sqlite3.Connection,
    canopy_env: CanopyEnv,
    snapshot: SnapshotAssertion,
) -> None:
    """`canopy plans` prints the approvals by level and how, then by length; an empty window says so."""
    journal_of_plans(conn, canopy_env.state_dir, NOW)
    with in_zone("UTC"):
        found = plan_report.report(conn, canopy_env.state_dir, NOW, 7)
        assert "\n".join(plan_report_cli.render(found, PlannerApproval.STRICT)) == snapshot
        empty = plan_report.report(conn, canopy_env.state_dir, NOW - timedelta(days=60), 1)
        assert plan_report_cli.render(empty, PlannerApproval.OFF) == [
            "Plans written over 1 day, since 2026-08-09 UTC: how they were approved, and what their PRs needed after.",
            "",
            "No plan was written in the window.",
        ]


def test_canopy_plans_reads_the_last_thirty_days(
    conn: sqlite3.Connection,
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--days` narrows it, and `--json` prints every plan as data, with where the key is now."""
    ids = journal_of_plans(conn, canopy_env.state_dir, datetime.now(UTC))
    # PROJ-6's plan, written ten days ago and approved as written with no file to measure, is in the 30 days alone.
    assert main(["plans"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[5].split() == ["off", "as", "written", "2", "0", "0", "0", "1h00m", "71", "121", "1", "0", "0", "1"]
    assert out[-1] == "policy.planner_may_approve is off now."
    assert main(["plans", "--days", "7", "--json"]) == 0
    found = json.loads(capsys.readouterr().out)
    assert (found["days"], found["planner_may_approve"], found["page_lines"]) == (7, "off", 50)
    assert found["outcomes"] == {
        "planner": 1,
        "as_written": 1,
        "revised": 1,
        "replaced": 1,
        "dropped": 1,
        "waiting": 1,
    }
    assert found["groups"][2] == {
        "level": None,
        "outcome": "revised",
        "plans": 1,
        "edited": 1,
        "commented": 0,
        "replanned": 1,
        "median_hours_to_approve": 3.0,
        "median_lines": 232,
        "median_words": 4_005,
        "implemented": 0,
        "with_resume": 0,
        "resumes": 0,
        "done": 0,
    }
    assert found["lengths"][0] == {"low": 50, "high": 100, "plans": 1, "median_hours_to_approve": 1.0, "as_written": 1}
    by_planner = next(p for p in found["plans"] if p["plan_id"] == ids["planner"])
    assert {k: by_planner[k] for k in ("ticket_key", "level", "outcome", "hours_to_approve", "resumes", "reasons")} == {
        "ticket_key": "PROJ-1",
        "level": "strict",
        "outcome": "planner",
        "hours_to_approve": 0.0,
        "resumes": 2,
        "reasons": {"ci": 2, "review": 1},
    }
    assert by_planner["metrics"] == {"words": 3, "lines": 3, "code_blocks": 0, "tables": 0, "diagrams": 0}
    assert main(["plans", "--days", "0"]) == 2


def journal_of_plans(conn: sqlite3.Connection, state: Path, now: datetime) -> dict[str, int]:
    """A plan of each way a plan goes, written in the week before `now`, and one before it; their ids by the way.

    PROJ-1's plan its planner approved at strict, then two resumes; PROJ-2's approved as written an hour after, done;
    PROJ-3's sent back after a comment, and its replacement edited and approved; PROJ-4's dropped; PROJ-5's waiting.
    """
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
    return {
        "planner": by_planner,
        "as_written": as_written,
        "sent_back": sent_back,
        "edited": edited,
        "dropped": dropped,
        "waiting": waiting,
    }


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
