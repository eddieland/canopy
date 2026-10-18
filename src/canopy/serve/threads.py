"""A PR's review threads and the drafts that answer them, as the API sends them (DESIGN §29, On the PR's diff).

The threads are what canopy's own reader last read of the PR, never a worker's copy of them, and the diff is the one
the latest run under `approve` kept at its pushed head. A coworker's comment and a worker's draft are both untrusted
text, sent as the journal holds them for the UI to show as plain text.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from collections.abc import Set as AbstractSet
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from canopy.core import db, drafts, drafts_manage, records, review_diff
from canopy.core.vocab import DraftKind, ReviewItem
from canopy.serve.draft_views import draft
from canopy.serve.reviews import diff_view
from canopy.serve.schema import (
    Draft,
    DraftFailure,
    DraftsSent,
    PullRequestThreads,
    Thread,
    ThreadComment,
)

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.context import Context


def threads(ctx: Context, url: str) -> PullRequestThreads | None:
    """The PR's threads on its latest kept diff, with every draft for it, or None when the journal knows neither.

    Returns:
        The threads, the PR's own comment's drafts, and the drafts no read has placed on a thread.
    """
    conn = ctx.conn
    observed = records.fetch_one(conn, records.ObservedPr, "SELECT * FROM observed_prs WHERE url = ?", (url,))
    found = records.fetch_all(
        conn, records.Draft, "SELECT * FROM drafts WHERE pr_url = ? ORDER BY run_id, number", (url,)
    )
    if observed is None and not found:
        return None
    views = {d.id: draft(conn, d) for d in found}
    kept = _kept_diff(conn, url)
    diff = review_diff.read(kept[1]) if kept is not None else None
    comments = records.fetch_all(
        conn,
        records.ObservedReview,
        "SELECT * FROM observed_reviews WHERE pr_url = ? AND item = ? ORDER BY created_at, id",
        (url, ReviewItem.COMMENT),
    )
    sent = set(drafts.sent_by_pr(conn).get(url, {}).get("comments", []))
    by_thread: dict[str, list[records.ObservedReview]] = {}
    for c in comments:
        if c.thread_id is not None:
            by_thread.setdefault(c.thread_id, []).append(c)
    placed = {c.id: c.thread_id for c in comments}
    answering: dict[str, list[Draft]] = {}
    unplaced: list[Draft] = []
    for d in found:
        if d.kind is not DraftKind.THREAD:
            continue
        where = d.thread_id or placed.get(d.comment_id or 0)
        if where is not None and where in by_thread:
            answering.setdefault(where, []).append(views[d.id])
        else:
            unplaced.append(views[d.id])
    listed = [_thread(tid, cs, answering.get(tid, []), sent, diff) for tid, cs in by_thread.items()]
    listed.sort(key=lambda t: (t.file if t.file is not None else len(listed), t.path or "", t.line or 0))
    return PullRequestThreads(
        url=url,
        review_replies=ctx.config.trust.review_replies.value,
        read_at=db.parse_time(observed.observed_at) if observed is not None else None,
        head_sha=observed.head_sha if observed is not None else None,
        diff_run=kept[0] if kept is not None and diff is not None else None,
        diff_head=review_diff.read_head(kept[1]) if kept is not None and diff is not None else None,
        diff=diff_view(diff) if diff is not None else None,
        threads=listed,
        pr_drafts=[views[d.id] for d in found if d.kind is DraftKind.PR],
        unplaced=unplaced,
    )


def known(conn: sqlite3.Connection, url: str) -> bool:
    """Whether canopy's reader has read the PR or a run drafted for it: whether `threads` has anything to show.

    Returns:
        True when the journal holds a read of the PR or a draft for it.
    """
    found = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM observed_prs WHERE url = ?) OR EXISTS (SELECT 1 FROM drafts WHERE pr_url = ?)",
        (url, url),
    ).fetchone()
    return bool(found[0])


def sent(conn: sqlite3.Connection, outcome: drafts_manage.Sent) -> DraftsSent:
    """What a send did, as the API sends it.

    Returns:
        The drafts posted now, before, failed, and unconfirmed, each as it now stands.
    """

    def now(found: Iterable[records.Draft]) -> list[Draft]:
        return [draft(conn, d) for d in (drafts.get(conn, f.id) for f in found) if d is not None]

    failed = [
        DraftFailure(draft=draft(conn, d), why=why)
        for f, why in outcome.failed
        if (d := drafts.get(conn, f.id)) is not None
    ]
    return DraftsSent(
        posted=now(outcome.posted), already=now(outcome.already), failed=failed, unconfirmed=now(outcome.unconfirmed)
    )


def _kept_diff(conn: sqlite3.Connection, url: str) -> tuple[int, Path] | None:
    """The latest run of the PR's unit that kept a diff, and where it is.

    Returns:
        The run's id and its diff's path, or None when no run kept one.
    """
    unit = conn.execute("SELECT ticket_key, repo FROM ticket_units WHERE pr_url = ?", (url,)).fetchone()
    if unit is None:
        return None
    rows = conn.execute(
        "SELECT r.id, r.log_path FROM runs r JOIN run_slots s ON s.run_id = r.id "
        "WHERE r.ticket_key = ? AND s.repo = ? ORDER BY r.id DESC LIMIT 20",
        (unit["ticket_key"], unit["repo"]),
    )
    for r in rows:
        path = review_diff.run_path_for(str(r["log_path"]), str(unit["repo"]))
        if path.is_file():
            return int(r["id"]), path
    return None


def _side(value: str | None) -> Literal["left", "right"] | None:
    if value == "left":
        return "left"
    if value == "right":
        return "right"
    return None


def _thread(
    thread_id: str,
    comments: Sequence[records.ObservedReview],
    answering: Sequence[Draft],
    sent: AbstractSet[int],
    diff: review_diff.Diff | None,
) -> Thread:
    first = comments[0]
    file, line = None, None
    if diff is not None and first.path is not None:
        located = f"{first.path}:{first.line}" if first.line is not None and first.side != "left" else first.path
        file, line = review_diff.anchor(diff, located)
    return Thread(
        id=thread_id,
        path=first.path,
        line=first.line,
        side=_side(first.side),
        outdated=bool(first.outdated),
        resolved=bool(first.resolved),
        file=file,
        diff_line=None if first.outdated else line,
        comments=[
            ThreadComment(
                id=c.id,
                author=c.author,
                bot=c.bot,
                created_at=c.created_at,
                body=c.body,
                url=c.url,
                operator_sent=c.id in sent,
            )
            for c in comments
        ],
        drafts=list(answering),
    )
