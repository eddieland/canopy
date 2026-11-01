"""The web UI's reports (DESIGN §11, §42): what each local month cost and got done, the checklist, health, and CI.

Reads only.
"""

import json
from datetime import UTC, datetime, time, timedelta

import pytest

from canopy.core import checklist_answers, db, health, pools, records, runtime_sessions, spend
from canopy.core.checklist_answers import Answer, Checked
from canopy.core.context import Context
from canopy.core.vocab import (
    CheckConclusion,
    ItemAnswer,
    PoolKind,
    ResumeReason,
    ReviewState,
    RunKind,
    RunStatus,
)
from canopy.infra import resources
from canopy.runs import tasks
from canopy.runtime.report import SessionPage, SessionSpend
from canopy.serve import monthly
from canopy.serve.backend import Backend
from canopy.serve.mock import T0, history
from tests.canopy.helpers import (
    answered,
    check_ran,
    context,
    earlier,
    feedback_left,
    in_zone,
    journal_of_answers,
    kicked,
    observed_pr,
    present,
    worker_ran,
)
from tests.canopy.web_helpers import client, signed_in_client
from tests.conftest import CanopyEnv


def test_the_monthly_report_reads_local_months_oldest_first(backend: Backend) -> None:
    c = client(None, backend)
    found = c.get("/api/reports/monthly", params={"months": 3}).json()["months"]
    assert [m["month"] for m in found] == ["2026-08", "2026-09", "2026-10"]
    assert found[0]["since"] == "2026-08-01T00:00:00Z"
    # October holds what the spend's month against its budget does, dry runs included, kind by kind.
    october = found[-1]
    spent = c.get("/api/spend/breakdown", params={"days": 30}).json()["month"]["spent_usd"]
    assert october["cost_usd"] == pytest.approx(spent)
    assert [k["kind"] for k in october["kinds"]] == ["overseer", "workers", "plans", "chores", "reviews", "tasks"]
    assert sum(k["cost_usd"] or 0 for k in october["kinds"]) == pytest.approx(october["cost_usd"])
    assert october["tokens"]["cache_read"] == sum(k["tokens"]["cache_read"] for k in october["kinds"])
    assert 0 < october["tokens"]["cache_hit"] < 1
    assert october["models"]
    # The months before hold the history's worker runs and the tickets they landed, the latest first.
    august = found[0]
    assert [k["kind"] for k in august["kinds"] if k["runs"]] == ["workers"]
    landed = [t for t in history.TICKETS if t.done_at.month == 8 and not t.closed]
    assert [t["key"] for t in august["landed"]] == [t.key for t in reversed(landed)]
    # The mock's reader kept none of GitHub's times, so each figure is its proxy's.
    assert {(t["merged_at"], t["awaiting_review_at"]) for t in august["landed"]} == {(None, None)}
    year = c.get("/api/reports/monthly").json()["months"]
    assert len(year) == monthly.DEFAULT_MONTHS
    # The workspace took canopy up in April: nothing before.
    assert (year[0]["month"], year[0]["runs"], year[0]["cost_usd"]) == ("2025-11", 0, None)
    assert c.get("/api/reports/monthly", params={"months": monthly.MAX_MONTHS + 1}).status_code == 422
    assert c.get("/api/reports/monthly", params={"months": 0}).status_code == 422


def test_each_month_counts_the_sessions_outside_canopy_as_the_budget_does(backend: Backend) -> None:
    c = client(None, backend)
    before = c.get("/api/reports/monthly", params={"months": 1}).json()
    assert before["sessions_read_at"] is None
    assert before["months"][0]["outside"]["sessions"] == 0
    ms = int(T0.timestamp() * 1000)
    mine = SessionSpend("ses_mine", None, "/home/me/notes", ms, ms, 1.5, 100, 20, 5, 300, 40)
    with backend.open() as ctx:
        runtime_sessions.record(
            ctx.conn,
            SessionPage("found", (mine,), cursor=(ms, "ses_mine")),
            now=db.format_time(T0),
        )
    after = c.get("/api/reports/monthly", params={"months": 1}).json()
    [october] = after["months"]
    assert (october["outside"]["sessions"], october["outside"]["cost_usd"]) == (1, 1.5)
    assert october["cost_usd"] - before["months"][0]["cost_usd"] == pytest.approx(1.5)
    assert october["tokens"]["input"] - before["months"][0]["tokens"]["input"] == 100
    assert october["per_landed_usd"] == before["months"][0]["per_landed_usd"]
    assert after["sessions_read_at"] == "2026-10-08T12:00:00Z"
    spent = c.get("/api/spend/breakdown", params={"days": 30}).json()["month"]["spent_usd"]
    assert october["cost_usd"] == pytest.approx(spent)


