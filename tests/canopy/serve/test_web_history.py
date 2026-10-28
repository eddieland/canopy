"""The web UI on a journal with a long history (DESIGN §22).

What a page or the event stream reads costs what the page shows, not what the journal has recorded; and the reads that
weigh only candidates find what weighing every row did.
"""

import dataclasses
import json
import random
import sqlite3
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from unittest import mock

import pytest

from canopy.core import chore_result, db
from canopy.core.context import Context
from canopy.loop import attention, web
from canopy.serve import chore_views, live, pr_list, pull_requests, reviews, spend_views, tick_views, views
from canopy.serve import mock as serve_mock
from canopy.serve.backend import Backend
from canopy.serve.mock import history as serve_history
from tests.conftest import Journals

# The mock's own PR, which the old history leaves alone.
PR = "https://github.com/acme/web/pull/88"
# How old the oldest of the mock's own rows is, in minutes, its months before T0 among them (mock/history.py); the
# history this adds is older than that.
HISTORY_STARTS = 200 * 24 * 60
# SQLite calls the progress handler once per this many virtual machine instructions: a step.
STEP = 10
# How much more work a read may do over five times the history: a deeper index, never another pass over it.
GROWTH = 1.1
SLACK = 5

# Each read a page or the event stream makes, but the all-time spend: that one sums every cost ever recorded, from an
# index alone (migration 0022), and grows with the journal by design.
READS: dict[str, Callable[[Backend, Context], object]] = {
    "attention": views.attention,
    "runs": lambda _b, ctx: views.runs(ctx),
    "tickets": lambda _b, ctx: views.tickets(ctx),
    "chores": chore_views.chores,
    "spend in the last 30 days": lambda b, ctx: spend_views._spent(ctx, b.clock(), views.SPEND_MONTH_HOURS),  # noqa: SLF001
    "latest tick": lambda _b, ctx: tick_views.last_tick(ctx),
    "ticks": lambda _b, ctx: tick_views.ticks(ctx),
    "a ticket": lambda b, ctx: views.ticket(b, ctx, "ABC-102"),
    "a chore": lambda b, ctx: chore_views.chore(b, ctx, serve_mock.CHORE),
    "reviews": lambda _b, ctx: reviews.reviews(ctx),
    "pull requests": lambda _b, ctx: pull_requests.pull_requests(ctx),
    "a pull request": lambda b, ctx: pull_requests.pull_request(b, ctx, PR),
}


@pytest.fixture
def backend(tmp_path: Path) -> Backend:
    """The mock's journal, served as `canopy loop` serves its own: the loop's attention list and limits."""
    return dataclasses.replace(
        serve_mock.seed(tmp_path / "mock"),
        attention=attention.listed,
        limits=web.limits,
        review_limit=web.review_limit,
    )


def test_no_read_grows_with_the_history_behind_it(backend: Backend) -> None:
    """Five times the history, every row older than any the pages show, and each read does the same work.

    Before migration 0022 and the candidates `db.recent_tickets` and `pr_list.pull_requests` weigh, the tickets list,
    the runs list, the PRs, a PR's decisions, and a chore's runs each read every row ever recorded, on every commit.
    """
    with backend.open() as ctx:
        add_history(ctx.conn, 0, 1_200)
        before = {name: instructions(ctx, lambda read=read: read(backend, ctx)) for name, read in READS.items()}
        add_history(ctx.conn, 1_200, 4_800)
        after = {name: instructions(ctx, lambda read=read: read(backend, ctx)) for name, read in READS.items()}
    # A deeper index costs a step or two more: SLACK steps, on reads too small for a share of them to show it.
    grown = {name: after[name] for name in READS if after[name] > before[name] * GROWTH + SLACK}
    assert grown == {}, (before, after)


