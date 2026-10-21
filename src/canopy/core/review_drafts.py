"""A review's draft (DESIGN §34): a `done` review of a PR the loop does not own, as the comment review it would post.

A review of someone else's PR, a `review.query` match or the operator's request, is the first version of a draft of a
review on that PR, which the operator may edit, and publish in their own name (`review_drafts_manage`). A review that
names a ticket, or of a PR a ticket's unit holds, has none: the loop's own PRs keep §21's send.

A version is exactly what would post: a body, and comments, each on a line of the diff the review kept (`review_diff`),
on the commit's side. canopy makes the first from the review's summary and findings, a comment for each finding at its
`path:line`; a finding whose location is on no such line goes into the body under its location as the version is
made, so canopy composes nothing when it publishes. Each text is held to a draft's bounds (DESIGN §29) and refused
alone, recorded on the version, never cut or cleaned. Dismissing a finding drops what it made, and taking the
dismissal back restores it, each a new version.

A version's words are the reviewer's until the operator publishes them, written from the PR's text: untrusted.

It is core, since `_review` makes the draft, and the operator's verbs, `dismiss` among them, change it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import db, records, review_diff, review_result, sql
from canopy.core.memory_text import TextRefused, check_text
from canopy.core.replies import MAX_DRAFT_CHARS, MAX_DRAFTS
from canopy.core.vocab import ReviewDraftAuthor, ReviewDraftStatus, ReviewRunStatus

if TYPE_CHECKING:
    import sqlite3

#: How many comments one version may carry: as many as one run's drafts, which one review canopy posts on a PR already
#: holds (DESIGN §29), and more than a review reports findings, so the reviewer's first version always fits. A comment
#: past it is refused, never cut.
MAX_COMMENTS = MAX_DRAFTS
#: How many hex characters of a version's SHA-256 name it, as a draft's text is named (`drafts_manage.HASH_CHARS`).
HASH_CHARS = 12
#: The purpose of a review of one of the loop's own PRs (DESIGN §21), which has no draft.
OWN = "own"
_DRAFTS = sql.select("*").from_("review_drafts")


@dataclass(frozen=True)
class Comment:
    """One comment of a version: the line of the kept diff it is on, its text, and the finding it was made from."""

    path: str
    #: The line in the commit's file, on the diff's new side.
    line: int
    text: str
    #: The review's finding it was made from, by number, so a dismissal drops it; None for the operator's own.
    finding: int | None = None

    def posted(self) -> dict[str, str | int]:
        """Return the comment as it posts, and as its version's hash names it: where it is, and its text."""
        return {"path": self.path, "line": self.line, "text": self.text}


@dataclass(frozen=True)
class Version:
    """One version of a review's draft: exactly what would post, who made it, and what it changed."""

    draft_id: int
    number: int
    body: str
    comments: Sequence[Comment]
    author: ReviewDraftAuthor
    channel: str | None
    #: What made it, in the harness's words.
    change: str
    #: What canopy left out as it made it, and why, in the harness's words.
    refused: Sequence[str]
    created_at: str

    @property
    def hash(self) -> str:
        """The name the operator publishes it by: its body's and its comments' hash."""
        return hash_of(self.body, self.comments)


