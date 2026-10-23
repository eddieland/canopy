"""The operator's verbs on a review's draft (DESIGN §34): editing, noting what to revise, publishing, and discarding.

Each refuses inside canopy's ticks and runs (`conversation.check_operator`): an agent that could publish could post as
the operator on any PR their query matches. The CLI's `canopy review` commands call these functions, and the web UI is
to call the same, so with the same guards.

Publishing names the version the operator last saw by its hash, and every check runs before anything posts. What
reaches GitHub is that version verbatim, unmarked, as one comment review on the commit the review read, through the
`vcs` source's `post_cmd`: it opens a pending review, adds every comment, and only then submits, so a comment GitHub
refuses posts nothing. A draft publishes one version, at most once: a publish claims the draft before it posts, and one
whose post ends without saying whether it submitted is `unconfirmed`, never posted again by canopy until a whole read
of its PR settles it. So is one whose publish stopped before the post said how it ended: at once when it raised, and
once its claim outlives the post command's timeout when the process holding it was killed (`expire_claims`).

A note asks for a revision (`review_revisions`): the next tick's overseer starts one while the note is newer than the
draft's newest version. Notes are the reviser's only instructions, so only the operator writes one, and a note past
the draft's revision limit, or while a revision runs, is refused; the operator grants a draft more revisions.

Staging is publishing without the submit: the version waits in a pending review for the operator to submit on GitHub,
and is `staged` until a whole read finds that review submitted, or gone.

Discarding is the operator's word that a waiting draft is seen and will not post: it is `discarded`, past every other
verb, and posts nothing.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, assert_never

from canopy.core import conversation, db, records, review_drafts, review_revisions, review_runs, sql
from canopy.core.config import notify_words
from canopy.core.memory_text import TextRefused
from canopy.core.review_drafts import Comment, Version
from canopy.core.vocab import DraftStatus, ReviewDraftAuthor, ReviewDraftStatus, ReviewItem, ReviewState
from canopy.infra import logs, procs

if TYPE_CHECKING:
    from canopy.core.config import Config, Source

#: How much of the poster's stderr a failure says: which comment GitHub refused, say.
_MAX_STDERR = 300
#: What the operator does with a review they staged, which a refusal for it says.
_FINISH = "submit or delete it on GitHub, and the next read of the PR settles it"

#: How long past its post command's timeout a publish may hold its draft before canopy takes the post as one that
#: ended without saying, as when the process posting it was killed.
CLAIM_MARGIN_MINUTES = 5

#: What an edit makes of the draft's newest version: its body and its comments.
type _Making = Callable[[Version], tuple[str, Sequence[Comment]]]


def find(conn: sqlite3.Connection, run_id: int) -> records.ReviewDraft:
    """Return review run `run_id`'s draft, made now for a `done` review that ended before drafts were kept.

    Returns:
        The draft.

    Raises:
        Refused: (`unknown`) there is no such review run; (`no_draft`) it has none: it did not end `done`, or it is of
            one of the loop's own PRs, whose findings go to a worker instead.
    """
    if review_runs.get_review_run(conn, run_id) is None:
        raise conversation.Refused("unknown", f"there is no review run {run_id}")
    found = review_drafts.of_review(conn, run_id) or review_drafts.make(conn, run_id)
    if found is None:
        raise conversation.Refused(
            "no_draft",
            f"review run {run_id} has no draft: only a `done` review of a PR the loop does not own drafts one",
        )
    return found


def edit_body(conn: sqlite3.Connection, run_id: int, text: str, *, channel: str) -> Version:
    """Make `text` the body of review run `run_id`'s draft, as a new version. Empty leaves the comments alone.

    Returns:
        The draft's newest version.

    Raises:
        Refused: (`inside_run`); (`unknown`); (`no_draft`); a status past edits, named for it; (`bad_text`).
    """
    conversation.check_operator()
    body = "" if not text.strip() else _checked(text)
    return _change(conn, run_id, channel, "edited the body", lambda v: (body, v.comments))


def edit_comment(conn: sqlite3.Connection, run_id: int, number: int, text: str, *, channel: str) -> Version:
    """Make `text` comment `number` of review run `run_id`'s draft, on the line it is on, as a new version.

    Returns:
        The draft's newest version.

    Raises:
        Refused: As `edit_body` does; (`unknown`) no such comment.
    """
    conversation.check_operator()
    words = _checked(text)

    def edited(v: Version) -> tuple[str, Sequence[Comment]]:
        old = _comment(v, number)
        return v.body, [Comment(c.path, c.line, words, c.finding) if c is old else c for c in v.comments]

    return _change(conn, run_id, channel, f"edited comment {number}", edited)


def drop_comment(conn: sqlite3.Connection, run_id: int, number: int, *, channel: str) -> Version:
    """Drop comment `number` of review run `run_id`'s draft, as a new version.

    Dropping a comment made from a finding leaves the finding as it is; dismissing it drops its comment too.

    Returns:
        The draft's newest version.

    Raises:
        Refused: As `edit_body` does; (`unknown`) no such comment.
    """
    conversation.check_operator()

    def dropped(v: Version) -> tuple[str, Sequence[Comment]]:
        old = _comment(v, number)
        return v.body, [c for c in v.comments if c is not old]

    return _change(conn, run_id, channel, f"dropped comment {number}", dropped)


def add_comment(conn: sqlite3.Connection, run_id: int, location: str, text: str, *, channel: str) -> Version:
    """Add a comment of `text` at `location`, `path:line` on a line of the diff the review kept, as a new version.

    Returns:
        The draft's newest version.

    Raises:
        Refused: As `edit_body` does; (`no_diff`) the review kept no diff, or it is gone; (`off_diff`) the diff shows no
            such line; (`too_many`) the draft holds `review_drafts.MAX_COMMENTS` comments.
    """
    conversation.check_operator()
    words = _checked(text)
    find(conn, run_id)
    run = review_runs.get_review_run(conn, run_id)
    diff = review_drafts.diff_of(run) if run is not None else None
    if diff is None:
        raise conversation.Refused("no_diff", f"review run {run_id} keeps no diff to put a comment on")
    at = review_drafts.spot(diff, location)
    if at is None:
        raise conversation.Refused("off_diff", f"{location!r} is on no line of the diff review run {run_id} read")

    def added(v: Version) -> tuple[str, Sequence[Comment]]:
        if len(v.comments) >= review_drafts.MAX_COMMENTS:
            raise conversation.Refused("too_many", f"a review holds at most {review_drafts.MAX_COMMENTS} comments")
        return v.body, [*v.comments, Comment(at[0], at[1], words)]

    return _change(conn, run_id, channel, f"added a comment on {at[0]}:{at[1]}", added)


def note(
    conn: sqlite3.Connection,
    config: Config,
    run_id: int,
    text: str,
    *,
    channel: str,
) -> records.ReviewDraftNote:
    """Record the operator's note on review run `run_id`'s draft: what a revision should change (DESIGN §34).

    The next tick's overseer starts a revision while the note is newer than the draft's newest version; a version made
    first, the operator's own edit among them, answers it. The note is the reviser's instruction, and the operator's
    alone.

    Returns:
        The note recorded.

    Raises:
        Refused: (`inside_run`); (`unknown`); (`no_draft`); (`not_ours`) a ticket's unit holds the PR now; a status past
            edits, named for it; (`bad_body`) empty or past the operator's bound; (`no_diff`) the diff the draft's
            comments sit on is gone; (`revising`) a revision of it runs; (`revision_limit`) it has had its revisions.
    """
    conversation.check_operator()
    words = text.strip()
    if not words:
        raise conversation.Refused("bad_body", "the note is empty")
    if len(words) > conversation.MAX_OPERATOR:
        raise conversation.Refused(
            "bad_body",
            f"the note is {len(words)} characters; the most is {conversation.MAX_OPERATOR}",
        )
    draft = find(conn, run_id)
    run = review_runs.get_review_run(conn, run_id)
    if run is None or not review_drafts.draftable(conn, run):
        raise conversation.Refused(
            "not_ours",
            f"{draft.pr_url} is one of the loop's own PRs now: it publishes no review",
        )
    if review_drafts.diff_of(run) is None:
        raise conversation.Refused(
            "no_diff",
            f"the diff review run {run_id} read is gone, so its draft is no longer publishable",
        )
    with db.transaction(conn):
        draft = review_drafts.get(conn, draft.id) or draft
        _check_open(draft)
        _check_not_revising(conn, draft)
        spent = len(review_runs.revision_runs_of(conn, draft.id))
        most = review_revisions.limit(conn, config, draft.id)
        if spent >= most:
            raise conversation.Refused(
                "revision_limit",
                f"review run {run_id}'s draft has had {spent} revisions and its limit is {most}; "
                f"{review_revisions.hint(run_id)}",
            )
        return review_revisions.add_note(conn, draft.id, words, channel=channel)


@dataclass(frozen=True)
class Granted:
    """What `grant_revisions` recorded: the draft's revisions, and its limit with the grant counted."""

    runs: int
    limit: int


