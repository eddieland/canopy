"""How long an external event waits for the tick that acts on it, over a journal written by hand (ROADMAP M39).

A comment, a review, a review comment, and a check run each wait for the first live tick that decided about their
ticket after canopy observed them, the harness's decision as much as the overseer's; a cursor the harness moved and a
refusal decide nothing; an item no tick acted on is counted apart; and the window is by the item's source time.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from canopy.cli import latency as latency_cli
from canopy.cli.main import main
from canopy.core import db, item_numbers, records
from canopy.core.vocab import CheckConclusion, Decider, NumberedItem, ReviewItem
from canopy.loop import harness, latency
from tests.canopy.helpers import in_zone

if TYPE_CHECKING:
    import sqlite3

    import pytest

    from tests.conftest import CanopyEnv

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
PR = "https://github.com/acme/api/pull/7"


def at(moment: datetime, minutes: float) -> str:
    """The journal's time `minutes` after `moment`."""
    return db.format_time(moment + timedelta(minutes=minutes))


def ticket(conn: sqlite3.Connection, key: str, pr: str | None = None) -> None:
    """A ticket `key`, with a unit whose PR is `pr`, if any."""
    db.touch_ticket(conn, key, "/ws")
    if pr is not None:
        records.insert(records.TicketUnit, ticket_key=key, repo="api", pr_url=pr).run(conn)


def commented(conn: sqlite3.Connection, key: str, ident: str, source_at: str, observed_at: str, **kw: str) -> None:
    """A comment on `key` at `source_at`, first observed at `observed_at`; `source="worker"` for a worker's own."""
    number = item_numbers.take(conn, NumberedItem.COMMENT, key, ident, at=observed_at)
    records.insert(
        records.ObservedComment,
        ticket=key,
        id=ident,
        author="alice",
        commented_at=source_at,
        body="Please rename it.",
        truncated=0,
        source=kw.get("source", "tracker"),
        observed_at=observed_at,
        number=number,
    ).run(conn)


def reviewed(conn: sqlite3.Connection, item: ReviewItem, ident: int, source_at: str, observed_at: str) -> None:
    """A review item of `PR` at `source_at`, first observed at `observed_at` and last read a day later."""
    kind = NumberedItem.REVIEW if item is ReviewItem.REVIEW else NumberedItem.REVIEW_COMMENT
    records.insert(
        records.ObservedReview,
        pr_url=PR,
        item=item,
        id=ident,
        bot=0,
        created_at=source_at,
        body="Looks off.",
        thread_id=None if item is ReviewItem.REVIEW else "PRRT_1",
        # A later read replaces the row's `observed_at`: its number keeps the first.
        observed_at=at(db.parse_time(observed_at), 24 * 60),
        number=item_numbers.take(conn, kind, PR, ident, at=observed_at),
    ).run(conn)


def check_completed(conn: sqlite3.Connection, run_id: int, observed_at: str) -> None:
    """A check run of `PR` a source first observed completed, failing, at `observed_at`."""
    records.insert(
        records.ObservedCheckRun,
        pr_url=PR,
        run_id=run_id,
        name="test",
        head_sha="a" * 40,
        conclusion=CheckConclusion.FAILURE,
        observed_at=observed_at,
        number=item_numbers.take(conn, NumberedItem.CHECK_RUN, PR, run_id, at=observed_at),
    ).run(conn)


def ticked(
    conn: sqlite3.Connection,
    started_at: str,
    decided: dict[str, str],
    *,
    woken_by: str | None = "timer",
    decider: Decider = Decider.OVERSEER,
    dry_run: bool = False,
) -> int:
    """A tick that started at `started_at` and, a few seconds later, recorded each action of `decided` by ticket."""
    tick_id = records.insert(records.Tick, started_at=started_at, dry_run=int(dry_run), woken_by=woken_by).run(conn)
    assert tick_id.lastrowid is not None
    for key, action in decided.items():
        records.insert(
            records.Decision,
            tick_id=tick_id.lastrowid,
            ticket_key=key,
            action=action,
            rationale="r",
            created_at=at(db.parse_time(started_at), 0.1),
            decider=decider,
        ).run(conn)
    return tick_id.lastrowid


