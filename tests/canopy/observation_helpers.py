"""Helpers the tests of the connectors' observations share: rows written by hand, as a source would (DESIGN §30, §35).

Each writes one observation straight into the journal, with the journal number a source would give it (DESIGN §35):
the next one, the first time it is written. The times default to fixed ones around `NOW`; a test that dispatches, which
reads the observations at the real time, passes its own.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest import mock

from canopy.core import artifact_feed, conversation, db, item_numbers, records, sql
from canopy.core.vocab import NumberedItem
from tests.canopy.helpers import KEY, LABEL, present

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


def comment(
    conn: sqlite3.Connection,
    ident: str,
    author: str,
    at: str,
    body: str,
    *,
    source: str = "tracker",
) -> int:
    """Record a tracker comment on KEY.

    Returns:
        Its journal number, what a `comment` cursor names.
    """
    number = item_numbers.take(conn, NumberedItem.COMMENT, KEY, ident, at=FRESH)
    conn.execute(
        "INSERT INTO observed_comments (ticket, id, author, commented_at, body, truncated, source, observed_at, "
        "number) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)",
        (KEY, ident, author, at, body, source, FRESH, number),
    )
    return number


def number_of(conn: sqlite3.Connection, kind: NumberedItem, ident: str | int, *, subject: str | None = None) -> int:
    """The journal number of an item the helpers recorded: a comment on KEY, or another kind on PR by default.

    Returns:
        Its number.
    """
    return item_numbers.take(conn, kind, subject or (KEY if kind is NumberedItem.COMMENT else PR), ident, at=FRESH)


def review_number(conn: sqlite3.Connection, ident: int) -> str:
    """The journal number a source gave review item `ident`, as a `review` cursor names it.

    Returns:
        The number, as the overseer passes it.
    """
    [found] = records.fetch_all(
        conn,
        records.ObservedReview,
        sql.select("*").from_("observed_reviews").where("id = ?", ident),
    )
    return str(found.number)


def observed_comments(conn: sqlite3.Connection) -> list[records.ObservedComment]:
    """KEY's observed comments, in the order the block reads them: the order they were first observed."""
    return records.fetch_all(
        conn,
        records.ObservedComment,
        sql.select("*").from_("observed_comments").order_by("number"),
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
    """Record a check of PR at `head` as a read does: the newest run of its context, and the run kept once it ends.

    A completed run takes its journal number, what a `ci` cursor names; see `number_of`.
    """
    done = status == "completed" and conclusion is not None
    number = item_numbers.take(conn, NumberedItem.CHECK_RUN, PR, run_id, at=FRESH) if done else None
    conn.execute(
        "INSERT OR REPLACE INTO observed_checks (pr_url, name, head_sha, status, conclusion, run_id, url, observed_at, "
        "number) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            PR,
            name,
            head,
            status,
            conclusion,
            run_id,
            f"https://github.com/acme/repo/actions/runs/{run_id}",
            FRESH,
            number,
        ),
    )
    if done:
        conn.execute(
            "INSERT OR IGNORE INTO observed_check_runs (pr_url, run_id, name, head_sha, conclusion, observed_at, "
            "number) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (PR, run_id, name, head, conclusion, FRESH, number),
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
) -> int:
    """Record a review, or with `item` a review comment, of PR by `author`.

    Returns:
        Its journal number, what a `review` cursor names.
    """
    thread = "PRRT_1" if item == "comment" else None
    kind = NumberedItem.REVIEW if item == "review" else NumberedItem.REVIEW_COMMENT
    number = item_numbers.take(conn, kind, PR, ident, at=FRESH)
    conn.execute(
        "INSERT INTO observed_reviews (pr_url, item, id, author, bot, state, created_at, body, url, thread_id, "
        "observed_at, number) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (PR, item, ident, author, bot, state, at, body, f"{PR}#review-{ident}", thread, FRESH, number),
    )
    return number


#: Who comments on an artifact in the helpers' changes: a person the store signed in.
ANA = {"id": "u_ana", "display_name": "Ana", "kind": "person"}


def artifact_comment(
    conn: sqlite3.Connection,
    ident: str,
    author: str = "u_ana",
    *,
    kind: str = "person",
    marked: bool = False,
    key: str = KEY,
    body: str = "Shard by tenant, not by day.",
) -> int:
    """Record comment `ident` on `key`'s artifact as the `artifacts` source does: observed, and in its conversation.

    Returns:
        The id of its message in `key`'s conversation.
    """
    conn.execute(
        "INSERT OR IGNORE INTO observed_artifact_threads (id, artifact_id, origin, ticket, anchored_version, state, "
        "seq, observed_at) VALUES (?, ?, ?, ?, 1, 'open', 1, ?)",
        (f"t-{key}", f"art-{key}", json.dumps({artifact_feed.TICKET_KEY: key}), key, FRESH),
    )
    conn.execute(
        "INSERT INTO observed_artifact_comments (id, thread_id, author, author_name, author_kind, via, body, "
        "truncated, marked, created_at, seq, observed_at) VALUES (?, ?, ?, ?, ?, 'web', ?, 0, ?, ?, 1, ?)",
        (ident, f"t-{key}", author, author, kind, body, marked, FRESH, FRESH),
    )
    said = db.Comment(id=f"{artifact_feed.COMMENT_ID_PREFIX}{ident}", author=author, at=FRESH, truncated=False)
    source = "worker" if marked else artifact_feed.SOURCE
    conversation.record_comment(conn, key, said, source=source, body=body, channel=conversation.ARTIFACTS)
    return present(db.comment_message(conn, conversation.TICKET, key, said.id)).id


def artifact_change(seq: int, kind: str = "comment_created", **more: object) -> dict[str, object]:
    """A line of an artifact store's comment feed: a change to comment `c{seq}` in thread `t1` of KEY's artifact."""
    found: dict[str, object] = {
        "kind": kind,
        "seq": seq,
        "at": "2026-10-23T10:00:00Z",
        "artifact_id": "art_1",
        "origin": {"canopy.ticket": KEY, "canopy.run": "7"},
        "thread_id": "t1",
        "anchor": {"exact": "shard it", "prefix": "We should ", "suffix": "."},
        "anchored_version": 1,
        "state": "open",
        "anchor_status": "found",
        "comment_id": f"c{seq}",
        "author": ANA,
        "via": "web",
        "body": f"Comment {seq}.",
        "created_at": "2026-10-23T10:00:00Z",
        "edited_at": None,
        "deleted_at": None,
    }
    return {**found, **more}