def grant_revisions(conn: sqlite3.Connection, config: Config, run_id: int, *, runs: int) -> Granted:
    """Grant review run `run_id`'s draft `runs` more revisions than `policy.max_revisions_per_draft` allows.

    Every revision still counts (D030): a grant raises one draft's limit and resets nothing.

    Returns:
        The draft's revisions, and its limit for them with the grant counted.

    Raises:
        Refused: (`inside_run`); (`unknown`); (`no_draft`).
    """
    conversation.check_operator()
    draft = find(conn, run_id)
    # The limit is read in the grant's own write transaction, so it counts this grant and none committed after it.
    with db.transaction(conn):
        review_revisions.add_grant(conn, draft.id, runs)
        spent = len(review_runs.revision_runs_of(conn, draft.id))
        return Granted(runs=spent, limit=review_revisions.limit(conn, config, draft.id))


def discard(conn: sqlite3.Connection, run_id: int, *, channel: str) -> records.ReviewDraft:
    """Discard review run `run_id`'s draft: the operator has seen it and will not post it.

    It posts nothing, takes no edit, note, or publish from now on, and answers its PR's `review_waiting` item as a
    published draft does. A later commit's review is a new draft.

    Returns:
        The draft, discarded.

    Raises:
        Refused: (`inside_run`); (`unknown`); (`no_draft`); a status past edits, named for it; (`revising`) a revision
            of it runs.
    """
    conversation.check_operator()
    draft = find(conn, run_id)
    with db.transaction(conn):
        draft = review_drafts.get(conn, draft.id) or draft
        _check_open(draft)
        _check_not_revising(conn, draft)
        sql.execute(
            conn,
            sql.update("review_drafts")
            .set(status=ReviewDraftStatus.DISCARDED, why=f"discarded by you through {channel}")
            .where("id = ?", draft.id),
        )
    return _present(conn, draft)


