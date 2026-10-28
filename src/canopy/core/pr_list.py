"""The PR list (DESIGN §22): every PR the journal knows, by its most recent activity.

A PR is known by a ticket's unit, by a review run, or by the operator's review request; none of them owns the list.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final, LiteralString

from canopy.core import db, sql

if TYPE_CHECKING:
    import sqlite3


def pull_requests(conn: sqlite3.Connection, limit: int, *, url: str | None = None) -> list[sqlite3.Row]:
    """Return the `limit` PRs with the most recent activity, most recently active first; with `url`, only it (§22).

    A PR is known by a ticket's unit, whose activity is the ticket's last change, by a review run, whose activity
    is its start or end, or by the operator's review request, whose activity is when it was made or ended. Each row
    has `url` and `active_at`, and the unit's `ticket_key`, `repo`, `branch`, `phase`, and the ticket's `title`, all
    NULL for a PR no unit records, and the PR's own `pr_title`, NULL until a worker reports one. Decisions are not a
    source: they are many. Only the candidates `db.candidates` finds are weighed, so the read costs what `limit` does.
    """
    if limit < 1:
        return []
    with db.read_snapshot(conn):
        urls = json.dumps([url] if url is not None else db.candidates(conn, _PR_ACTIVITY, limit))
        return _weighed_pull_requests(conn, urls, limit)


def _weighed_pull_requests(conn: sqlite3.Connection, urls: str, limit: int) -> list[sqlite3.Row]:
    among: LiteralString = "pr_url IN (SELECT value FROM json_each(?))"
    activity = sql.union(
        sql.select("u.pr_url AS url, t.changed_at AS at")
        .from_("ticket_units u")
        .join("tickets t ON t.key = u.ticket_key")
        .where("u.pr_url IN (SELECT value FROM json_each(?))", urls),
        sql.select("pr_url, coalesce(ended_at, started_at)").from_("review_runs").where(among, urls),
        sql.select("pr_url, coalesce(ended_at, created_at)").from_("review_requests").where(among, urls),
        every=True,
    )
    query = (
        sql.select(
            "k.url, max(k.at) AS active_at, u.ticket_key, u.repo, u.branch, u.phase, t.title, p.title AS pr_title",
        )
        .from_("({}) k", activity)
        .left_join("ticket_units u ON u.pr_url = k.url")
        .left_join("tickets t ON t.key = u.ticket_key")
        .left_join("pr_titles p ON p.pr_url = k.url")
        .group_by("k.url")
        .order_by("active_at DESC, k.url")
        .limit(limit)
    )
    return sql.execute(conn, query).fetchall()


# Each source of a PR's activity as `pull_requests` weighs it, for `db.candidates`: its units by when their ticket last
# changed, its review runs by when each ended, or started while it runs (`db.finish_run` sets the end), and its
# review requests by when each ended, or was made while it is open.
# CROSS JOIN keeps SQLite reading the tickets in order and each one's units after, rather than sorting every unit.
_PR_ACTIVITY: Final = (
    sql.select("u.pr_url, t.changed_at")
    .from_("tickets t CROSS JOIN ticket_units u ON u.ticket_key = t.key")
    .where("u.pr_url IS NOT NULL")
    .order_by("t.changed_at DESC"),
    sql.select("pr_url, ended_at").from_("review_runs").where("ended_at IS NOT NULL").order_by("ended_at DESC"),
    sql.select("pr_url, started_at").from_("review_runs").where("status = 'running'").order_by("started_at DESC"),
    sql.select("pr_url, coalesce(ended_at, created_at) AS at").from_("review_requests").order_by("at DESC"),
)