def test_each_month_carries_the_health_ci_and_reviews_pages_headline_figures(canopy_env: CanopyEnv) -> None:
    """Last month: a failed run and a done one, a red head and a green one, and a first review three hours in."""
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    conn = ctx.conn
    first = datetime.now(UTC).astimezone().date().replace(day=1)
    noon = datetime.combine(first - timedelta(days=15), time(12)).astimezone()

    def at(hours: float) -> str:
        return db.format_time(noon + timedelta(hours=hours))

    pr = "https://github.com/acme/web/pull/7"
    worker_ran(conn, RunKind.IMPLEMENT, at(0), prs={"web": pr}, cost=1.0)
    worker_ran(conn, RunKind.RESUME, at(4), prs={"web": pr}, status=RunStatus.FAILED, cost=0.25)
    check_ran(conn, pr, "h1", "unit", CheckConclusion.FAILURE, at(1))
    check_ran(conn, pr, "h2", "unit", CheckConclusion.SUCCESS, at(5))
    observed_pr(conn, pr, ready_at=at(1), review_requested_at=at(2))
    feedback_left(conn, pr, "dana", at(5), ReviewState.CHANGES_REQUESTED)
    c, _ = signed_in_client(ctx)
    last, this = c.get("/api/reports/monthly", params={"months": 2}).json()["months"]
    assert last["month"] == noon.strftime("%Y-%m")
    assert (last["runs_ended"], last["failed"], last["failed_cost_usd"]) == (2, 1, 0.25)
    assert (last["heads"], last["green_first"]) == (2, 1)
    assert (last["first_reviews"], last["median_first_review_hours"]) == (1, pytest.approx(3.0))
    assert (this["runs_ended"], this["failed"], this["failed_cost_usd"]) == (0, 0, None)
    assert (this["heads"], this["first_reviews"], this["median_first_review_hours"]) == (0, 0, None)


def test_the_health_ci_and_checklist_reports_carry_the_window_before_theirs(ctx: Context) -> None:
    """The last week's headline figures and the week's before, each from a journal with runs in both and before them."""
    conn, now = ctx.conn, datetime.now(UTC)
    start, _ = spend.window(now, spend.DEFAULT_DAYS)

    def at(days: float, hours: float = 0) -> str:
        return db.format_time(start + timedelta(days=days, hours=hours))

    pr = "https://github.com/acme/web/pull/7"
    # Two weeks back, before either window: counted in neither.
    worker_ran(conn, RunKind.IMPLEMENT, at(-10), status=RunStatus.FAILED, cost=9.0)
    # The week before: a failed implement and a fix for CI that turned its red check green; a run given a checklist.
    worker_ran(conn, RunKind.IMPLEMENT, at(-3), prs={"web": pr}, status=RunStatus.FAILED, cost=0.5)
    check_ran(conn, pr, "h1", "unit", CheckConclusion.FAILURE, at(-3, 1))
    worker_ran(conn, RunKind.RESUME, at(-3, 2), prs={"web": pr}, reasons=(ResumeReason.CI,), cost=0.25)
    check_ran(conn, pr, "h2", "unit", CheckConclusion.SUCCESS, at(-3, 3))
    a = ItemAnswer
    answered(conn, at(-2), "api", general_types=a.HELD, newspaper=a.UNANSWERED)
    # This week: one run that ended done, and a red head no fix followed.
    worker_ran(conn, RunKind.RESUME, at(1), prs={"web": pr}, cost=1.0)
    check_ran(conn, pr, "h3", "unit", CheckConclusion.FAILURE, at(1, 1))
    c, _ = signed_in_client(ctx)

    health = c.get("/api/reports/health").json()
    previous = health["previous"]
    assert (previous["since"], previous["until"]) == (_iso(spend.window_before(health["since"], 7)[0]), health["since"])
    # The checklist's run, which `answered` leaves running, ended no way yet.
    assert (previous["runs_ended"], previous["failed"], previous["failed_cost_usd"]) == (2, 1, 0.5)

    found = c.get("/api/reports/ci").json()
    assert (found["heads"], found["green_first"], found["fixes"]) == (1, 0, [])
    assert found["previous"]["until"] == found["since"]
    assert {k: found["previous"][k] for k in ("heads", "green_first", "red", "fixes", "fixes_green")} == {
        "heads": 2,
        "green_first": 1,
        "red": 1,
        "fixes": 1,
        "fixes_green": 1,
    }

    checklist = c.get("/api/reports/checklist").json()
    assert checklist["items"] == []
    assert {k: checklist["previous"][k] for k in ("reminded", "held", "unanswered")} == {
        "reminded": 2,
        "held": 1,
        "unanswered": 1,
    }
    today = c.get("/api/reports/checklist", params={"days": 1}).json()
    assert (today["previous"]["until"], today["previous"]["reminded"]) == (today["since"], 0)