def _checked(text: str) -> str:
    """The operator's text, held to the bounds the reviewer's is (DESIGN §34).

    Returns:
        The text, trimmed.

    Raises:
        Refused: (`bad_text`) canopy would not keep it, for the reason it says.
    """
    try:
        return review_drafts.checked(text)
    except TextRefused as e:
        raise conversation.Refused("bad_text", str(e)) from e


def _comment(version: Version, number: int) -> Comment:
    if not 0 < number <= len(version.comments):
        raise conversation.Refused("unknown", f"the draft has no comment {number}: it holds {len(version.comments)}")
    return version.comments[number - 1]


def _change(
    conn: sqlite3.Connection,
    run_id: int,
    channel: str,
    change: str,
    made: _Making,
) -> Version:
    """Record what `made` makes of the draft's newest version as the operator's, if it changes anything.

    Returns:
        The draft's newest version.

    Raises:
        Refused: (`unknown`); (`no_draft`); a status past edits, named for it; or what `made` raises.
    """
    draft = find(conn, run_id)
    with db.transaction(conn):
        draft = review_drafts.get(conn, draft.id) or draft
        _check_open(draft)
        current = review_drafts.newest(conn, draft.id)
        body, comments = made(current)
        if review_drafts.hash_of(body, comments) == current.hash:
            return current
        return review_drafts.add_version(
            conn,
            draft,
            body,
            comments,
            author=ReviewDraftAuthor.OPERATOR,
            channel=channel,
            change=change,
        )


