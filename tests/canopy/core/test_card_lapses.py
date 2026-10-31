"""How often running agents' cards went stale, by role, over a window (DESIGN §41, ROADMAP M65).

Each run's row counts its lapses as tool calls find them; one that ended stale and uncounted lapses once more as it
ended. `canopy cards` counts them per role, over a hand-written journal.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.cli import cards as cards_cli
from canopy.cli.main import main
from canopy.core import card_lapses, cards, db, records, review_runs
from canopy.core.vocab import ReviewRunStatus, RunKind, RunStatus
from tests.canopy.helpers import in_tick, in_zone, plan_run, present, worker_ran

if TYPE_CHECKING:
    import sqlite3

    import pytest
    from syrupy.assertion import SnapshotAssertion

    from tests.conftest import CanopyEnv, Journals

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
CARD = cards.Card.model_validate({"summary": "Fixing the parser.", "now": "running the tests"})


def at(start: datetime, minutes: float) -> str:
    """The time `minutes` after `start`, as the journal writes it."""
    return db.format_time(start + timedelta(minutes=minutes))


def worker(
    conn: sqlite3.Connection,
    kind: RunKind,
    start: datetime,
    *,
    ended: float | None,
    calls: int,
    card: tuple[float, int] | None = None,
    lapses: int = 0,
    stale: bool = False,
) -> None:
    """A worker's or a planner's run that started at `start`, its card recorded `card` minutes in, after so many calls.

    `ended` and `card`'s minutes count from `start`; `calls` is every tool call it ended.
    """
    run_id = worker_ran(
        conn,
        kind,
        db.format_time(start),
        status=RunStatus.DONE if ended is not None else RunStatus.RUNNING,
    )
    records.update(records.Run).set(
        ended_at=at(start, ended) if ended is not None else None,
        tool_calls=calls,
        card_json=CARD.model_dump_json() if card is not None else None,
        card_at=at(start, card[0]) if card is not None else None,
        card_calls=card[1] if card is not None else None,
        card_lapses=lapses,
        card_stale=stale,
    ).where("id = ?", run_id).run(conn)


def journal_of_lapses(conn: sqlite3.Connection, tmp_path: Path, now: datetime) -> None:
    """Two implements, a plan still running, a review and a task, each in the last day; an implement before the week."""
    day = now - timedelta(days=1)
    # Fresh as it ended: updated two minutes before, three calls since.
    worker(conn, RunKind.IMPLEMENT, day, ended=30, calls=13, card=(28, 10))
    # Lapsed twice as it ran, and ended still stale: counted already.
    worker(conn, RunKind.IMPLEMENT, day, ended=30, calls=30, card=(29, 5), lapses=2, stale=True)
    # No card yet after 25 calls, and still running.
    worker(conn, RunKind.PLAN, day, ended=None, calls=25, lapses=1, stale=True)
    # Before a week's window.
    worker(conn, RunKind.IMPLEMENT, now - timedelta(days=9), ended=30, calls=99, lapses=5, stale=True)
    with in_tick(conn) as tick_id:
        review = review_runs.insert_review_run(
            conn,
            tick_id=tick_id,
            pr_url="https://example.test/acme/repo/pull/9",
            sha="a" * 40,
            ticket=None,
            repo=None,
            purpose="request",
            logs_dir=tmp_path,
        )
        task = records.insert(records.Task, text="t", repo="repo", channel="cli", submitted_at=at(day, 0)).run(conn)
        task_run = records.insert(
            records.TaskRun,
            task_id=present(task.lastrowid),
            tick_id=tick_id,
            branch="agent/task/1",
            repo="repo",
            slot_path="/pool/1/repo",
            lease_id="l1",
            lease_holder="canopy:task:1",
            base_branch="main",
            pool="treehouse",
            started_at=at(day, 0),
            ended_at=at(day, 5),
            status=RunStatus.DONE,
            log_path="1.log",
            tool_calls=3,
        )
        task_run.run(conn)
    # Updated a minute in, then quiet for nineteen minutes until it ended: it ended stale, uncounted.
    records.update(records.ReviewRun).set(
        started_at=at(day, 0),
        ended_at=at(day, 20),
        status=ReviewRunStatus.DONE,
        tool_calls=4,
        card_json=CARD.model_dump_json(),
        card_at=at(day, 1),
        card_calls=2,
    ).where("id = ?", review).run(conn)


def test_lapses_are_counted_per_role_over_the_window(tmp_path: Path, journals: Journals) -> None:
    """A run counts by when it started; one that ended stale, and was not counted so, lapses once more as it ended."""
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_lapses(conn, tmp_path, NOW)
    found = card_lapses.counts(conn, NOW, 7)
    assert found.days == 7
    assert [(r.role, r.runs, r.carded, r.lapsed, r.lapses, r.ended, r.ended_stale) for r in found.roles] == [
        ("implement", 2, 2, 1, 2, 2, 1),
        ("plan", 1, 0, 1, 1, 0, 0),
        ("review", 1, 1, 1, 1, 1, 1),
        ("task", 1, 0, 0, 0, 1, 0),
    ]
    implement = card_lapses.counts(conn, NOW, 30).roles[0]
    assert (implement.role, implement.lapses) == ("implement", 7)
    assert card_lapses.counts(conn, NOW - timedelta(days=20), 1).roles == ()


def test_a_run_that_ends_with_its_card_stale_lapses_once_more_unless_counted(
    conn: sqlite3.Connection,
    tmp_path: Path,
) -> None:
    """However it ended: the row holds when, so the end's lapse is read by the measure its tool calls are."""
    fresh, quiet, counted = (plan_run(conn, tmp_path, key) for key in ("PROJ-1", "PROJ-2", "PROJ-3"))
    for run_id in (fresh, quiet, counted):
        cards.record_call(conn, "runs", run_id, CARD)
    records.update(records.Run).set(card_at="2026-01-01T00:00:00.000Z").where("id = ?", quiet).run(conn)
    for _ in range(cards.STALE_CALLS):
        cards.record_call(conn, "runs", counted, None)
    for run_id in (fresh, quiet, counted):
        assert db.finish_run(conn, "runs", run_id, RunStatus.DONE, "{}")
    [implement] = card_lapses.counts(conn, datetime.now(UTC), 1).roles
    assert (implement.runs, implement.lapsed, implement.lapses, implement.ended, implement.ended_stale) == (
        3,
        2,
        2,
        3,
        2,
    )