def _iso(at: datetime) -> str:
    return at.isoformat().replace("+00:00", "Z")


def test_the_checklist_counts_each_repositorys_items_as_the_cli_does(ctx: Context) -> None:
    """Per repository and item over the last local days, `repo` narrowing it."""
    journal_of_answers(ctx.conn, datetime.now(UTC))
    c, _ = signed_in_client(ctx)
    found = c.get("/api/reports/checklist").json()
    assert (found["days"], found["repo"]) == (spend.DEFAULT_DAYS, None)
    assert found["since"] < found["until"]
    columns = ("repo", "item", "reminded", "passed", "fixed", "held", "not_applicable", "unanswered")
    assert [tuple(row[k] for k in columns) for row in found["items"]] == [
        ("api", "general-types", 3, 2, 1, 0, 0, 0),
        ("api", "newspaper", 3, 0, 1, 1, 1, 0),
        ("api", "doc-comments", 3, 1, 0, 0, 0, 2),
        ("web", "no-any", 1, 0, 0, 1, 0, 0),
    ]
    # A held item's reason is sent beside the run that gave it, never counted.
    month = c.get("/api/reports/checklist", params={"days": 30}).json()
    assert [r["reason"] for r in month["items"][0]["held_runs"]] == ["Its reason."]
    today = c.get("/api/reports/checklist", params={"days": 1}).json()
    assert [(row["item"], row["reminded"]) for row in today["items"]] == [
        ("general-types", 1),
        ("newspaper", 1),
        ("doc-comments", 1),
        ("no-any", 1),
    ]
    web = c.get("/api/reports/checklist", params={"repo": "web"}).json()
    assert (web["repo"], [row["item"] for row in web["items"]]) == ("web", ["no-any"])
    assert c.get("/api/reports/checklist", params={"repo": "docs"}).json()["items"] == []
    for bad in ({"days": 0}, {"days": spend.MAX_DAYS + 1}, {"repo": "Not a repo"}):
        assert c.get("/api/reports/checklist", params=bad).status_code == 422