def _check_open(draft: records.ReviewDraft) -> None:
    """Refuse to change a draft past edits: one publishing, published, staged, discarded, or of unknown outcome.

    Raises:
        Refused: Named for the draft's status.
    """
    if draft.status is not ReviewDraftStatus.WAITING:
        raise conversation.Refused(draft.status, f"review run {draft.review_run_id}'s draft is {draft.status}")


@dataclass(frozen=True)
class Published:
    """What a publish or a stage did: the draft as it now stands, and why nothing was posted, if nothing was."""

    draft: records.ReviewDraft
    #: The version it posted, or tried to.
    version: Version
    #: Why nothing was posted, in the harness's words with the poster's; None when it posted, staged, or may have.
    failed: str | None = None


def publish(
    conn: sqlite3.Connection,
    config: Config,
    runner: procs.Runner,
    run_id: int,
    seen: str,
    *,
    submit: bool,
    channel: str,
    log: logs.TickAdapter,
) -> Published:
    """Publish the version of review run `run_id`'s draft the operator last saw, named by `seen`, its hash.

    It posts as one comment review on the commit the review read, verbatim and unmarked, or with `submit` false stages
    it in a pending review for the operator to submit on GitHub. Every check runs before anything posts.

    Returns:
        The draft as it now stands: published, staged, unconfirmed, or waiting again with why nothing was posted.

    Raises:
        Refused: (`inside_run`); (`unknown`); (`no_draft`); (`not_ours`) a ticket's unit holds the PR now; a status that
            cannot publish, named for it: a draft publishes once; (`revising`) a revision of it runs; (`stale`) the
            version is not the newest; (`empty`)
            it would post nothing; (`no_diff`) the diff its comments sit on is gone; (`staged`) the PR holds a review
            the operator staged; (`no_post`) no command posts there.
    """
    conversation.check_operator()
    expire_claims(conn, config)
    draft = find(conn, run_id)
    run = review_runs.get_review_run(conn, run_id)
    if run is None or not review_drafts.draftable(conn, run):
        raise conversation.Refused(
            "not_ours",
            f"{draft.pr_url} is one of the loop's own PRs now: it publishes no review",
        )
    _check_publishable(draft)
    _check_not_revising(conn, draft)
    current = _check_seen(conn, draft, seen)
    if not current.body and not current.comments:
        raise conversation.Refused("empty", f"version {current.number} of review run {run_id}'s draft posts nothing")
    if review_drafts.diff_of(run) is None:
        raise conversation.Refused(
            "no_diff",
            f"the diff review run {run_id} read is gone, so its draft is no longer publishable",
        )
    check_none_staged(conn, draft.pr_url)
    source = config.connect.vcs()
    if not notify_words(source.post_cmd):
        raise conversation.Refused("no_post", f"no [connect.sources] post_cmd posts to {draft.pr_url}")
    version = _claim(conn, draft, seen, channel)
    return _post(conn, source, runner, draft=draft, version=version, submit=submit, log=log)