def test_the_counts_are_printed_as_a_table(tmp_path: Path, journals: Journals, snapshot: SnapshotAssertion) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    journal_of_lapses(conn, tmp_path, NOW)
    with in_zone("UTC"):
        assert "\n".join(cards_cli.render(card_lapses.counts(conn, NOW, 7))) == snapshot
        assert cards_cli.render(card_lapses.counts(conn, NOW - timedelta(days=20), 1)) == [
            "Running cards over 1 day, since 2026-09-18 UTC, by role.",
            "",
            "No run started in the window.",
        ]


def test_canopy_cards_counts_the_last_days(
    canopy_env: CanopyEnv,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--days` narrows it to the last days, and `--json` prints it as data."""
    journal_of_lapses(canopy_env.journal(), tmp_path, datetime.now(UTC))
    assert main(["cards"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[2:4] == [
        "role       runs  carded  lapsed  lapses  ended  ended stale",
        "implement     2       2       1       2      2            1",
    ]
    assert main(["cards", "--days", "30", "--json"]) == 0
    found = json.loads(capsys.readouterr().out)
    assert found["days"] == 30
    assert found["roles"][2] == {
        "role": "review",
        "runs": 1,
        "carded": 1,
        "lapsed": 1,
        "lapses": 1,
        "ended": 1,
        "ended_stale": 1,
    }
    assert found["roles"][0]["lapses"] == 7
    assert main(["cards", "--days", "0"]) == 2