def test_the_stream_reads_the_same_lists_over_a_long_history(backend: Backend) -> None:
    with backend.open() as ctx:
        add_history(ctx.conn, 0, 1_500)
        events = [e.root for e in live._Sent().changes(backend, ctx)]  # noqa: SLF001  (the stream's own record)
    [tickets] = [e for e in events if isinstance(e, live.TicketsUpdated)]
    # The mock's seven of the day, newest first, the two it landed in October, its feedback plans' seven of eight days
    # before, the rest it landed, then the history's newest.
    landed = [t.key for t in sorted(serve_history.TICKETS, key=lambda t: t.done_at, reverse=True)]
    newest = ["ABC-101", "ABC-104", "ABC-102", "ABC-105", "ABC-099", "ABC-100", "ABC-103", *landed[:2]]
    newest += ["ABC-136", "ABC-135", "ABC-134", "ABC-133", "ABC-132", "ABC-131", "ABC-130", *landed[2:], "OLD-0"]
    assert [t.key for t in tickets.tickets[: len(newest)]] == newest
    assert len(tickets.tickets) == views.TICKETS
    [runs] = [e for e in events if isinstance(e, live.RunsUpdated)]
    assert len([r for r in runs.runs if r.state != "running"]) == views.RECENT_RUNS


@pytest.mark.parametrize("seed", range(25))
def test_the_tickets_list_is_what_weighing_every_ticket_finds(journals: Journals, tmp_path: Path, seed: int) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    rnd = random.Random(seed)  # noqa: S311  (journals to compare, not secrets)
    keys = [f"K-{i}" for i in range(20)]
    with db.transaction(conn):
        conn.execute("INSERT INTO ticks (id, started_at, status) VALUES (1, 'x', 'ok')")
        for key in keys:
            conn.execute(
                "INSERT INTO tickets (key, repo, first_seen_at, last_seen_at, changed_at) "
                "VALUES (?, '/r', '0', '0', ?)",
                (key, moment(rnd)),
            )
            for _ in range(rnd.randrange(4)):
                start = moment(rnd)
                ended = rnd.choice([None, max(start, moment(rnd))])
                conn.execute(
                    "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, ended_at, status, log_path) "
                    "VALUES (1, ?, 'implement', 'b', ?, ?, ?, 'x.log')",
                    (key, start, ended, "running" if ended is None else "done"),
                )
            if rnd.random() < 0.3:
                stopped = rnd.choice([None, moment(rnd)])
                conn.execute(
                    "INSERT INTO starts (subject_kind, subject_id, status, started_at, stopped_at, channel) "
                    "VALUES ('ticket', ?, ?, ?, ?, 'cli')",
                    (key, "started" if stopped is None else "stopped", moment(rnd), stopped),
                )
        # Messages about tickets the journal has no row for, and about a chore, weigh nothing.
        for subject in [*rnd.choices(keys, k=30), "GHOST-1", "GHOST-2"]:
            conn.execute(
                "INSERT INTO messages (subject_kind, subject_id, at, source, kind, channel, body) "
                "VALUES ('ticket', ?, ?, 'operator', 'reply', 'cli', 'b')",
                (subject, moment(rnd)),
            )
        conn.execute(
            "INSERT INTO messages (subject_kind, subject_id, at, source, kind, channel, body) "
            "VALUES ('chore', 'K-1', '99', 'operator', 'reply', 'cli', 'b')",
        )
    for limit in range(1, len(keys) + 2):
        found = [(r["key"], r["active_at"]) for r in db.recent_tickets(conn, limit)]
        assert found == every_ticket(conn, limit), limit