def _check_publishable(draft: records.ReviewDraft) -> None:
    """Refuse a draft with a version published, staged, of unknown outcome, or being posted: it publishes once.

    Raises:
        Refused: Named for its status.
    """
    where = f"review run {draft.review_run_id}'s draft"
    match draft.status:
        case ReviewDraftStatus.WAITING:
            pass
        case ReviewDraftStatus.PUBLISHED:
            raise conversation.Refused(
                "published",
                f"{where} is published already: {draft.published_url}; a later commit's review is a new one",
            )
        case ReviewDraftStatus.STAGED:
            raise conversation.Refused("staged", f"{where} is in the review you staged on {draft.pr_url}: {_FINISH}")
        case ReviewDraftStatus.UNCONFIRMED:
            raise conversation.Refused(
                "unconfirmed",
                f"{where} may have been posted already; the next whole read of {draft.pr_url} says",
            )
        case ReviewDraftStatus.PUBLISHING:
            raise conversation.Refused("publishing", f"{where} is being posted now")
        case ReviewDraftStatus.DISCARDED:
            raise conversation.Refused("discarded", f"{where} is discarded; a later commit's review is a new one")
        case _:
            assert_never(draft.status)


def _check_not_revising(conn: sqlite3.Connection, draft: records.ReviewDraft) -> None:
    """Refuse while a revision of the draft runs: its version may be the newest before the post ends.

    Raises:
        Refused: (`revising`) a revision of it is running.
    """
    revising = review_revisions.running(conn, draft.id)
    if revising is not None:
        raise conversation.Refused(
            "revising",
            f"review run {revising.id} is revising review run {draft.review_run_id}'s draft; wait for it to end",
        )


def _check_seen(conn: sqlite3.Connection, draft: records.ReviewDraft, seen: str) -> Version:
    """The draft's newest version, if it is the one the operator saw.

    Returns:
        The version.

    Raises:
        Refused: (`stale`) its hash is not `seen`: another version is the newest.
    """
    current = review_drafts.newest(conn, draft.id)
    if current.hash != seen:
        raise conversation.Refused(
            "stale",
            f"review run {draft.review_run_id}'s draft is version {current.number} now, hash {current.hash}; read it "
            "again before you publish",
        )
    return current


def check_none_staged(conn: sqlite3.Connection, pr: str) -> None:
    """Refuse to post on a PR that holds a review the operator staged: GitHub keeps one pending review a person.

    Raises:
        Refused: (`staged`), naming the PR.
    """
    staged = sql.union(
        sql.select("1").from_("drafts").where("pr_url = ?", pr).where("status = ?", DraftStatus.STAGED),
        sql.select("1").from_("review_drafts").where("pr_url = ?", pr).where("status = ?", ReviewDraftStatus.STAGED),
    )
    if sql.execute(conn, staged).fetchone():
        raise conversation.Refused("staged", f"{pr} holds a review you staged: {_FINISH}")


def _claim(conn: sqlite3.Connection, draft: records.ReviewDraft, seen: str, channel: str) -> Version:
    """Claim the draft for this publish, so two at once post it once, at the version the operator saw.

    Returns:
        The version claimed, which takes no edit until the post ends.

    Raises:
        Refused: (`stale`) another version is the newest now; the status it has now, when another publish claimed it.
    """
    with db.transaction(conn):
        version = _check_seen(conn, draft, seen)
        claimed = sql.execute(
            conn,
            sql.update("review_drafts")
            .set(
                status=ReviewDraftStatus.PUBLISHING,
                publish_version=version.number,
                publish_started_at=db.now(),
                publish_channel=channel,
                why=None,
            )
            .where("id = ?", draft.id)
            .where("status = ?", ReviewDraftStatus.WAITING),
        ).rowcount
        if not claimed:
            now = review_drafts.get(conn, draft.id)
            status = now.status if now is not None else "unknown"
            raise conversation.Refused(status, f"review run {draft.review_run_id}'s draft became {status} meanwhile")
    return version