def hash_of(body: str, comments: Iterable[Comment]) -> str:
    """Return the name of what a version would post: the start of the SHA-256 of its body and its comments, in order.

    Returns:
        The hash, hex.
    """
    words = json.dumps(
        {"body": body, "comments": [c.posted() for c in comments]}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(words.encode()).hexdigest()[:HASH_CHARS]


def make(conn: sqlite3.Connection, run_id: int) -> records.ReviewDraft | None:
    """Make review run `run_id`'s draft, if it may have one and has none yet: its first version is the review's.

    `_review` calls it once its run is closed; the operator's verbs, for a review that ended before drafts were kept.

    Returns:
        The draft, or None when the run has none: not `done`, without a result, or of a PR the loop owns.
    """
    with db.transaction(conn):
        return _make(conn, run_id)


def draftable(conn: sqlite3.Connection, run: records.ReviewRun) -> bool:
    """Whether review run `run` may have a draft: a review of a PR the loop does not own (DESIGN §34).

    Returns:
        False for a review that names a ticket, or of a PR a ticket's unit holds now; True otherwise.
    """
    if run.purpose == OWN or run.ticket_key is not None:
        return False
    held = sql.select("1").from_("ticket_units").where("pr_url = ?", run.pr_url).limit(1)
    return sql.execute(conn, held).fetchone() is None


def of_review(conn: sqlite3.Connection, run_id: int) -> records.ReviewDraft | None:
    """Return review run `run_id`'s draft, or None."""
    return records.fetch_one(conn, records.ReviewDraft, _DRAFTS.where("review_run_id = ?", run_id))


def get(conn: sqlite3.Connection, draft_id: int) -> records.ReviewDraft | None:
    """Return draft `draft_id`, or None."""
    return records.fetch_one(conn, records.ReviewDraft, _DRAFTS.where("id = ?", draft_id))


def newest(conn: sqlite3.Connection, draft_id: int) -> Version:
    """Return draft `draft_id`'s newest version: what it would post now.

    Returns:
        The version.

    Raises:
        LookupError: The draft has no version, which `make` never leaves.
    """
    found = records.fetch_one(
        conn,
        records.ReviewDraftVersion,
        sql.select("*")
        .from_("review_draft_versions")
        .where("draft_id = ?", draft_id)
        .order_by("version DESC")
        .limit(1),
    )
    if found is None:
        raise LookupError(f"review draft {draft_id} has no version")
    return _version(found)


def versions(conn: sqlite3.Connection, draft_id: int) -> list[Version]:
    """Return every version of draft `draft_id`, oldest first.

    Returns:
        The versions.
    """
    return [
        _version(v)
        for v in records.fetch_all(
            conn,
            records.ReviewDraftVersion,
            sql.select("*").from_("review_draft_versions").where("draft_id = ?", draft_id).order_by("version"),
        )
    ]


def add_version(
    conn: sqlite3.Connection,
    draft: records.ReviewDraft,
    body: str,
    comments: Sequence[Comment],
    *,
    author: ReviewDraftAuthor,
    channel: str | None,
    change: str,
    refused: Sequence[str] = (),
) -> Version:
    """Record `body` and `comments` as the draft's newest version. Call inside a transaction.

    Returns:
        The version recorded.
    """
    number = newest(conn, draft.id).number + 1
    _insert_version(
        conn, draft.id, number, body, comments, author=author, channel=channel, change=change, refused=refused
    )
    return newest(conn, draft.id)


def diff_of(run: records.ReviewRun) -> review_diff.Diff | None:
    """Return the diff review run `run` kept, which a draft's comments sit on, or None once it is gone.

    Returns:
        The parsed diff, or None when the review kept none, or garbage collection deleted it (DESIGN §26).
    """
    return review_diff.read(review_diff.path_for(run.log_path))


def spot(diff: review_diff.Diff | None, location: str) -> tuple[str, int] | None:
    """Where a `path:line` falls on the diff's new side, if it names a line the diff shows.

    Returns:
        The file's path in the diff and the line, or None.
    """
    if diff is None or not location.strip():
        return None
    index, line = review_diff.anchor(diff, location)
    return None if index is None or line is None else (diff.files[index].path, line)


def checked(text: object) -> str:
    """Return a version's text, held to a draft's bounds (DESIGN §29): never cut or cleaned.

    Returns:
        The text, trimmed.

    Raises:
        TextRefused: canopy would not keep it as a draft's text, for the reason it says.
    """
    return check_text(text, MAX_DRAFT_CHARS, lines=True)


def dismissed(
    conn: sqlite3.Connection, run_id: int, numbers: Collection[int], *, undo: bool, channel: str
) -> Version | None:
    """Drop what review run `run_id`'s findings `numbers`, just dismissed, made of its draft, or with `undo` restore it.

    One control rather than two (DESIGN §34): a new version without the finding's comment, or its part of the body, or
    with them back. Call inside the transaction that records the dismissals. A draft the operator published, or is
    publishing, is not changed; nor one whose text no longer holds what the finding made, which is theirs to edit.

    Returns:
        The new version, or None when nothing changed.
    """
    draft = of_review(conn, run_id)
    if draft is None:
        # A review from before drafts were kept: its first version is made with the dismissals already in it.
        _make(conn, run_id)
        return None
    run = db.get_review_run(conn, run_id)
    stored = review_result.stored(run.result_json) if run is not None else None
    if run is None or stored is None or draft.status is not ReviewDraftStatus.WAITING:
        return None
    current = newest(conn, draft.id)
    body, comments, changed = current.body, list(current.comments), list[int]()
    diff = diff_of(run)
    for number in sorted(n for n in set(numbers) if 0 < n <= len(stored.findings)):
        toggled = _toggled(body, comments, number, stored.findings[number - 1], diff, undo=undo)
        if toggled is not None:
            body, comments = toggled
            changed.append(number)
    if not changed:
        return None
    named = ", ".join(map(str, changed))
    change = f"took back the dismissal of finding {named}" if undo else f"dismissed finding {named}"
    return add_version(conn, draft, body, comments, author=ReviewDraftAuthor.OPERATOR, channel=channel, change=change)


def _toggled(
    body: str,
    comments: Sequence[Comment],
    number: int,
    finding: review_result.Finding,
    diff: review_diff.Diff | None,
    *,
    undo: bool,
) -> tuple[str, list[Comment]] | None:
    """A version's body and comments without what finding `number` made, or with `undo`, with it back.

    Returns:
        The body and the comments, or None when the version does not hold what the finding made, or with `undo`
        already does, or cannot take it back.
    """
    held = any(c.finding == number for c in comments)
    in_body = _held(body, _block(finding))
    if undo:
        if held or in_body:
            return None
        left_out: list[str] = []
        placed = _placed(body, comments, number, finding, diff=diff, refused=left_out)
        return None if left_out else placed
    if held:
        return body, [c for c in comments if c.finding != number]
    return (_without(body, _block(finding)), list(comments)) if in_body else None


def _make(conn: sqlite3.Connection, run_id: int) -> records.ReviewDraft | None:
    found = of_review(conn, run_id)
    if found is not None:
        return found
    run = db.get_review_run(conn, run_id)
    if run is None or run.status is not ReviewRunStatus.DONE or not draftable(conn, run):
        return None
    stored = review_result.stored(run.result_json)
    if stored is None:
        return None
    cursor = sql.execute(
        conn,
        sql.insert(
            "review_drafts",
            review_run_id=run.id,
            pr_url=run.pr_url,
            sha=run.sha,
            status=ReviewDraftStatus.WAITING,
            created_at=db.now(),
        ),
    )
    draft_id = int(cursor.lastrowid or 0)
    body, comments, refused = _first(stored, db.review_dismissals(conn, run.id), diff_of(run))
    change = f"made from review run {run.id}'s summary and findings"
    _insert_version(
        conn,
        draft_id,
        1,
        body,
        comments,
        author=ReviewDraftAuthor.REVIEWER,
        channel=None,
        change=change,
        refused=refused,
    )
    return get(conn, draft_id)


def _first(
    stored: review_result.ReviewResult, dismissed: Collection[int], diff: review_diff.Diff | None
) -> tuple[str, list[Comment], list[str]]:
    """The first version of a review's draft: its summary as the body, and a comment for each finding kept.

    Returns:
        The body, the comments, and what was left out, and why.
    """
    refused: list[str] = []
    body = ""
    if stored.summary.strip():
        try:
            body = checked(stored.summary)
        except TextRefused as e:
            refused.append(f"the summary: {e}")
    comments: list[Comment] = []
    for number, finding in enumerate(stored.findings, 1):
        if number not in dismissed:
            body, comments = _placed(body, comments, number, finding, diff=diff, refused=refused)
    return body, comments, refused


def _placed(
    body: str,
    comments: Sequence[Comment],
    number: int,
    finding: review_result.Finding,
    *,
    diff: review_diff.Diff | None,
    refused: list[str],
) -> tuple[str, list[Comment]]:
    """Put finding `number` in a version: a comment on its line, or, off the diff or past the bound, in the body.

    A text canopy would not keep is left out, and `refused` says why.

    Returns:
        The body and the comments with it.
    """
    at = spot(diff, finding.location)
    try:
        if at is not None and len(comments) < MAX_COMMENTS:
            return body, [*comments, Comment(at[0], at[1], checked(_text(finding)), number)]
        block = checked(_block(finding))
        return checked(f"{body}\n\n{block}" if body else block), list(comments)
    except TextRefused as e:
        refused.append(f"finding {number}: {e}")
        return body, list(comments)


def _text(finding: review_result.Finding) -> str:
    """A finding as a comment on its line says it: its severity, its title, and its detail.

    Returns:
        The text.
    """
    head = f"**{finding.severity}**: {finding.title}"
    return f"{head}\n\n{finding.detail.strip()}" if finding.detail.strip() else head


def _block(finding: review_result.Finding) -> str:
    """A finding as the body says it, under its location, where no line of the diff takes it.

    Returns:
        The text, trimmed as a checked text is.
    """
    at = f" at `{finding.location.strip()}`" if finding.location.strip() else ""
    head = f"**{finding.severity}**{at}: {finding.title}"
    return (f"{head}\n\n{finding.detail.strip()}" if finding.detail.strip() else head).strip()


def _held(body: str, block: str) -> bool:
    return body == block or body.startswith(f"{block}\n\n") or f"\n\n{block}" in body


def _without(body: str, block: str) -> str:
    if body == block:
        return ""
    if f"\n\n{block}" in body:
        return body.replace(f"\n\n{block}", "", 1).strip()
    return body.removeprefix(f"{block}\n\n").strip()


def _insert_version(
    conn: sqlite3.Connection,
    draft_id: int,
    number: int,
    body: str,
    comments: Sequence[Comment],
    *,
    author: ReviewDraftAuthor,
    channel: str | None,
    change: str,
    refused: Sequence[str],
) -> None:
    stored = [{**c.posted(), **({"finding": c.finding} if c.finding is not None else {})} for c in comments]
    sql.execute(
        conn,
        sql.insert(
            "review_draft_versions",
            draft_id=draft_id,
            version=number,
            body=body,
            comments=json.dumps(stored),
            author=author,
            channel=channel,
            change=change,
            refused=json.dumps(list(refused)),
            created_at=db.now(),
        ),
    )


def _version(row: records.ReviewDraftVersion) -> Version:
    raw: object = json.loads(row.comments)
    comments = [
        Comment(
            path=str(c["path"]),
            line=int(c["line"]),
            text=str(c["text"]),
            finding=int(c["finding"]) if isinstance(c.get("finding"), int) else None,
        )
        for c in (raw if isinstance(raw, list) else [])
        if isinstance(c, dict)
    ]
    left: object = json.loads(row.refused)
    return Version(
        draft_id=row.draft_id,
        number=row.version,
        body=row.body,
        comments=comments,
        author=row.author,
        channel=row.channel,
        change=row.change,
        refused=[str(r) for r in left] if isinstance(left, list) else [],
        created_at=row.created_at,
    )