def test_the_checklist_names_the_runs_behind_each_held_and_fixed_answer_and_counts_each_week(ctx: Context) -> None:
    """The newest runs first, a worker's or a task's, a held one's reason on a line; every week of the window."""
    now = datetime(2026, 10, 8, 12, tzinfo=UTC)  # a Thursday, in 2026-W41
    a = ItemAnswer
    answered(ctx.conn, earlier(now, 20), "api", general_types=a.HELD)  # before the window
    before = answered(ctx.conn, earlier(now, 8), "api", general_types=a.HELD, newspaper=a.PASSED)  # 2026-W40
    held_with(ctx, before, "general-types", "Typed by hand\n\tin ABC-112.")
    last = answered(ctx.conn, earlier(now, 1), "api", general_types=a.FIXED, newspaper=a.HELD)  # 2026-W41
    held_with(ctx, last, "newspaper", "Long. " * 100)
    task = tasks.submit(ctx.conn, ctx.workspace, "Tidy the export.", repo="repo", project=None, channel="cli")
    task_run = task_ran(ctx, task, earlier(now, 0, hours=2))
    given = (Answer("api", "general-types", a.HELD, "The task's reason."), Answer("api", "newspaper", a.NOT_APPLICABLE))
    checklist_answers.record(ctx.conn, task_run, Checked(answers=given), table="task_runs")
    with in_zone("UTC"):
        c, _ = signed_in_client(ctx, now=now)
        found = c.get("/api/reports/checklist", params={"days": 14}).json()
    general, newspaper = found["items"]
    assert (general["item"], general["held"], general["fixed"]) == ("general-types", 2, 1)
    assert [(r["kind"], r["id"], r["task_id"], r["reason"]) for r in general["held_runs"]] == [
        ("task", task_run, task.id, "The task's reason."),
        ("run", before, None, "Typed by hand in ABC-112."),
    ]
    assert general["held_runs"][0]["started_at"] == "2026-10-08T10:00:00Z"
    assert [(r["kind"], r["id"], r["reason"]) for r in general["fixed_runs"]] == [("run", last, None)]
    [cut] = newspaper["held_runs"]
    assert (cut["id"], len(cut["reason"]), cut["reason"][-3:]) == (last, health.NOTE_LIMIT, "...")
    assert newspaper["fixed_runs"] == []
    # From the Friday the 14 days start on: three weeks, each item's every one, none skipped.
    columns = ("item", "week", "reminded", "passed", "fixed", "held", "not_applicable", "unanswered")
    assert [tuple(w[k] for k in columns) for w in found["weeks"]] == [
        ("general-types", "2026-W39", 0, 0, 0, 0, 0, 0),
        ("general-types", "2026-W40", 1, 0, 0, 1, 0, 0),
        ("general-types", "2026-W41", 2, 0, 1, 1, 0, 0),
        ("newspaper", "2026-W39", 0, 0, 0, 0, 0, 0),
        ("newspaper", "2026-W40", 1, 1, 0, 0, 0, 0),
        ("newspaper", "2026-W41", 2, 0, 0, 1, 1, 0),
    ]
    assert sum(w["held"] for w in found["weeks"]) == sum(i["held"] for i in found["items"])
    narrowed = c.get("/api/reports/checklist", params={"days": 14, "repo": "web"}).json()
    assert (narrowed["items"], narrowed["weeks"]) == ([], [])


def held_with(ctx: Context, run_id: int, item: str, reason: str) -> None:
    """The reason run `run_id` gave for holding `item`, in place of `answered`'s own."""
    query = records.update(records.ChecklistAnswer).set(reason=reason)
    query.where("run_id = ? AND item = ?", run_id, item).run(ctx.conn)


def task_ran(ctx: Context, task: records.Task, started: str) -> int:
    """A run of `task` that started at `started`, as a tick starts one; its id."""
    lease = pools.Lease(
        path=ctx.workspace.root / "slot",
        lease_id=f"lease-{task.id}",
        lease_holder=tasks.holder(task.id),
        leased_at=db.now(),
        base_branch="main",
    )
    run_id = tasks.insert_run(
        ctx.conn,
        task=task,
        tick_id=db.start_tick(ctx.conn, dry_run=False),
        branch_name=tasks.branch(ctx.config.trust.branch_prefix, task.id),
        lease=lease,
        pool=PoolKind.TREEHOUSE,
        logs_dir=ctx.state_dir / "task-runs",
    )
    records.update(records.TaskRun).set(started_at=started).where("id = ?", run_id).run(ctx.conn)
    return present(run_id)


def test_the_mock_counts_its_two_lists(backend: Backend) -> None:
    """`api`'s list in its order, answered by ABC-102's run, then `web`'s, by T0's four ended worker runs in it."""
    found = client(None, backend).get("/api/reports/checklist").json()
    assert [(row["repo"], row["item"], row["reminded"]) for row in found["items"]] == [
        ("api", "general-types", 1),
        ("api", "newspaper-order", 1),
        ("api", "doc-comments", 1),
        ("api", "migration-companion", 1),
        ("web", "no-fixed-sleeps", 4),
        ("web", "query-keys", 4),
        ("web", "no-any", 4),
        ("web", "i18n-strings", 4),
    ]