def _post(
    conn: sqlite3.Connection,
    source: Source,
    runner: procs.Runner,
    *,
    draft: records.ReviewDraft,
    version: Version,
    submit: bool,
    log: logs.TickAdapter,
) -> Published:
    """Post `version` as one review on the draft's commit, or stage it, and record what became of it.

    Returns:
        What became of it.
    """
    request: dict[str, object] = {
        "pr": draft.pr_url,
        "commit": draft.sha,
        "delete_pending": draft.pending_review,
        "body": version.body or None,
        "comments": [c.posted() for c in version.comments],
    }
    if not submit:
        request["submit"] = False
    try:
        result = runner.run(
            notify_words(source.post_cmd),
            stdin=json.dumps(request),
            timeout=source.timeout_minutes * 60,
            on_line=lambda line: _pending_seen(conn, draft.id, line),
        )
    except procs.ProcError as e:
        # It never started, so it posted nothing.
        return _back(conn, draft, version, f"the post command did not start: {e}", None)
    except BaseException:
        # Whatever stopped it, the post may have reached GitHub: the draft waits on a whole read, never posted again.
        _lost(conn, draft.id)
        raise
    lines, comments = _lines(result.stdout)
    said = result.stderr.strip()[-_MAX_STDERR:]
    end, pending = lines.get("end"), lines.get("pending")
    fields = {"review_draft": draft.id, "version": version.number, "submit": submit, "stderr": said}
    if end is not None and end.get("submitted") is True:
        log.info("review published", extra=fields)
        return _published(conn, draft, version, lines.get("review", {}), comments)
    if end is not None and end.get("staged") is True and pending is not None and _int(pending.get("id")) is not None:
        log.info("review staged", extra=fields)
        return _staged(conn, draft, version, pending)
    if (end is not None and end.get("staged") is not True) or pending is None:
        # It said nothing was posted, or it opened no review, so it posted nothing.
        log.warning("review not published", extra=fields)
        why = f"nothing was posted: {said or 'the post command refused'}"
        return _back(conn, draft, version, why, end)
    log.warning("review of unknown outcome", extra=fields)
    return _unconfirmed(conn, draft, version, pending)


def _pending_seen(conn: sqlite3.Connection, draft_id: int, line: str) -> None:
    """Record the pending review the post command names as it prints it, so a read can settle a publish cut short."""
    try:
        raw: object = json.loads(line)
    except json.JSONDecodeError:
        return
    if not isinstance(raw, dict) or raw.get("kind") != "pending":
        return
    with db.transaction(conn):
        sql.execute(
            conn,
            sql.update("review_drafts")
            .set(pending_review=_str(raw.get("review")), pending_review_id=_int(raw.get("id")))
            .where("id = ?", draft_id),
        )


def _lost(conn: sqlite3.Connection, draft_id: int) -> None:
    """A publish that stopped before its post said how it ended: unconfirmed, with the pending review it saw, if any."""
    with db.transaction(conn):
        sql.execute(
            conn,
            sql.update("review_drafts")
            .set(status=ReviewDraftStatus.UNCONFIRMED, why="the publish stopped before the post said how it ended")
            .where("id = ?", draft_id)
            .where("status = ?", ReviewDraftStatus.PUBLISHING),
        )


