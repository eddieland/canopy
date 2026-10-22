"""Helpers the tests of the connectors' observations share: rows written by hand, as a source would (DESIGN §30, §35).

Each writes one observation straight into the journal. The times default to fixed ones around `NOW`; a test that
dispatches, which reads the observations at the real time, passes its own.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest import mock

from canopy.core import db, records, sql
from tests.canopy.helpers import KEY, LABEL

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator

    from tests.conftest import CanopyEnv

#: The time the observation tests are read at; an observation at `FRESH` is fresh, one at `OLD` stale.
NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)
#: When canopy first held the tests' tickets: before any was observed.
FIRST_SEEN = "2026-10-20T09:00:00.000Z"
FRESH = "2026-10-20T11:59:00.000Z"
OLD = "2026-10-20T10:00:00.000Z"
PR = "https://github.com/acme/repo/pull/7"
HEAD = "abc1234"
#: A tracker source, so tickets are observed.
TRACKER = {"connect": {"sources": {"jira": {"kind": "tracker", "cmd": "connector jira"}}}}
#: Who the tests trust: `acc-1` replies, `octocat` reviews.
TRUST = {"trust": {"authorized_repliers": ["acc-1"], "trusted_reviewers": ["Octocat"]}}


@contextmanager
def clock(stamp: str) -> Iterator[None]:
    """Until the block ends, the journal records every time it writes as `stamp`."""
    with mock.patch.object(db, "now", autospec=True, return_value=stamp):
        yield


def held(env: CanopyEnv, conn: sqlite3.Connection, key: str, *, at: str = FIRST_SEEN) -> None:
    """Record `key` as a ticket canopy has held since `at`."""
    with clock(at):
        db.touch_ticket(conn, key, str(env.root))


def observe_ticket(
    conn: sqlite3.Connection,
    key: str = KEY,
    *,
    state: str = "open",
    labels: dict[str, str | None] | None = None,
    body: str = "",
    at: str = FRESH,
) -> None:
    """Record the tracker's view of `key`: labeled with the queue label unless `labels` says otherwise."""
    named = {LABEL: None} if labels is None else labels
    conn.execute(
        "INSERT INTO observed_tickets (key, title, body, state, labels, updated_at, blockers, observed_at) "
        "VALUES (?, 'Retry flaky uploads', ?, ?, ?, NULL, '[]', ?)",
        (key, body, state, json.dumps([{"name": n, "added_at": a} for n, a in named.items()]), at),
    )


def comment(conn: sqlite3.Connection, ident: str, author: str, at: str, body: str, *, source: str = "tracker") -> None:
    """Record a tracker comment on KEY."""
    conn.execute(
        "INSERT INTO observed_comments (ticket, id, author, commented_at, body, truncated, source, observed_at) "
        "VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
        (KEY, ident, author, at, body, source, FRESH),
    )


def observed_comments(conn: sqlite3.Connection) -> list[records.ObservedComment]:
    """KEY's observed comments, in the order the block reads them."""
    return records.fetch_all(
        conn,
        records.ObservedComment,
        sql.select("*").from_("observed_comments").order_by("commented_at, id"),
    )


def branches_read(conn: sqlite3.Connection, *, at: str = FRESH) -> None:
    """Record a `vcs` run that read the repository's branches whole, with none under the prefix."""
    conn.execute(
        "INSERT INTO connector_runs (tick_id, source, kind, started_at, ended_at, status, request, recorded, refused, "
        "stderr) VALUES (NULL, 'github', 'vcs', ?, ?, 'ok', ?, '{}', '{}', '')",
        (at, at, json.dumps({"repositories": [{"name": "repo"}]})),
    )


def query_read(conn: sqlite3.Connection, keys: list[str], *, at: str = FRESH) -> None:
    """Record a `tracker` run that read the query to its end, returning `keys`."""
    conn.execute(
        "INSERT INTO connector_runs (tick_id, source, kind, started_at, ended_at, status, request, recorded, refused, "
        "stderr, query_result) VALUES (NULL, 'jira', 'tracker', ?, ?, 'ok', '{}', '{}', '{}', '', ?)",
        (at, at, json.dumps(keys)),
    )


def observe_pr(conn: sqlite3.Connection, *, url: str = PR, at: str = FRESH) -> None:
    """Record a PR as the reader saw it, open at HEAD, opened by `operator`."""
    conn.execute(
        "INSERT INTO observed_prs (url, repository, number, head_sha, base_ref, state, draft, mergeable, author, "
        "observed_at, labels, mergeable_state) VALUES (?, 'acme/repo', 7, ?, 'main', 'open', 0, 'mergeable', "
        "'operator', ?, '[]', 'blocked')",
        (url, HEAD, at),
    )


def check(
    conn: sqlite3.Connection,
    name: str,
    status: str,
    conclusion: str | None,
    *,
    run_id: int = 11,
    head: str = HEAD,
) -> None:
    """Record a check of PR at `head`."""
    conn.execute(
        "INSERT INTO observed_checks (pr_url, name, head_sha, status, conclusion, run_id, url, observed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (PR, name, head, status, conclusion, run_id, f"https://github.com/acme/repo/actions/runs/{run_id}", FRESH),
    )


def review(
    conn: sqlite3.Connection,
    ident: int,
    author: str,
    state: str | None,
    at: str,
    body: str = "",
    *,
    item: str = "review",
    bot: bool = False,
) -> None:
    """Record a review, or with `item` a review comment, of PR by `author`."""
    thread = "PRRT_1" if item == "comment" else None
    conn.execute(
        "INSERT INTO observed_reviews (pr_url, item, id, author, bot, state, created_at, body, url, thread_id, "
        "observed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (PR, item, ident, author, bot, state, at, body, f"{PR}#review-{ident}", thread, FRESH),
    )
