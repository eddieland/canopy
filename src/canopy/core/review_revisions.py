"""Revising a review's draft with an agent (DESIGN §34): the operator's notes, a draft's limit, and its versions.

A note on a draft, the operator's reply on its review, asks for a revision while it is newer than the draft's newest
version: a version made since, by a revision or by the operator, answers it. A revision is a review run at the commit
the review read (`reviews/revise.py` starts it), counted against its draft's limit, `policy.max_revisions_per_draft`
plus the operator's grants, never reset (D030).

A revision's result is a new version, placed as the reviewer's findings are (`review_drafts`): a comment on a line of
the diff the review kept, or, off it or past the bound, in the body under its location, each text held to a draft's
bounds and refused alone. A revision of a version the draft has since moved on from, or of a draft no longer waiting,
makes none: what the operator did meanwhile stands.

It is core, since the operator's verbs check a draft's limit and the overseer's state block lists what notes ask for,
and `_review` makes the version.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import db, records, review_diff, review_drafts, review_runs, sql
from canopy.core.memory_text import TextRefused
from canopy.core.review_drafts import Comment, Version
from canopy.core.vocab import ReviewDraftAuthor, ReviewDraftStatus, ReviewRunStatus

if TYPE_CHECKING:
    import sqlite3

    from canopy.core.config import Config
    from canopy.core.review_result import RevisionResult

#: The KIND `canopy grant review:ID` takes: more revisions of the review's draft.
KIND = "revision"
#: A waiting draft with a note no version has answered: one whose note was written at its newest version.
_WANTED = (
    sql.select("d.*")
    .from_("review_drafts d")
    .where("d.status = ?", ReviewDraftStatus.WAITING)
    .where(
        "EXISTS (SELECT 1 FROM review_draft_notes n WHERE n.draft_id = d.id AND n.after_version >= "
        "(SELECT max(v.version) FROM review_draft_versions v WHERE v.draft_id = d.id))",
    )
)


@dataclass(frozen=True)
class Wanted:
    """A review's draft the operator's notes ask a revision of, and what the overseer is told of it."""

    draft: records.ReviewDraft
    #: The review whose draft it is.
    review: records.ReviewRun
    #: The notes no version has answered, oldest first.
    notes: Sequence[records.ReviewDraftNote]
    #: Its revisions so far, however they ended, newest first.
    revisions: Sequence[records.ReviewRun]
    #: How many revisions it may have: the policy's limit plus the operator's grants.
    limit: int


def wanted(conn: sqlite3.Connection, config: Config) -> list[Wanted]:
    """Return each draft the operator's notes ask a revision of, oldest first.

    Returns:
        Each waiting draft with a note newer than its newest version, with its review, notes, revisions, and limit.
    """
    found: list[Wanted] = []
    for draft in records.fetch_all(conn, records.ReviewDraft, _WANTED.order_by("d.id")):
        review = review_runs.get_review_run(conn, draft.review_run_id)
        if review is None:
            continue
        found.append(
            Wanted(
                draft=draft,
                review=review,
                notes=pending(conn, draft.id),
                revisions=review_runs.revision_runs_of(conn, draft.id),
                limit=limit(conn, config, draft.id),
            ),
        )
    return found


def on(conn: sqlite3.Connection, config: Config) -> bool:
    """Whether a revision may start at all: `max_reviews` above 0, and a note asking one of some draft.

    A note authorizes a revision of its draft, and nothing else: it turns on no review of any PR (DESIGN §21).

    Returns:
        True when review capacity is above 0 and some waiting draft has a note newer than its newest version.
    """
    if config.capacity.max_reviews <= 0:
        return False
    return sql.execute(conn, sql.select("1").from_("({}) w", _WANTED).limit(1)).fetchone() is not None


def pending(conn: sqlite3.Connection, draft_id: int) -> list[records.ReviewDraftNote]:
    """Return the notes on draft `draft_id` no version has answered: written at its newest version, oldest first.

    Returns:
        The notes, none when a version was made since the last.
    """
    return notes_since(conn, draft_id, review_drafts.newest(conn, draft_id).number)


def notes_since(conn: sqlite3.Connection, draft_id: int, version: int) -> list[records.ReviewDraftNote]:
    """Return the notes on draft `draft_id` written at version `version` or later, oldest first.

    Returns:
        The notes.
    """
    query = (
        records.select(records.ReviewDraftNote)
        .where("draft_id = ? AND after_version >= ?", draft_id, version)
        .order_by("id")
    )
    return query.all(conn)


def limit(conn: sqlite3.Connection, config: Config, draft_id: int) -> int:
    """Return the most revisions draft `draft_id` may have: the policy's limit plus the revisions granted it."""
    return config.policy.max_revisions_per_draft + granted(conn, draft_id)


