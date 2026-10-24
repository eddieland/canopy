"""Journal numbers (DESIGN §35, ROADMAP M37): the cursors a journal held before them, converted to numbers.

Each old form: a `comment` cursor by the tracker's id, named or not; a `review` cursor by time, to the second, or in no
form a reader read; a `ci` cursor by check run id, named or not.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import db, records, sql
from canopy.core.vocab import NumberedItem
from canopy.infra import resources
from tests.canopy.helpers import journal_at, old_ticket, versions_after

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from tests.conftest import Journals

#: The migration that numbered the journal.
VERSION = next(m.version for m in db.discover(resources.migrations_dir()) if m.name == "journal_numbers")
PR = "https://github.com/acme/api/pull/7"
OTHER = "https://github.com/acme/api/pull/8"


def test_each_old_cursor_becomes_the_number_of_the_item_it_names(tmp_path: Path, journals: Journals) -> None:
    conn = journal_at(journals, tmp_path, VERSION - 1)
    comments(conn)
    reviews(conn)
    check_runs(conn)
    cursors = {
        # The comment it names; a number naming none, passing those before the first larger id; one in no form.
        "NAMED": ("c-2", "2026-10-18T09:00:00Z", "12"),
        "BETWEEN": ("15", "2026-10-18T10:00:00.900Z", "99"),
        "GONE": ("gone", "run:5", "5"),
        # No comment observed: no tracker source may observe it, so its tracker id stays and it takes no number.
        "UNTRACKED": ("10234", "2026-10-18T07:00:00Z", "run-7"),
    }
    for key, (comment, review, ci) in cursors.items():
        old_ticket(conn, key)
        conn.execute("UPDATE tickets SET last_comment_id = ? WHERE key = ?", (comment, key))
        conn.execute(
            "INSERT INTO ticket_units (ticket_key, repo, pr_url, last_review_id, last_ci_run_id) "
            "VALUES (?, 'api', ?, ?, ?)",
            (key, PR, review, ci),
        )
    assert db.migrate(conn, resources.migrations_dir()) == versions_after(VERSION - 1)

    number = numbers(conn)
    tickets = {t.key: t for t in records.fetch_all(conn, records.Ticket, sql.select("*").from_("tickets"))}
    assert {k: (t.comment_cursor, t.last_comment_id) for k, t in tickets.items()} == {
        "NAMED": (number["comment", "NAMED", "c-2"], "c-2"),
        "BETWEEN": (number["comment", "BETWEEN", "10"], "15"),
        "GONE": (None, "gone"),
        "UNTRACKED": (None, "10234"),
    }
    units = {
        u.ticket_key: u for u in records.fetch_all(conn, records.TicketUnit, sql.select("*").from_("ticket_units"))
    }
    assert {k: (u.review_cursor, u.ci_cursor) for k, u in units.items()} == {
        # A review time passes every item at its second, the review run that ended then included.
        "NAMED": (number["review_run", PR, "1"], number["check_run", PR, "12"]),
        "BETWEEN": (number["review_comment", PR, "3"], number["check_run", PR, "13"]),
        "GONE": (None, 0),
        # A time before every item passed none of them: 0, still a cursor that is set.
        "UNTRACKED": (0, None),
    }
    # Each observation carries its number, kept in the order each old cursor read them, subject by subject.
    kept = [
        r.number for r in records.fetch_all(conn, records.ObservedReview, sql.select("*").from_("observed_reviews"))
    ]
    assert None not in kept
    assert number["review", PR, "1"] < number["review_comment", PR, "2"] < number["review_run", PR, "1"]
    assert number["review_run", PR, "1"] < number["review_comment", PR, "3"]
    assert number["check_run", PR, "11"] < number["check_run", PR, "12"] < number["check_run", PR, "13"]
    checks = records.fetch_all(conn, records.ObservedCheck, sql.select("*").from_("observed_checks"))
    assert [(c.run_id, c.number) for c in checks] == [(13, number["check_run", PR, "13"])]


def comments(conn: sqlite3.Connection) -> None:
    """Three comments on each ticket that gets some, written in the order of their ids `c-1` to `c-3` and 10 to 30."""
    observed = (
        "INSERT INTO observed_comments (ticket, id, author, commented_at, body, truncated, source, observed_at) "
        "VALUES (?, ?, 'acc-1', ?, 'Hello.', 0, 'tracker', 'x')"
    )
    for key, ids in (("NAMED", ("c-1", "c-2", "c-3")), ("BETWEEN", ("10", "20", "30")), ("GONE", ("a", "b", "c"))):
        for n, ident in enumerate(ids):
            conn.execute(observed, (key, ident, f"2026-10-18T0{n}:00:00.000Z"))


def reviews(conn: sqlite3.Connection) -> None:
    """A review, two review comments, and a review run that ended between them, on PR; a review on another PR."""
    observed = (
        "INSERT INTO observed_reviews (pr_url, item, id, author, bot, state, created_at, body, thread_id, observed_at) "
        "VALUES (?, ?, ?, 'octocat', 0, ?, ?, '', ?, 'x')"
    )
    conn.execute(observed, (PR, "review", 1, "commented", "2026-10-18T08:00:00.000Z", None))
    conn.execute(observed, (PR, "comment", 2, None, "2026-10-18T09:00:00.000Z", "PRRT_1"))
    conn.execute(observed, (PR, "comment", 3, None, "2026-10-18T10:00:00.500Z", "PRRT_1"))
    conn.execute(observed, (OTHER, "review", 1, "commented", "2026-10-18T06:00:00.000Z", None))
    tick = db.start_tick(conn, dry_run=False)
    conn.execute(
        "INSERT INTO review_runs (tick_id, pr_url, sha, started_at, ended_at, status, log_path) "
        "VALUES (?, ?, 'abc1234', ?, ?, 'done', 'x')",
        (tick, PR, "2026-10-18T08:50:00.000Z", "2026-10-18T09:00:00.700Z"),
    )


def check_runs(conn: sqlite3.Connection) -> None:
    """Runs 11 and 12 of PR kept, and run 13 at its head as a read left it."""
    for run in (12, 11):
        conn.execute(
            "INSERT INTO observed_check_runs (pr_url, run_id, name, head_sha, conclusion, observed_at) "
            "VALUES (?, ?, 'build', 'abc1234', 'failure', 'x')",
            (PR, run),
        )
    conn.execute(
        "INSERT INTO observed_checks (pr_url, name, head_sha, status, conclusion, run_id, url, observed_at) "
        "VALUES (?, 'build', 'abc1234', 'completed', 'failure', 13, NULL, 'x')",
        (PR,),
    )


def numbers(conn: sqlite3.Connection) -> dict[tuple[str, str, str], int]:
    """Every item's journal number, by its kind, subject, and id."""
    found = records.fetch_all(conn, records.ItemNumber, sql.select("*").from_("item_numbers"))
    assert {n.kind for n in found} == set(NumberedItem)
    return {(n.kind.value, n.subject, n.id): n.number for n in found}