def rows(found: latency.Latencies) -> dict[str, tuple[object, ...]]:
    """Each row of `found` by kind: items, acted, by poll, not acted, median, p90, and from observed."""
    return {
        k.kind: (k.items, k.acted, k.by_poll, k.not_acted, k.median, k.p90, k.observed_median)
        for k in (*found.kinds, found.total)
    }


def test_each_kind_waits_for_the_first_live_tick_after_it_was_observed(conn: sqlite3.Connection) -> None:
    """A tick before canopy observed the item, or a dry run, did not act on it; the poll-woken tick after did."""
    ticket(conn, "PROJ-1", PR)
    base = NOW - timedelta(hours=2)
    ticked(conn, at(base, -1), {"PROJ-1": "wait"})
    commented(conn, "PROJ-1", "c1", at(base, 0), at(base, 1))
    reviewed(conn, ReviewItem.REVIEW, 11, at(base, 0.5), at(base, 1))
    reviewed(conn, ReviewItem.COMMENT, 12, at(base, 0.5), at(base, 1))
    check_completed(conn, 21, at(base, 1.5))
    ticked(conn, at(base, 1.6), {"PROJ-1": "dispatch:resume"}, dry_run=True)
    ticked(conn, at(base, 2), {"PROJ-1": "dispatch:resume"}, woken_by=latency.POLL)
    found = latency.measure(conn, NOW, 7)
    assert found.days == 7
    assert rows(found) == {
        "comment": (1, 1, 1, 0, 120.0, 120.0, 60.0),
        "review": (1, 1, 1, 0, 90.0, 90.0, 60.0),
        "review_comment": (1, 1, 1, 0, 90.0, 90.0, 60.0),
        # No source time: only canopy's own part of its wait.
        "check_run": (1, 1, 1, 0, None, None, 30.0),
        "all": (4, 4, 4, 0, 90.0, 120.0, 60.0),
    }


def test_the_harness_deciding_acts_and_a_cursor_or_a_refusal_does_not(conn: sqlite3.Connection) -> None:
    """A cursor moved and a refusal decide nothing about the ticket; the harness's own `wait` does."""
    ticket(conn, "PROJ-2")
    base = NOW - timedelta(hours=3)
    commented(conn, "PROJ-2", "c2", at(base, 0), at(base, 2))
    ticked(conn, at(base, 3), {"PROJ-2": harness.CURSOR_ACTION}, decider=Decider.HARNESS)
    ticked(conn, at(base, 4), {"PROJ-2": "refused:decided"})
    assert rows(latency.measure(conn, NOW, 7))["comment"] == (1, 0, 0, 1, None, None, None)
    ticked(conn, at(base, 10), {"PROJ-2": "wait"}, decider=Decider.HARNESS)
    assert rows(latency.measure(conn, NOW, 7))["comment"] == (1, 1, 0, 0, 600.0, 600.0, 480.0)


def test_items_no_tick_acted_on_are_counted_apart_and_canopys_own_are_not_counted(conn: sqlite3.Connection) -> None:
    """A tick deciding about another ticket acts on none of this one's; a worker's comment is no external event."""
    ticket(conn, "PROJ-3")
    ticket(conn, "PROJ-4")
    base = NOW - timedelta(hours=1)
    commented(conn, "PROJ-3", "c3", at(base, 0), at(base, 1))
    commented(conn, "PROJ-3", "c4", at(base, 0), at(base, 1), source="worker")
    # A review of a PR no ticket's unit names is no ticket's event.
    reviewed(conn, ReviewItem.REVIEW, 31, at(base, 0), at(base, 1))
    ticked(conn, at(base, 2), {"PROJ-4": "dispatch:implement"})
    found = rows(latency.measure(conn, NOW, 7))
    assert found["comment"] == (1, 0, 0, 1, None, None, None)
    assert found["review"] == (0, 0, 0, 0, None, None, None)
    assert found["all"] == (1, 0, 0, 1, None, None, None)


