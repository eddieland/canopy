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

from canopy.core import db, drafts, drafts_manage, records, review_diff, sql
from canopy.core.vocab import DraftKind, ReviewItem
from canopy.serve.draft_views import draft
from canopy.serve.feedback_plan_views import for_pr
from canopy.serve.reviews import diff_view
from canopy.serve.schema.draft import Draft, DraftFailure, DraftsSent, PullRequestThreads, Thread, ThreadComment

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.context import Context


def threads(ctx: Context, url: str) -> PullRequestThreads | None:
    """The PR's threads on its latest kept diff, with every draft for it, or None when the journal knows neither.

    Returns:
        The threads, the PR's own comment's drafts, the drafts no read has placed on a thread, and the current feedback
        plan of the PR's ticket, each of its items naming the thread it is.
    """
    conn = ctx.conn
    observed = records.fetch_one(conn, records.ObservedPr, sql.select("*").from_("observed_prs").where("url = ?", url))
    found = records.fetch_all(
        conn,
        records.Draft,
        sql.select("*").from_("drafts").where("pr_url = ?", url).order_by("run_id, number"),
    )
    if observed is None and not found:
        return None
    views = {d.id: draft(conn, d) for d in found}
    kept = _kept_diff(conn, url)
    diff = review_diff.read(kept[1]) if kept is not None else None
    comments = records.fetch_all(
        conn,
        records.ObservedReview,
        sql.select("*")
        .from_("observed_reviews")
        .where("pr_url = ?", url)
        .where("item = ?", ReviewItem.COMMENT)
        .order_by("created_at, id"),
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
        feedback_plan=for_pr(ctx, url, {i: t for i, t in placed.items() if t is not None}),
    )


def known(conn: sqlite3.Connection, url: str) -> bool:
    """Whether canopy's reader has read the PR or a run drafted for it: whether `threads` has anything to show.

    Returns:
        True when the journal holds a read of the PR or a draft for it.
    """
    read = sql.select("1").from_("observed_prs").where("url = ?", url)
    drafted = sql.select("1").from_("drafts").where("pr_url = ?", url)
    found = sql.execute(conn, sql.select("EXISTS ({}) OR EXISTS ({})", read, drafted)).fetchone()
    return bool(found[0])


def sent(conn: sqlite3.Connection, outcome: drafts_manage.Sent) -> DraftsSent:
    """What a send or a stage did, as the API sends it.

    Returns:
        The drafts posted now, before, failed, unconfirmed, and staged, each as it now stands.
    """

    def now(found: Iterable[records.Draft]) -> list[Draft]:
        return [draft(conn, d) for d in (drafts.get(conn, f.id) for f in found) if d is not None]

    failed = [
        DraftFailure(draft=draft(conn, d), why=why)
        for f, why in outcome.failed
        if (d := drafts.get(conn, f.id)) is not None
    ]
    return DraftsSent(
        posted=now(outcome.posted),
        already=now(outcome.already),
        failed=failed,
        unconfirmed=now(outcome.unconfirmed),
        staged=now(outcome.staged),
    )


def _kept_diff(conn: sqlite3.Connection, url: str) -> tuple[int, Path] | None:
    """The latest run of the PR's unit that kept a diff, and where it is.

    Returns:
        The run's id and its diff's path, or None when no run kept one.
    """
    unit = sql.execute(conn, sql.select("ticket_key, repo").from_("ticket_units").where("pr_url = ?", url)).fetchone()
    if unit is None:
        return None
    rows = sql.execute(
        conn,
        sql.select("r.id, r.log_path")
        .from_("runs r")
        .join("run_slots s ON s.run_id = r.id")
        .where("r.ticket_key = ?", unit["ticket_key"])
        .where("s.repo = ?", unit["repo"])
        .order_by("r.id DESC")
        .limit(20),
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