def _lines(stdout: str) -> tuple[dict[str, dict[str, object]], list[dict[str, object]]]:
    """The post command's lines by kind, the last of each, and its `comment` lines by their index in the request.

    Returns:
        The lines, and the comments' lines in the order they were asked for.
    """
    found: dict[str, dict[str, object]] = {}
    comments: dict[int, dict[str, object]] = {}
    for text in stdout.splitlines():
        try:
            raw: object = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        line = {str(k): v for k, v in raw.items()}
        index = _int(line.get("index"))
        if line.get("kind") == "comment" and index is not None:
            comments[index] = line
        else:
            found[str(line.get("kind"))] = line
    return found, [comments[i] for i in sorted(comments)]


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _published(
    conn: sqlite3.Connection,
    draft: records.ReviewDraft,
    version: Version,
    review: Mapping[str, object],
    comments: Sequence[Mapping[str, object]],
) -> Published:
    posted = [{"id": _int(c.get("id")), "url": _str(c.get("url"))} for c in comments]
    with db.transaction(conn):
        sql.execute(
            conn,
            sql.update("review_drafts")
            .set(
                status=ReviewDraftStatus.PUBLISHED,
                why=None,
                pending_review=None,
                pending_review_id=None,
                published_at=db.now(),
                published_review_id=_int(review.get("id")),
                published_url=_str(review.get("url")),
                published_comments=json.dumps(posted),
            )
            .where("id = ?", draft.id),
        )
    return Published(_present(conn, draft), version)


def _staged(
    conn: sqlite3.Connection,
    draft: records.ReviewDraft,
    version: Version,
    pending: Mapping[str, object],
) -> Published:
    with db.transaction(conn):
        sql.execute(
            conn,
            sql.update("review_drafts")
            .set(
                status=ReviewDraftStatus.STAGED,
                why=None,
                pending_review=_str(pending.get("review")),
                pending_review_id=_int(pending.get("id")),
            )
            .where("id = ?", draft.id),
        )
    return Published(_present(conn, draft), version)


def _back(
    conn: sqlite3.Connection,
    draft: records.ReviewDraft,
    version: Version,
    why: str,
    end: Mapping[str, object] | None,
) -> Published:
    """A post that posted nothing: the draft waits again, keeping a pending review it could not delete.

    Returns:
        The draft, waiting, and why nothing was posted.
    """
    left = _str(end.get("pending")) if end is not None else None
    with db.transaction(conn):
        _unclaim(conn, draft.id, why=why, pending=left or draft.pending_review)
    return Published(_present(conn, draft), version, failed=why)


def _unclaim(conn: sqlite3.Connection, draft_id: int, *, why: str, pending: str | None) -> None:
    sql.execute(
        conn,
        sql.update("review_drafts")
        .set(
            status=ReviewDraftStatus.WAITING,
            why=why,
            publish_version=None,
            publish_started_at=None,
            publish_channel=None,
            pending_review=pending,
            pending_review_id=None,
        )
        .where("id = ?", draft_id),
    )


def _unconfirmed(
    conn: sqlite3.Connection,
    draft: records.ReviewDraft,
    version: Version,
    pending: Mapping[str, object],
) -> Published:
    """A post that may have posted: the draft is unconfirmed until a whole read of its PR settles it.

    Returns:
        The draft, unconfirmed.
    """
    with db.transaction(conn):
        sql.execute(
            conn,
            sql.update("review_drafts")
            .set(
                status=ReviewDraftStatus.UNCONFIRMED,
                why="the post ended without saying whether it submitted",
                pending_review=_str(pending.get("review")),
                pending_review_id=_int(pending.get("id")),
            )
            .where("id = ?", draft.id),
        )
    return Published(_present(conn, draft), version)


def _present(conn: sqlite3.Connection, draft: records.ReviewDraft) -> records.ReviewDraft:
    return review_drafts.get(conn, draft.id) or draft


def expire_claims(conn: sqlite3.Connection, config: Config) -> list[int]:
    """Take each publish that has held its draft past its post command's timeout, and a margin, as of unknown outcome.

    The process posting it was killed, or it would have ended by now: its draft is unconfirmed, so the next whole read
    of its PR settles it, by the pending review the post printed, or as nothing posted if it printed none.

    Returns:
        The drafts' ids.
    """
    minutes = config.connect.vcs().timeout_minutes + CLAIM_MARGIN_MINUTES
    before = db.format_time(datetime.now(UTC) - timedelta(minutes=minutes))
    with db.transaction(conn):
        rows = sql.execute(
            conn,
            sql.update("review_drafts")
            .set(status=ReviewDraftStatus.UNCONFIRMED, why="the publish stopped before the post said how it ended")
            .where("status = ?", ReviewDraftStatus.PUBLISHING)
            .where("publish_started_at < ?", before)
            .returning("id"),
        ).fetchall()
    return [int(r["id"]) for r in rows]