@pytest.mark.parametrize("seed", range(25))
def test_the_pull_requests_are_what_weighing_every_one_finds(journals: Journals, tmp_path: Path, seed: int) -> None:
    conn = journals.open(tmp_path / "canopy.db")
    rnd = random.Random(seed)  # noqa: S311  (journals to compare, not secrets)
    urls = [f"https://github.com/acme/web/pull/{i}" for i in range(16)]
    owned = rnd.sample(urls, 8)
    with db.transaction(conn):
        conn.execute("INSERT INTO ticks (id, started_at, status) VALUES (1, 'x', 'ok')")
        for i in range(10):
            key = f"K-{i}"
            conn.execute(
                "INSERT INTO tickets (key, repo, first_seen_at, last_seen_at, changed_at, title) "
                "VALUES (?, '/r', '0', '0', ?, ?)",
                (key, moment(rnd), f"Ticket {i}"),
            )
            # A unit with no PR yet, and a PR no other unit has: a PR is one unit's.
            for repo in ("api", "web"):
                url = owned.pop() if owned and rnd.random() < 0.6 else None
                conn.execute(
                    "INSERT INTO ticket_units (ticket_key, repo, branch, pr_url, phase) VALUES (?, ?, 'b', ?, 'p')",
                    (key, repo, url),
                )
        for _ in range(25):
            start = moment(rnd)
            ended = rnd.choice([None, max(start, moment(rnd))])
            conn.execute(
                "INSERT INTO review_runs (tick_id, pr_url, sha, started_at, ended_at, status, log_path) "
                "VALUES (1, ?, 'abc', ?, ?, ?, 'x.log')",
                (rnd.choice(urls), start, ended, "running" if ended is None else "done"),
            )
    for limit in range(1, len(urls) + 2):
        found = [tuple(r) for r in pr_list.pull_requests(conn, limit)]
        assert found == every_pull_request(conn, limit), limit
    for url in urls:
        assert [tuple(r) for r in pr_list.pull_requests(conn, 1, url=url)] == every_pull_request(conn, 1, url=url)


def test_a_findings_start_is_read_back_once(backend: Backend) -> None:
    """A finding open for hundreds of runs reads them all once; later reads stop at the run the last one reached."""
    real = chore_result.stored
    with backend.open() as ctx:
        # The mock's run 2 found the advisory, and its run 1 did not; these 300 report it again.
        for n in range(300):
            ok_run(ctx.conn, 100 + n, -230 + n * 0.5, [ADVISORY])
    with mock.patch.object(chore_result, "stored", autospec=True, side_effect=real) as stored:
        assert advisory_since(backend) == serve_mock.at(-240)
        assert stored.call_count > 300
        stored.reset_mock()
        # A request after reads only what the page shows: the latest run, and each of the runs it lists.
        assert advisory_since(backend) == serve_mock.at(-240)
        assert stored.call_count == PAGE
        stored.reset_mock()
        with backend.open() as ctx:
            ok_run(ctx.conn, 400, -60, [ADVISORY])
        # A new run that reports it again: the walk stops at the run the last read remembered.
        assert advisory_since(backend) == serve_mock.at(-240)
        assert stored.call_count == PAGE
    # A server that remembers nothing finds the same, the long way.
    fresh = dataclasses.replace(backend)
    assert advisory_since(fresh) == serve_mock.at(-240)
    with backend.open() as ctx:
        ok_run(ctx.conn, 401, -50, [])
        ok_run(ctx.conn, 402, -40, [ADVISORY])
    # An ok run without it ended the sequence: the one after begins a new one.
    assert advisory_since(backend) == db.format_time(serve_mock.T0 + timedelta(minutes=-40))
    assert advisory_since(dataclasses.replace(backend)) == advisory_since(backend)


ADVISORY = {"id": "lodash-advisory", "title": "lodash 4.17.20 has a prototype pollution advisory"}
# The results a chore's page reads with nothing to walk: its latest `ok` run's, its summary's, and each run it lists.
PAGE = 2 + chore_views.CHORE_RUNS


def advisory_since(backend: Backend) -> str:
    with backend.open() as ctx:
        found = chore_views.chore(backend, ctx, serve_mock.CHORE)
    assert found is not None
    [finding] = found.chore.findings
    assert finding.id == ADVISORY["id"]
    return db.format_time(finding.since)