def test_the_health_report_is_canopy_healths_with_each_days_failures(backend: Backend) -> None:
    """The health report holds what `canopy health` reads, with every day's ended and failed runs beside it."""
    c = client(None, backend)
    found = c.get("/api/reports/health").json()
    assert found["days"] == 7
    assert found["since"] == "2026-10-02T00:00:00Z"
    assert found["until"] == "2026-10-09T00:00:00Z"
    with backend.open() as ctx:
        expected = health.report(ctx.conn, backend.clock(), 7)
    assert [(o["kind"], o["what"], o["status"], o["runs"]) for o in found["outcomes"]] == [
        (o.kind, o.what, o.status, o.runs) for o in expected.outcomes
    ]
    assert [(f["kind"], f["id"]) for f in found["failures"]] == [(f.kind, f.id) for f in expected.failures]
    assert [r["guard"] for r in found["refusals"]] == [r.guard for r in expected.refusals]
    # Every day of the window, and the days add up to the outcomes.
    assert [d["day"] for d in found["per_day"]] == [f"2026-10-0{n}" for n in range(2, 9)]
    ended = sum(sum(d["ended"].values()) for d in found["per_day"])
    failed = sum(sum(d["failed"].values()) for d in found["per_day"])
    assert ended == sum(o.runs for o in expected.outcomes)
    assert failed == sum(o.runs for o in expected.outcomes if o.failed)
    assert failed > 0
    assert [u["kind"] for u in found["unpriced"]] == ["overseer", "workers", "plans", "chores", "reviews", "tasks"]
    assert c.get("/api/reports/health", params={"days": 30}).json()["days"] == 30
    assert c.get("/api/reports/health", params={"days": 0}).status_code == 422
    assert c.get("/api/reports/health", params={"days": spend.MAX_DAYS + 1}).status_code == 422


def test_the_health_report_groups_failures_by_cause_and_refusals_by_ask(canopy_env: CanopyEnv) -> None:
    """Two failures of one harness note are one cause, an agent's summary is `other`, and a guard's ask is counted."""
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    conn, now = ctx.conn, datetime.now(UTC)
    note = "the worker exited 1 without a result line"
    stored = [
        (RunKind.IMPLEMENT, RunStatus.CRASHED, {"harness": note}, earlier(now, 1, 3)),
        (RunKind.RESUME, RunStatus.CRASHED, {"harness": note}, earlier(now, 1, 2)),
        (
            RunKind.IMPLEMENT,
            RunStatus.FAILED,
            {"status": "failed", "summary": "the tests would not pass"},
            earlier(now, 1),
        ),
    ]
    runs = []
    for kind, status, result, started in stored:
        run = worker_ran(conn, kind, started, status=status)
        records.update(records.Run).set(result_json=json.dumps(result)).where("id = ?", run).run(conn)
        runs.append(run)
    # The running guard refused the same resume of PROJ-1 in two ticks.
    ticks = [
        present(records.insert(records.Tick, started_at=earlier(now, 0, h), dry_run=0).run(conn).lastrowid)
        for h in (2, 1)
    ]
    for tick in ticks:
        db.record_decision(conn, tick, "PROJ-1", "refused:running", "run 3 is working PROJ-1", kind=RunKind.RESUME)
    c, _ = signed_in_client(ctx)
    found = c.get("/api/reports/health").json()
    causes = [(k["note"], k["runs"], k["kinds"], k["latest"]["id"], k["latest"]["what"]) for k in found["causes"]]
    assert causes == [
        (note, 2, ["workers"], runs[1], "resume"),
        (None, 1, ["workers"], runs[2], "implement"),
    ]
    assert found["causes"][0]["latest"]["ticket"] == "PROJ-1"
    [refused] = found["refusals"]
    assert (refused["guard"], refused["decisions"], refused["ticks"]) == ("running", 2, 2)
    assert refused["asks"] == [
        {"ticket": "PROJ-1", "chore": None, "pr": None, "kind": "resume", "decisions": 2, "last_tick": ticks[1]},
    ]


def test_the_health_report_holds_each_sorts_durations_against_its_timeout(canopy_env: CanopyEnv) -> None:
    """A worker run near `runtime.worker_timeout_minutes`, and one that timed out past it, held to it."""
    canopy_env.configure(canopy_env.user_file, {"runtime": {"worker_timeout_minutes": 60}})
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    conn, now = ctx.conn, datetime.now(UTC)
    for minutes, status in ((55, RunStatus.DONE), (61, RunStatus.TIMEOUT)):
        started = earlier(now, 1, minutes / 60)
        run = worker_ran(conn, RunKind.IMPLEMENT, started, status=status)
        ended = db.format_time(db.parse_time(started) + timedelta(minutes=minutes))
        records.update(records.Run).set(ended_at=ended).where("id = ?", run).run(conn)
    c, _ = signed_in_client(ctx)
    [implement] = c.get("/api/reports/health").json()["durations"]
    assert (implement["kind"], implement["what"], implement["runs"], implement["timeouts"]) == (
        "workers",
        "implement",
        2,
        1,
    )
    assert implement["limit_minutes"] == 60
    assert implement["longest_minutes"] == pytest.approx(61)
    assert implement["median_minutes"] == pytest.approx(58)
    assert implement["bins"] == {
        "under_quarter": 0,
        "under_half": 0,
        "under_three_quarters": 0,
        "under_limit": 1,
        "over_limit": 1,
    }


