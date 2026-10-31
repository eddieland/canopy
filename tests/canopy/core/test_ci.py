"""What CI did on the PRs canopy observed (DESIGN §11): the CI page's report, over a journal of check runs by hand."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from canopy.core import ci
from canopy.core.vocab import CheckConclusion, ResumeReason, RunKind, RunStatus
from tests.canopy.helpers import check_ran, earlier, in_zone, kicked, worker_ran
from tests.conftest import Journals

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
PR_1 = "https://github.com/acme/web/pull/1"
PR_2 = "https://github.com/acme/web/pull/2"


S, F, E, T, X, C, K, N = (
    CheckConclusion.SUCCESS,
    CheckConclusion.FAILURE,
    CheckConclusion.ERROR,
    CheckConclusion.TIMED_OUT,
    CheckConclusion.STARTUP_FAILURE,
    CheckConclusion.CANCELLED,
    CheckConclusion.SKIPPED,
    CheckConclusion.NEUTRAL,
)


def journal_of_checks(conn: sqlite3.Connection) -> None:
    """Two PRs' check runs over the week, and one before it."""
    # Before the window: its head is not the window's, though the run after it on a new head is.
    check_ran(conn, PR_1, "a0", "unit", F, earlier(NOW, 9))
    # PR 1's first head in the window: `unit` red, then rerun green at the same head; `lint` green.
    check_ran(conn, PR_1, "a1", "unit", F, earlier(NOW, 3))
    check_ran(conn, PR_1, "a1", "lint", S, earlier(NOW, 3))
    check_ran(conn, PR_1, "a1", "unit", S, earlier(NOW, 3, -1))
    # Its next head: green first time, a skipped preview counting as neither.
    check_ran(conn, PR_1, "a2", "unit", S, earlier(NOW, 2))
    check_ran(conn, PR_1, "a2", "lint", S, earlier(NOW, 2))
    check_ran(conn, PR_1, "a2", "preview", K, earlier(NOW, 2))
    # PR 2: errors and a timeout, and a head of nothing but neither.
    check_ran(conn, PR_2, "b1", "e2e", E, earlier(NOW, 1))
    check_ran(conn, PR_2, "b1", "build", T, earlier(NOW, 1))
    check_ran(conn, PR_2, "b1", "deploy", X, earlier(NOW, 1))
    check_ran(conn, PR_2, "b1", "docs", F, earlier(NOW, 1))
    check_ran(conn, PR_2, "b1", "lint", C, earlier(NOW, 1))
    check_ran(conn, PR_2, "b2", "e2e", F, earlier(NOW, 0, 2))
    check_ran(conn, PR_2, "b2", "build", S, earlier(NOW, 0, 2))
    check_ran(conn, PR_2, "b3", "lint", N, earlier(NOW, 0, 1))


def test_checks_are_the_worst_first_with_how_often_a_new_head_fixed_them(tmp_path: Path, journals: Journals) -> None:
    """Each check counts its red and green runs, and how often the next run on a new head of its PR passed."""
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_checks(conn)
    found = ci.report(conn, NOW, 7)
    assert [(c.name, c.runs, c.red, c.green, c.followed, c.passed) for c in found.checks] == [
        # The most red runs first, then the highest share of red among red and green.
        ("e2e", 2, 2, 0, 1, 0),
        ("deploy", 1, 1, 0, 0, 0),
        ("docs", 1, 1, 0, 0, 0),
        ("build", 2, 1, 1, 1, 1),
        # A rerun at the same head is no new head: `unit`'s red run is followed by a2's green.
        ("unit", 3, 1, 2, 1, 1),
        # Cancelled, skipped, and neutral runs count as neither red nor green.
        ("lint", 4, 0, 2, 0, 0),
        ("preview", 1, 0, 0, 0, 0),
    ]


def test_a_head_is_green_first_time_when_no_checks_first_run_was_red(tmp_path: Path, journals: Journals) -> None:
    """A head counts by the first run of each check on it, and a head of nothing but neither counts not at all."""
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_checks(conn)
    found = ci.report(conn, NOW, 7)
    # a1 red first (its rerun passed), a2 green, b1 and b2 red, b3 neither; a0 before the window.
    assert (found.heads, found.green_first) == (4, 1)


def test_red_runs_by_day_name_the_top_checks_and_sum_the_rest(tmp_path: Path, journals: Journals) -> None:
    """The chart's series are the most often red checks, then the rest as one; each day counts its red runs."""
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_checks(conn)
    found = ci.report(conn, NOW, 7)
    assert found.series == ["e2e", "build", "deploy", "docs", None]
    assert [(d.day, list(d.red)) for d in found.per_day] == [
        ("2026-10-02", [0, 0, 0, 0, 0]),
        ("2026-10-03", [0, 0, 0, 0, 0]),
        ("2026-10-04", [0, 0, 0, 0, 0]),
        ("2026-10-05", [0, 0, 0, 0, 1]),
        ("2026-10-06", [0, 0, 0, 0, 0]),
        ("2026-10-07", [1, 1, 1, 1, 0]),
        ("2026-10-08", [1, 0, 0, 0, 0]),
    ]


def test_a_check_is_red_on_the_local_day_it_was_observed(tmp_path: Path, journals: Journals) -> None:
    """A run observed at 02:00 UTC is the evening before in New York, and counts on that day."""
    conn = journals.open(tmp_path / "canopy.db")
    check_ran(conn, PR_1, "a1", "unit", F, "2026-10-08T02:00:00.000Z")
    with in_zone("America/New_York"):
        found = ci.report(conn, NOW, 2)
    assert [(d.day, list(d.red)) for d in found.per_day] == [("2026-10-07", [1]), ("2026-10-08", [0])]