def ok_run(conn: sqlite3.Connection, run_id: int, minutes: float, findings: list[dict[str, str]]) -> None:
    start = serve_mock.T0 + timedelta(minutes=minutes)
    conn.execute(
        "INSERT INTO chore_runs (id, tick_id, chore, started_at, ended_at, status, result_json, log_path) "
        "VALUES (?, 1, ?, ?, ?, 'ok', ?, 'x.log')",
        (
            run_id,
            serve_mock.CHORE,
            db.format_time(start),
            db.format_time(start + timedelta(minutes=0.2)),
            json.dumps({"status": "ok", "summary": "checked", "findings": findings}),
        ),
    )


def instructions(ctx: Context, read: Callable[[], object]) -> int:
    """How many hundred SQLite instructions `read` ran on `ctx`'s connection.

    That is what it read, in a measure that never depends on the machine running the test.
    """
    counted = [0]

    def count() -> int:
        counted[0] += 1
        return 0

    ctx.conn.set_progress_handler(count, STEP)
    try:
        read()
    finally:
        ctx.conn.set_progress_handler(None, STEP)
    return counted[0]


def add_history(conn: sqlite3.Connection, first: int, count: int) -> None:
    """Items `first` to `first + count` of a history older than the mock's rows, each older than the one before.

    Each item is a tick with a decision, a ticket with a unit, a PR, a run in a slot, and a message, a review of the
    PR, and a chore run that checked and found nothing; every fourth ticket was started and stopped privately. Ids
    count down from below the mock's, as an older row's would.
    """
    rows = range(first, first + count)
    with db.transaction(conn):
        conn.executemany(
            "INSERT INTO ticks (id, started_at, ended_at, status, summary, cost_usd) "
            "VALUES (?, ?, ?, 'ok', 'an old tick', 0.1)",
            [(-1 - i, old(i), old(i, 1)) for i in rows],
        )
        conn.executemany(
            "INSERT INTO tickets (key, repo, first_seen_at, last_seen_at, changed_at, phase, done) "
            "VALUES (?, '/r', ?, ?, ?, 'merged', 1)",
            [(f"OLD-{i}", old(i), old(i, 2), old(i, 2)) for i in rows],
        )
        conn.executemany(
            "INSERT INTO ticket_units (ticket_key, repo, branch, pr_url, phase) VALUES (?, 'web', ?, ?, 'merged')",
            [(f"OLD-{i}", f"agent/OLD-{i}", old_pr(i)) for i in rows],
        )
        conn.executemany(
            "INSERT INTO runs (id, tick_id, ticket_key, kind, branch, started_at, ended_at, status, result_json, "
            "log_path, cost_usd) VALUES (?, ?, ?, 'implement', ?, ?, ?, 'done', ?, 'x.log', 1.0)",
            [
                (-1 - i, -1 - i, f"OLD-{i}", f"agent/OLD-{i}", old(i), old(i, 3), json.dumps({"summary": "done"}))
                for i in rows
            ],
        )
        conn.executemany(
            "INSERT INTO run_slots (run_id, repo, slot_path, lease_id, lease_holder) VALUES (?, 'web', 's', ?, 'h')",
            [(-1 - i, f"lease-old-{i}") for i in rows],
        )
        conn.executemany(
            "INSERT INTO messages (id, subject_kind, subject_id, at, source, kind, channel, run_id, body) "
            "VALUES (?, 'ticket', ?, ?, 'worker', 'report', 'run', ?, 'done')",
            [(-1 - i, f"OLD-{i}", old(i, 3), -1 - i) for i in rows],
        )
        conn.executemany(
            "INSERT INTO starts (subject_kind, subject_id, status, started_at, stopped_at, channel) "
            "VALUES ('ticket', ?, 'stopped', ?, ?, 'cli')",
            [(f"OLD-{i}", old(i), old(i, 4)) for i in rows if i % 4 == 0],
        )
        conn.executemany(
            "INSERT INTO decisions (id, tick_id, ticket_key, action, rationale, created_at, pr) "
            "VALUES (?, ?, ?, 'wait', 'waiting on review', ?, ?)",
            [(-1 - i, -1 - i, f"OLD-{i}", old(i), old_pr(i)) for i in rows],
        )
        conn.executemany(
            "INSERT INTO review_runs (id, tick_id, pr_url, sha, ticket_key, repo, started_at, ended_at, status, "
            "result_json, log_path, cost_usd) VALUES (?, ?, ?, 'abc', ?, 'web', ?, ?, 'done', ?, 'x.log', 0.5)",
            [(-1 - i, -1 - i, old_pr(i), f"OLD-{i}", old(i), old(i, 1), json.dumps({"summary": "fine"})) for i in rows],
        )
        conn.executemany(
            "INSERT INTO chore_runs (id, tick_id, chore, started_at, ended_at, status, result_json, log_path, "
            "cost_usd) VALUES (?, ?, ?, ?, ?, 'ok', ?, 'x.log', 0.2)",
            [(-1 - i, -1 - i, serve_mock.CHORE if i % 2 else "build-health", old(i), old(i, 1), CLEAR) for i in rows],
        )


