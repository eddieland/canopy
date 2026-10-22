"""A review's draft as the API sends it (DESIGN §34): its newest version, exactly what would post, and its history.

Its text is the reviewer's, written from the PR's, until the operator publishes it: sent as the journal holds it, for
the UI to show as plain text, every hidden character named. Reads only; the operator's verbs on it are
`canopy.core.review_drafts_manage`'s, through `api/reviews.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from canopy.core import db, records, review_diff, review_drafts, review_result, sql
from canopy.serve.review_schema import (
    ReviewDraft,
    ReviewDraftAuthorName,
    ReviewDraftComment,
    ReviewDraftStatusName,
    ReviewDraftVersion,
)

if TYPE_CHECKING:
    import sqlite3


def of_review(conn: sqlite3.Connection, run: records.ReviewRun, diff: review_diff.Diff | None) -> ReviewDraft | None:
    """Review run `run`'s draft, its comments placed on `diff`, the diff it kept; None when it has none.

    Returns:
        The draft, or None.
    """
    found = review_drafts.of_review(conn, run.id)
    return view(conn, found, run, diff) if found is not None else None


def view(
    conn: sqlite3.Connection,
    found: records.ReviewDraft,
    run: records.ReviewRun,
    diff: review_diff.Diff | None,
) -> ReviewDraft:
    """A draft as the API sends it, at its newest version, its comments placed on `diff`, its review run `run`.

    Returns:
        The draft.
    """
    current = review_drafts.newest(conn, found.id)
    stored = review_result.stored(run.result_json)
    pr = records.fetch_one(
        conn,
        records.ObservedPr,
        sql.select("*").from_("observed_prs").where("url = ?", found.pr_url),
    )
    return ReviewDraft(
        status=cast("ReviewDraftStatusName", found.status.value),
        why=found.why,
        version=current.number,
        hash=current.hash,
        author=cast("ReviewDraftAuthorName", current.author.value),
        channel=current.channel,
        change=current.change,
        refused=list(current.refused),
        body=current.body,
        comments=[_comment(n, c, diff) for n, c in enumerate(current.comments, 1)],
        max_comments=review_drafts.MAX_COMMENTS,
        in_body=review_drafts.in_body(current.body, stored.findings) if stored is not None else [],
        versions=[
            ReviewDraftVersion(
                number=v.number,
                hash=v.hash,
                author=cast("ReviewDraftAuthorName", v.author.value),
                channel=v.channel,
                change=v.change,
                created_at=db.parse_time(v.created_at),
            )
            for v in review_drafts.versions(conn, found.id)
        ],
        pr_author=pr.author if pr is not None else None,
        moved_head=_moved_head(pr, found),
        published_at=db.parse_time(found.published_at) if found.published_at else None,
        published_url=found.published_url,
    )


def _comment(number: int, comment: review_drafts.Comment, diff: review_diff.Diff | None) -> ReviewDraftComment:
    file, line = review_diff.anchor(diff, f"{comment.path}:{comment.line}") if diff is not None else (None, None)
    return ReviewDraftComment(
        number=number,
        path=comment.path,
        line=comment.line,
        text=comment.text,
        finding=comment.finding,
        file=file,
        diff_line=line,
    )


def _moved_head(pr: records.ObservedPr | None, draft: records.ReviewDraft) -> str | None:
    """The PR's head as canopy last read it, `pr`, when that is past the commit the draft's review read.

    Returns:
        The head, or None when canopy has not read the PR or its head is that commit.
    """
    if pr is None or not pr.head_sha or draft.sha.startswith(pr.head_sha):
        return None
    return pr.head_sha