def test_a_health_failure_names_what_it_was_about_by_its_kind(backend: Backend) -> None:
    """A failure carries its ticket, PR, chore, or task apart, rather than one subject to parse."""
    c = client(None, backend)
    failures = c.get("/api/reports/health", params={"days": 30}).json()["failures"]
    assert failures
    for f in failures:
        named = {k for k in ("ticket", "pr_url", "chore", "task_id") if f[k] is not None}
        assert (
            named
            == {
                "overseer": set(),
                "workers": {"ticket"},
                "plans": {"ticket"},
                "chores": {"chore"},
                "reviews": {"pr_url"},
                "tasks": {"task_id"},
            }[f["kind"]]
        )


def test_the_ci_report_counts_the_mocks_week_of_check_runs(backend: Backend) -> None:
    """The mock's week: its heads, its checks the worst first, the red ones by day, and its fixes; kicks are off."""
    c = client(None, backend)
    found = c.get("/api/reports/ci").json()
    assert (found["days"], found["since"], found["until"]) == (7, "2026-10-02T00:00:00Z", "2026-10-09T00:00:00Z")
    # PR 88's third head, run 45's push, among them, green first time.
    assert (found["heads"], found["green_first"]) == (11, 5)
    assert [(k["name"], k["red"], k["followed"], k["passed"]) for k in found["checks"]][:3] == [
        ("e2e", 3, 1, 1),
        ("unit", 2, 2, 2),
        ("integration", 1, 0, 0),
    ]
    assert found["series"] == ["e2e", "unit", "build", "integration", None]
    assert [d["day"] for d in found["per_day"]] == [f"2026-10-0{n}" for n in range(2, 9)]
    assert found["per_day"][-1]["red"] == [3, 0, 0, 1, 1]
    # Run 40, a retired `fix-ci`, failed before PR 86's next head; run 43 is a `resume` for `ci` still running.
    assert [(f["run_id"], f["kind"], f["status"]) for f in found["fixes"]] == [
        (43, "resume", "running"),
        (40, "fix-ci", "failed"),
    ]
    assert found["fixes"][1]["checks"] == [
        {"pr_url": "https://github.com/acme/web/pull/86", "name": "e2e", "next": None},
    ]
    assert (found["kicks"], found["kicked_pull_requests"], found["max_flaky_kicks"]) == ([], [], 0)
    assert found["cooldown"] is None
    assert c.get("/api/reports/ci", params={"days": 30}).json()["days"] == 30
    assert c.get("/api/reports/ci", params={"days": 0}).status_code == 422
    assert c.get("/api/reports/ci", params={"days": spend.MAX_DAYS + 1}).status_code == 422


def test_the_ci_report_reads_kicks_fixes_and_the_cooldown_from_the_journal(canopy_env: CanopyEnv) -> None:
    """A journal by hand: a fix, a kick that came back red, its PR against the private limit, and the cooldown."""
    canopy_env.write_private("[trust]\nmax_flaky_kicks = 2\n")
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    conn, now = ctx.conn, datetime.now(UTC)
    pr = "https://github.com/acme/web/pull/7"
    worker_ran(conn, RunKind.IMPLEMENT, earlier(now, 2, 2), prs={"web": pr})
    check_ran(conn, pr, "h1", "e2e", CheckConclusion.FAILURE, earlier(now, 2, 1))
    check_ran(conn, pr, "h1", "unit", CheckConclusion.SUCCESS, earlier(now, 2, 1))
    fix = worker_ran(conn, RunKind.RESUME, earlier(now, 2), prs={"web": pr}, reasons=(ResumeReason.CI,), cost=0.4)
    kicked(conn, fix, "h1", "h2", earlier(now, 1, 23))
    check_ran(conn, pr, "h2", "e2e", CheckConclusion.FAILURE, earlier(now, 1, 22))
    tick = records.insert(records.Tick, started_at=earlier(now, 1), dry_run=0).run(conn).lastrowid
    for action in ("refused:cooldown", "refused:cooldown", "refused:capacity"):
        records.insert(
            records.Decision,
            tick_id=tick,
            created_at=earlier(now, 1),
            ticket_key="PROJ-1",
            action=action,
            rationale="r",
        ).run(conn)
    c, _ = signed_in_client(ctx)
    found = c.get("/api/reports/ci").json()
    [fixed] = found["fixes"]
    assert (fixed["run_id"], fixed["ticket_key"], fixed["cost_usd"]) == (fix, "PROJ-1", 0.4)
    assert fixed["checks"] == [{"pr_url": pr, "name": "e2e", "next": "red"}]
    [kick] = found["kicks"]
    assert (kick["pr_url"], kick["kick"], kick["red_before"], kick["still_red"], kick["checked"]) == (
        pr,
        1,
        ["e2e"],
        ["e2e"],
        True,
    )
    assert found["kicked_pull_requests"] == [
        {"url": pr, "ticket_key": "PROJ-1", "phase": None, "kicks": 1, "most": 1, "still_red": 1},
    ]
    assert found["max_flaky_kicks"] == 2
    asked = {"ticket": "PROJ-1", "chore": None, "pr": None, "kind": None, "decisions": 2, "last_tick": tick}
    assert found["cooldown"] == {"guard": "cooldown", "decisions": 2, "ticks": 1, "last_tick": tick, "asks": [asked]}