def test_a_fix_says_whether_each_check_it_found_red_passed_on_the_next_head(tmp_path: Path, journals: Journals) -> None:
    """A `resume` for `ci` and a retired `fix-ci` are fixes; each red check is judged by its run on the next head."""
    conn = journals.open(tmp_path / "canopy.db")
    worker_ran(conn, RunKind.IMPLEMENT, earlier(NOW, 3, 1), prs={"web": PR_1})
    check_ran(conn, PR_1, "a1", "unit", F, earlier(NOW, 3))
    check_ran(conn, PR_1, "a1", "lint", F, earlier(NOW, 3))
    check_ran(conn, PR_1, "a1", "e2e", F, earlier(NOW, 3))
    check_ran(conn, PR_1, "a1", "build", S, earlier(NOW, 3))
    # The rerun the operator asked for: `e2e` is red again at the head the fix starts on.
    check_ran(conn, PR_1, "a1", "lint", S, earlier(NOW, 3, -1))
    fix = worker_ran(
        conn,
        RunKind.RESUME,
        earlier(NOW, 2, 1),
        prs={"web": PR_1},
        reasons=(ResumeReason.CI, ResumeReason.REVIEW),
        cost=0.5,
    )
    check_ran(conn, PR_1, "a2", "unit", S, earlier(NOW, 2))
    check_ran(conn, PR_1, "a2", "e2e", F, earlier(NOW, 2))
    # Retired, failed before it named a PR: its ticket's PR is the one it was sent for. No new head followed it.
    old = worker_ran(conn, RunKind.FIX_CI, earlier(NOW, 1), status=RunStatus.FAILED, cost=0.25)
    # A `resume` for review alone fixes no CI, and one before the window is outside it.
    worker_ran(conn, RunKind.RESUME, earlier(NOW, 1, 1), prs={"web": PR_1}, reasons=(ResumeReason.REVIEW,))
    worker_ran(conn, RunKind.RESUME, earlier(NOW, 9), prs={"web": PR_1}, reasons=(ResumeReason.CI,))
    found = ci.report(conn, NOW, 7)
    assert [(f.run_id, f.kind, f.status, f.cost_usd) for f in found.fixes] == [
        (old, RunKind.FIX_CI, RunStatus.FAILED, 0.25),
        (fix, RunKind.RESUME, RunStatus.DONE, 0.5),
    ]
    assert [(c.pr_url, c.name, c.next) for c in found.fixes[1].checks] == [
        (PR_1, "unit", "green"),
        (PR_1, "e2e", "red"),
    ]
    assert [(c.name, c.next) for c in found.fixes[0].checks] == [("e2e", None)]


def test_a_kick_says_whether_its_check_came_back_red(tmp_path: Path, journals: Journals) -> None:
    """Each kick names its PR, its place in its head's chain, and the checks red before it that were red again."""
    conn = journals.open(tmp_path / "canopy.db")
    run = worker_ran(conn, RunKind.RESUME, earlier(NOW, 9), prs={"web": PR_1, "api": PR_2}, reasons=(ResumeReason.CI,))
    # Before the window, but the first of the chain the window's kicks continue.
    check_ran(conn, PR_1, "h0", "e2e", F, earlier(NOW, 9))
    kicked(conn, run, "h0", "h1", earlier(NOW, 9))
    check_ran(conn, PR_1, "h1", "e2e", F, earlier(NOW, 3))
    check_ran(conn, PR_1, "h1", "unit", S, earlier(NOW, 3))
    again = worker_ran(conn, RunKind.RESUME, earlier(NOW, 3, -1), prs={"web": PR_1}, reasons=(ResumeReason.CI,))
    kicked(conn, again, "h1", "h2", earlier(NOW, 3, -2))
    check_ran(conn, PR_1, "h2", "e2e", T, earlier(NOW, 3, -3))
    # A worker's push starts a new head of work, its chain empty; this kick has no run of its check yet.
    check_ran(conn, PR_1, "w1", "unit", F, earlier(NOW, 1))
    last = worker_ran(conn, RunKind.RESUME, earlier(NOW, 1, -1), prs={"web": PR_1}, reasons=(ResumeReason.CI,))
    kicked(conn, last, "w1", "w2", earlier(NOW, 1, -2))
    found = ci.report(conn, NOW, 7)
    assert [(k.run_id, k.pr_url, k.kick, list(k.red_before), list(k.still_red), k.checked) for k in found.kicks] == [
        (last, PR_1, 1, ["unit"], [], False),
        (again, PR_1, 2, ["e2e"], ["e2e"], True),
    ]
    assert [(p.url, p.ticket, p.kicks, p.most, p.still_red) for p in found.kicked_prs] == [(PR_1, "PROJ-1", 2, 2, 1)]


def test_an_empty_window_lists_each_day_at_nothing(tmp_path: Path, journals: Journals) -> None:
    """A window with no check run has no heads, checks, or series, and each of its days."""
    conn = journals.open(tmp_path / "canopy.db")
    found = ci.report(conn, NOW, 3)
    assert (found.heads, found.green_first, list(found.checks), list(found.series)) == (0, 0, [], [])
    assert [(d.day, list(d.red)) for d in found.per_day] == [
        ("2026-10-06", []),
        ("2026-10-07", []),
        ("2026-10-08", []),
    ]
    assert (list(found.fixes), list(found.kicks), list(found.kicked_prs)) == ([], [], [])