def test_an_item_a_ticks_own_read_observed_is_that_ticks(conn: sqlite3.Connection) -> None:
    """A tick that observed the item in its own read and then decided acted on it from when it observed it."""
    ticket(conn, "PROJ-5")
    base = NOW - timedelta(hours=1)
    commented(conn, "PROJ-5", "c5", at(base, -1), at(base, 0.05))
    ticked(conn, at(base, 0), {"PROJ-5": "wait"})
    assert rows(latency.measure(conn, NOW, 7))["comment"] == (1, 1, 0, 0, 63.0, 63.0, 0.0)


def test_the_window_is_by_the_items_source_time(conn: sqlite3.Connection) -> None:
    """An item from three days ago is in a week's window and not in a day's; a check run's is by its observation."""
    ticket(conn, "PROJ-6", PR)
    old = NOW - timedelta(days=3)
    commented(conn, "PROJ-6", "c6", at(old, 0), at(old, 1))
    check_completed(conn, 61, at(old, 1))
    commented(conn, "PROJ-6", "c7", at(NOW, -30), at(NOW, -29))
    ticked(conn, at(old, 2), {"PROJ-6": "wait"})
    ticked(conn, at(NOW, -28), {"PROJ-6": "wait"})
    with in_zone("UTC"):
        week, day = rows(latency.measure(conn, NOW, 7)), rows(latency.measure(conn, NOW, 1))
    assert (week["comment"][0], week["check_run"][0]) == (2, 1)
    assert (day["comment"][0], day["check_run"][0]) == (1, 0)


def test_the_report_is_printed_as_a_table(conn: sqlite3.Connection) -> None:
    """A row per kind and the total, each duration to the second, `-` where none is known."""
    ticket(conn, "PROJ-1", PR)
    base = NOW - timedelta(hours=2)
    commented(conn, "PROJ-1", "c1", at(base, 0), at(base, 1))
    commented(conn, "PROJ-1", "c2", at(base, 0), at(base, 1))
    check_completed(conn, 21, at(base, 1.5))
    ticked(conn, at(base, 2.25), {"PROJ-1": "wait"}, woken_by=latency.POLL)
    commented(conn, "PROJ-1", "c3", at(base, 60), at(base, 61))
    with in_zone("UTC"):
        lines = latency_cli.render(latency.measure(conn, NOW, 7))
    assert lines == [
        "External events over 7 days, since 2026-10-02 UTC: how long each waited for a tick to act.",
        "",
        "kind            items  acted  by poll  not acted  median    p90  from observed",
        "comment             3      2        2          1   2m15s  2m15s          1m15s",
        "review              0      0        0          0       -      -              -",
        "review comment      0      0        0          0       -      -              -",
        "check run           1      1        1          0       -      -            45s",
        "all                 4      3        3          1   2m15s  2m15s          1m15s",
        "",
        "Latency runs from the item's time at its source; from observed, from when canopy first observed it.",
        "A check run has no source time: its latency is unknown, and the total's reads the other kinds.",
    ]


def test_canopy_latency_prints_the_last_days(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    """`--json` prints it as data, in seconds; `--days` takes at least one day."""
    conn = canopy_env.journal()
    now = datetime.now(UTC)
    ticket(conn, "PROJ-1")
    commented(conn, "PROJ-1", "c1", at(now, -10), at(now, -9))
    ticked(conn, at(now, -8), {"PROJ-1": "wait"}, woken_by=latency.POLL)
    assert main(["latency"]) == 0
    assert capsys.readouterr().out.splitlines()[3].split() == ["comment", "1", "1", "1", "0", "2m00s", "2m00s", "1m00s"]
    assert main(["latency", "--days", "2", "--json"]) == 0
    found = json.loads(capsys.readouterr().out)
    assert found["days"] == 2
    assert found["kinds"][0] == {
        "kind": "comment",
        "items": 1,
        "acted": 1,
        "by_poll": 1,
        "not_acted": 0,
        "median_s": 120.0,
        "p90_s": 120.0,
        "observed_median_s": 60.0,
    }
    assert [k["kind"] for k in found["kinds"]] == ["comment", "review", "review_comment", "check_run"]
    assert found["total"]["items"] == 1
    assert main(["latency", "--days", "0"]) == 2