def test_the_ci_report_reads_reruns_heads_by_day_and_time_to_green(canopy_env: CanopyEnv) -> None:
    """A rerun that passed on one head, two heads first checked on one day, and a PR green two heads after its red."""
    ctx = context(canopy_env)
    db.migrate(ctx.conn, resources.migrations_dir())
    conn, now = ctx.conn, datetime.now(UTC)
    flaky, fixed = "https://github.com/acme/web/pull/7", "https://github.com/acme/web/pull/8"
    worker_ran(conn, RunKind.IMPLEMENT, earlier(now, 4), prs={"web": flaky})
    worker_ran(conn, RunKind.IMPLEMENT, earlier(now, 4), key="PROJ-2", prs={"web": fixed})
    # PR 7's `e2e` failed and passed on a rerun at the same head an hour later.
    check_ran(conn, flaky, "h1", "e2e", CheckConclusion.FAILURE, earlier(now, 3))
    check_ran(conn, flaky, "h1", "unit", CheckConclusion.SUCCESS, earlier(now, 3))
    check_ran(conn, flaky, "h1", "e2e", CheckConclusion.SUCCESS, earlier(now, 3, -1))
    # PR 8 went red on two heads first checked together, and green on the head after them, a day later.
    check_ran(conn, fixed, "g1", "unit", CheckConclusion.FAILURE, earlier(now, 2))
    check_ran(conn, fixed, "g2", "unit", CheckConclusion.FAILURE, earlier(now, 2))
    fix = worker_ran(
        conn,
        RunKind.RESUME,
        earlier(now, 2, -1),
        key="PROJ-2",
        prs={"web": fixed},
        reasons=(ResumeReason.CI,),
    )
    check_ran(conn, fixed, "g3", "unit", CheckConclusion.SUCCESS, earlier(now, 1))
    c, _ = signed_in_client(ctx)
    found = c.get("/api/reports/ci").json()
    assert [(k["name"], k["runs"], k["red"], k["reruns"], k["reruns_green"]) for k in found["checks"]] == [
        ("unit", 4, 2, 0, 0),
        ("e2e", 2, 1, 1, 1),
    ]
    by_day = {d["day"]: (d["heads"], d["green_first"]) for d in found["per_day"] if d["heads"]}
    assert by_day == {
        spend.local_day(earlier(now, 3)): (1, 0),
        spend.local_day(earlier(now, 2)): (2, 0),
        spend.local_day(earlier(now, 1)): (1, 1),
    }
    assert [(p["url"], p["ticket_key"], p["hours_to_green"]) for p in found["pull_requests"]] == [
        (fixed, "PROJ-2", pytest.approx(24)),
        (flaky, "PROJ-1", pytest.approx(1)),
    ]
    [pr] = [p for p in found["pull_requests"] if p["url"] == fixed]
    assert (db.parse_time(pr["red_at"]), db.parse_time(pr["green_at"])) == (
        db.parse_time(earlier(now, 2)),
        db.parse_time(earlier(now, 1)),
    )
    assert found["median_hours_to_green"] == pytest.approx(12.5)
    assert [(f["run_id"], f["hours_to_green"]) for f in found["fixes"]] == [(fix, pytest.approx(24))]