CLEAR = json.dumps({"status": "ok", "summary": "nothing found", "findings": []})


def old(item: int, minutes: int = 0) -> str:
    return db.format_time(serve_mock.T0 - timedelta(minutes=HISTORY_STARTS + 10 * item - minutes))


def old_pr(item: int) -> str:
    return f"https://github.com/acme/web/pull/{100_000 + item}"


def moment(rnd: random.Random) -> str:
    """One of a few times, so ties are common."""
    return f"2026-01-0{rnd.randint(1, 6)}T00:00:00.000Z"


def every_ticket(conn: sqlite3.Connection, limit: int) -> list[tuple[str, str]]:
    """The tickets list as it was read before migration 0022: every ticket's activity, weighed."""
    rows = conn.execute(
        "SELECT t.key, max("
        "  t.changed_at,"
        "  coalesce((SELECT max(m.at) FROM messages m WHERE m.subject_kind = 'ticket' AND m.subject_id = t.key), ''),"
        "  coalesce((SELECT max(coalesce(r.ended_at, r.started_at)) FROM runs r WHERE r.ticket_key = t.key), ''),"
        "  coalesce((SELECT coalesce(s.stopped_at, s.started_at) FROM starts s"
        "    WHERE s.subject_kind = 'ticket' AND s.subject_id = t.key), '')"
        ") AS active_at "
        "FROM tickets t ORDER BY active_at DESC, t.key LIMIT ?",
        (limit,),
    )
    return [(str(r[0]), str(r[1])) for r in rows]


def every_pull_request(conn: sqlite3.Connection, limit: int, *, url: str | None = None) -> list[tuple[object, ...]]:
    """The PRs as read before migration 0022, with their own titles: every unit and every review run, weighed."""
    rows = conn.execute(
        "SELECT k.url, max(k.at) AS active_at, u.ticket_key, u.repo, u.branch, u.phase, t.title, p.title "
        "FROM ("
        "  SELECT u.pr_url AS url, t.changed_at AS at FROM ticket_units u JOIN tickets t ON t.key = u.ticket_key"
        "  WHERE u.pr_url IS NOT NULL"
        "  UNION ALL SELECT pr_url, coalesce(ended_at, started_at) FROM review_runs"
        ") k "
        "LEFT JOIN ticket_units u ON u.pr_url = k.url LEFT JOIN tickets t ON t.key = u.ticket_key "
        "LEFT JOIN pr_titles p ON p.pr_url = k.url "
        "WHERE ? IS NULL OR k.url = ? GROUP BY k.url ORDER BY active_at DESC, k.url LIMIT ?",
        (url, url, limit),
    )
    return [tuple(r) for r in rows]
