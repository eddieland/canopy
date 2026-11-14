"""`canopy waiting` and its tool: what waits on the operator, and what happened since a time (DESIGN §20)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import db
from canopy.core.vocab import ReviewState
from canopy.loop import waiting as waiting_report
from tests.canopy.helpers import feedback_left, in_tick, observed_pr

if TYPE_CHECKING:
    import sqlite3

    from tests.conftest import CanopyEnv

PR = "https://github.com/acme/web/pull/7"
MERGED = "https://github.com/acme/web/pull/8"


def ago(hours: float) -> str:
    """The journal's time `hours` before now."""
    return db.format_time(datetime.now(UTC) - timedelta(hours=hours))


def waiting(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    """What `canopy waiting` prints, read back."""
    assert main(["waiting", *args]) == 0
    found: dict[str, Any] = json.loads(capsys.readouterr().out)
    return found


def test_it_lists_what_waits_and_marks_what_is_new(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = str(canopy_env.root)
    db.set_unit(conn, "PROJ-1", root, "repo", pr_url=PR)
    db.set_unit(conn, "PROJ-2", root, "repo", pr_url=MERGED)
    observed_pr(conn, PR, review_requested_at=ago(30))
    observed_pr(conn, MERGED, merged_at=ago(2))
    # Ana asked for changes before the last briefing; Bo approved after it, then Ana commented on a line.
    feedback_left(conn, PR, "ana", ago(26), ReviewState.CHANGES_REQUESTED, body="Rename the flag.")
    feedback_left(conn, PR, "bo", ago(3), ReviewState.APPROVED, body="Ship it.")
    feedback_left(conn, PR, "ana", ago(2), body="Needs a test.\n\n  Here.")
    feedback_left(conn, PR, "ana", ago(1), ReviewState.COMMENTED, body="One more \x1b[31mthing.")
    # The PR's author, a bot, and a merged PR's reviewer are no reviewer the operator waits on.
    feedback_left(conn, PR, "op", ago(1), ReviewState.COMMENTED)
    feedback_left(conn, PR, "ci-bot", ago(1), ReviewState.CHANGES_REQUESTED, bot=True)
    feedback_left(conn, MERGED, "cy", ago(2), ReviewState.APPROVED)
    with in_tick(conn, ends_ok=True) as tick_id:
        db.record_decision(conn, tick_id, "PROJ-1", "attention:needs_reviewer", "PR 7 has waited a day")

    found = waiting(capsys, "--since", ago(24))

    [item] = found["attention"]
    assert {k: item[k] for k in ("ticket", "reason", "detail", "new")} == {
        "ticket": "PROJ-1",
        "reason": "needs_reviewer",
        "detail": "PR 7 has waited a day",
        "new": True,
    }
    [pr] = found["prs"]
    assert (pr["ticket"], pr["pr"], pr["author"]) == ("PROJ-1", PR, "op")
    # Ana's comment-only review leaves her where her request for changes put her.
    assert [(r["author"], r["state"]) for r in pr["reviews"]] == [("ana", "changes_requested"), ("bo", "approved")]
    assert [(f["author"], f["item"], f["new"]) for f in pr["feedback"] if not f["pr_author"] and not f["bot"]] == [
        ("ana", "review", False),
        ("bo", "review", True),
        ("ana", "comment", True),
        ("ana", "review", True),
    ]
    assert [f["excerpt"] for f in pr["feedback"] if f["author"] == "ana"] == [
        "Rename the flag.",
        "Needs a test. Here.",
        "One more [31mthing.",
    ]
    assert pr["more_feedback"] == 0
    assert set(found["happened"]) >= {"ticks", "runs_started", "runs_ended", "done", "blocked", "spend"}
    assert "until" not in found["happened"]


def test_a_done_ticket_has_no_prs_listed(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db.set_unit(conn, "PROJ-1", str(canopy_env.root), "repo", pr_url=PR)
    observed_pr(conn, PR)
    conn.execute("UPDATE tickets SET done = 1 WHERE key = 'PROJ-1'")
    conn.commit()
    assert waiting(capsys)["prs"] == []


def test_it_counts_from_a_day_back_by_default(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    del canopy_env
    since = db.parse_time(waiting(capsys)["since"])
    assert abs(datetime.now(UTC) - timedelta(days=1) - since) < timedelta(minutes=1)


def test_a_reviewer_stands_where_their_last_approval_or_request_put_them(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db.set_unit(conn, "PROJ-1", str(canopy_env.root), "repo", pr_url=PR)
    observed_pr(conn, PR)
    # Cy only commented, Di's approval was dismissed, and Ed's was dismissed and then given again.
    feedback_left(conn, PR, "cy", ago(5), ReviewState.COMMENTED)
    feedback_left(conn, PR, "di", ago(5), ReviewState.APPROVED)
    feedback_left(conn, PR, "di", ago(4), ReviewState.DISMISSED)
    feedback_left(conn, PR, "ed", ago(5), ReviewState.APPROVED)
    feedback_left(conn, PR, "ed", ago(4), ReviewState.DISMISSED)
    feedback_left(conn, PR, "ed", ago(3), ReviewState.APPROVED)
    [pr] = waiting(capsys)["prs"]
    assert [(r["author"], r["state"]) for r in pr["reviews"]] == [("ed", "approved")]


def test_a_new_answer_on_an_old_thread_is_marked_and_the_oldest_are_counted(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db.set_unit(conn, "PROJ-1", str(canopy_env.root), "repo", pr_url=PR)
    observed_pr(conn, PR)
    feedback_left(conn, PR, "ana", ago(30), thread="t", body="Why a flag?")
    for n, hours in enumerate((29, 28, 27, 2)):
        feedback_left(conn, PR, "op" if n % 2 == 0 else "ana", ago(hours), thread="t", body=f"answer {n}")
    with mock.patch.object(waiting_report, "MAX_REPLIES", 3):
        [pr] = waiting(capsys, "--since", ago(24))["prs"]
    [thread] = pr["feedback"]
    assert (thread["excerpt"], thread["new"], thread["new_replies"], thread["more_replies"]) == (
        "Why a flag?",
        False,
        1,
        1,
    )
    assert [(r["excerpt"], r["new"]) for r in thread["replies"]] == [
        ("answer 1", False),
        ("answer 2", False),
        ("answer 3", True),
    ]


@pytest.mark.parametrize(
    ("since", "refusal"),
    [
        ("yesterday", "must be ISO 8601"),
        ("2026-11-13T09:00:00", "must name its time zone"),
        ("2020-01-01T00:00:00Z", "must be within 366 days"),
        ("2999-01-01T00:00:00Z", "must not be in the future"),
    ],
)
def test_a_time_it_cannot_read_is_refused(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
    since: str,
    refusal: str,
) -> None:
    del canopy_env
    assert main(["waiting", "--since", since]) != 0
    assert refusal in capsys.readouterr().err