def settle_by_read(conn: sqlite3.Connection, whole: Iterable[str]) -> list[records.ReviewDraft]:
    """Settle the unconfirmed and staged drafts of the PRs just read whole, by their pending review's id, never by text.

    Submitted, that review is the draft's, published. For an unconfirmed post, still pending or gone means nothing was
    posted, and the draft waits again, a pending one to be deleted by the next post. A staged review is the operator's
    to submit on GitHub, so one still pending stays staged, and one gone means they deleted it: the draft waits again.
    An unconfirmed draft whose post printed no pending review opened none, so it waits again too.

    Returns:
        The drafts settled, as they now stand.
    """
    with db.transaction(conn):
        waiting = records.fetch_all(
            conn,
            records.ReviewDraft,
            sql.select("*")
            .from_("review_drafts")
            .where_in("pr_url", sorted(set(whole)))
            .where_in("status", (ReviewDraftStatus.UNCONFIRMED, ReviewDraftStatus.STAGED)),
        )
        settled = [draft.id for draft in waiting if _settle_one(conn, draft)]
    return [d for d in (review_drafts.get(conn, i) for i in settled) if d is not None]


def _settle_one(conn: sqlite3.Connection, draft: records.ReviewDraft) -> bool:
    """Settle one draft by what the read found of its pending review.

    Returns:
        Whether it is settled; False while a staged review is pending.
    """
    review = records.fetch_one(
        conn,
        records.ObservedReview,
        sql.select("*")
        .from_("observed_reviews")
        .where("pr_url = ?", draft.pr_url)
        .where("item = ?", ReviewItem.REVIEW)
        .where("id = ?", draft.pending_review_id),
    )
    staged = draft.status is ReviewDraftStatus.STAGED
    if review is not None and review.state is ReviewState.PENDING:
        if staged:
            return False
        _unclaim(conn, draft.id, why="the read found nothing posted", pending=draft.pending_review)
        return True
    if review is None:
        why = "the review you staged was deleted on GitHub" if staged else "the read found nothing posted"
        _unclaim(conn, draft.id, why=why, pending=None)
        return True
    comments = records.fetch_all(
        conn,
        records.ObservedReview,
        sql.select("*")
        .from_("observed_reviews")
        .where("pr_url = ?", draft.pr_url)
        .where("item = ?", ReviewItem.COMMENT)
        .where("review_id = ?", review.id)
        .order_by("created_at, id"),
    )
    sql.execute(
        conn,
        sql.update("review_drafts")
        .set(
            status=ReviewDraftStatus.PUBLISHED,
            why="submitted by you on GitHub" if staged else "settled published by a read",
            pending_review=None,
            pending_review_id=None,
            published_at=db.now(),
            published_review_id=review.id,
            published_url=review.url,
            published_comments=json.dumps([{"id": c.id, "url": c.url} for c in comments]),
        )
        .where("id = ?", draft.id),
    )
    return True


def unsettled_prs(conn: sqlite3.Connection) -> list[str]:
    """Return the PRs with a review's draft unconfirmed or staged, which each tick's reconcile reads again.

    Returns:
        The PRs' URLs, in order.
    """
    rows = sql.execute(
        conn,
        sql.select("pr_url")
        .unique()
        .from_("review_drafts")
        .where_in("status", (ReviewDraftStatus.UNCONFIRMED, ReviewDraftStatus.STAGED))
        .order_by("pr_url"),
    )
    return [str(r["pr_url"]) for r in rows]