def granted(conn: sqlite3.Connection, draft_id: int) -> int:
    """Return the revisions the operator granted draft `draft_id` past the policy's limit, 0 for none."""
    query = sql.select("coalesce(sum(runs), 0)").from_("review_draft_grants").where("draft_id = ?", draft_id)
    return int(sql.execute(conn, query).fetchone()[0])


def hint(review_run_id: int) -> str:
    """Return what a draft at its limit tells the operator they can do about it."""
    return f"allow it another revision with `canopy grant review:{review_run_id} revision`"


def running(conn: sqlite3.Connection, draft_id: int) -> records.ReviewRun | None:
    """Return draft `draft_id`'s revision still running, or None."""
    return next((r for r in review_runs.revision_runs_of(conn, draft_id) if r.status is ReviewRunStatus.RUNNING), None)


def add_note(conn: sqlite3.Connection, draft_id: int, body: str, *, channel: str) -> records.ReviewDraftNote:
    """Record the operator's note `body` on draft `draft_id`, at its newest version. Call inside a transaction.

    Returns:
        The note recorded.

    Raises:
        LookupError: The note is not there once inserted, which a transaction never leaves.
    """
    at = review_drafts.newest(conn, draft_id).number
    note = records.insert(
        records.ReviewDraftNote,
        draft_id=draft_id,
        after_version=at,
        body=body,
        channel=channel,
        created_at=db.now(),
    )
    note_id = int(note.run(conn).lastrowid or 0)
    found = records.select(records.ReviewDraftNote).where("id = ?", note_id).one(conn)
    if found is None:
        raise LookupError(f"review draft note {note_id} vanished")
    return found


def add_grant(conn: sqlite3.Connection, draft_id: int, runs: int) -> None:
    """Record that the operator granted draft `draft_id` `runs` more revisions. Call inside a transaction."""
    records.insert(records.ReviewDraftGrant, draft_id=draft_id, runs=runs, granted_at=db.now()).run(conn)


@dataclass(frozen=True)
class Revised:
    """What a revision's result made: the new version, or why it made none, in the harness's words."""

    version: Version | None
    why: str = ""


def revised(conn: sqlite3.Connection, run: records.ReviewRun, result: RevisionResult) -> Revised:
    """Make revision run `run`'s `done` result the newest version of its draft, if the draft still waits on it.

    Returns:
        The version made; or none, and why: the draft is gone, no longer waiting, or moved on from what it read.
    """
    if run.revises is None or run.revises_version is None:
        return Revised(None, f"review run {run.id} revises no draft")
    with db.transaction(conn):
        draft = review_drafts.get(conn, run.revises)
        if draft is None:
            return Revised(None, f"review draft {run.revises} is gone")
        if draft.status is not ReviewDraftStatus.WAITING:
            return Revised(None, f"the draft is {draft.status} now; this revision's version was left out")
        current = review_drafts.newest(conn, draft.id)
        if current.number != run.revises_version:
            return Revised(
                None,
                f"the draft moved on to version {current.number} while this revision of version "
                f"{run.revises_version} ran; its version was left out",
            )
        review = review_runs.get_review_run(conn, draft.review_run_id)
        diff = review_drafts.diff_of(review) if review is not None else None
        body, comments, refused = _placed(result, diff)
        change = f"revision run {run.id} revised version {current.number} on the operator's notes"
        version = review_drafts.add_version(
            conn,
            draft,
            body,
            comments,
            author=ReviewDraftAuthor.REVISER,
            channel=None,
            change=change,
            refused=refused,
        )
    return Revised(version)


def _placed(result: RevisionResult, diff: review_diff.Diff | None) -> tuple[str, list[Comment], list[str]]:
    """A revision's body and comments as a version holds them: each comment on its line of the diff, if it has one.

    A comment whose location is on no line of the diff, or past the bound, goes in the body under its location. A text
    canopy would not keep is left out, and the third list says why.

    Returns:
        The body, the comments, and what was left out, and why.
    """
    refused: list[str] = []
    body = ""
    if result.body.strip():
        try:
            body = review_drafts.checked(result.body)
        except TextRefused as e:
            refused.append(f"the body: {e}")
    comments: list[Comment] = []
    for number, revised_comment in enumerate(result.comments, 1):
        at = review_drafts.spot(diff, revised_comment.location)
        try:
            if at is not None and len(comments) < review_drafts.MAX_COMMENTS:
                comments.append(Comment(at[0], at[1], review_drafts.checked(revised_comment.text)))
                continue
            where = revised_comment.location.strip()
            block = review_drafts.checked(f"At `{where}`: {revised_comment.text}" if where else revised_comment.text)
            body = review_drafts.checked(f"{body}\n\n{block}" if body else block)
        except TextRefused as e:
            refused.append(f"comment {number}: {e}")
    return body, comments, refused
