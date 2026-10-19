"""The operator's verbs on drafts (DESIGN §29, Sending): editing, dropping, sending, staging, and settling one.

Each refuses inside canopy's ticks and runs (`conversation.check_operator`): an agent that could send a draft could post
as the operator. The CLI's `canopy draft` and the web UI call the same functions, so with the same guards.

Sending posts exactly the text and the reaction the operator last saw, named by their hash, with no comment marks. The
drafts sent together for one PR go through the `vcs` source's `post_cmd` as one comment review, their reactions added
before it; a ticket's, through the `tracker` source's. Each is posted at most once: a send claims its drafts before it
posts, and one whose post ends without saying whether it submitted is `unconfirmed`, never posted again by canopy until
a whole read of its PR, or the operator for a ticket's, settles it.

Staging is sending without the submit: one PR's drafts go into a pending review, left on GitHub for the operator to
finish there, and stay `staged` until a whole read finds that review submitted, when they are sent, or gone, when they
wait again. While a PR holds one, nothing else is sent or staged on it, since GitHub keeps one pending review a person.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, assert_never

from canopy.core import conversation, db, drafts, observe, records
from canopy.core.config import notify_words
from canopy.core.memory_text import TextRefused
from canopy.core.vocab import DraftAuthor, DraftKind, DraftStatus, Reaction, ReviewItem, ReviewState
from canopy.infra import logs, procs

if TYPE_CHECKING:
    from canopy.core.config import Config, Source

# How many hex characters of a text's SHA-256 name it, in the CLI and the web UI alike.
HASH_CHARS = 12
# How much of a comment a `thread_changed` refusal quotes, and of the poster's stderr a failure says.
_MAX_QUOTED = 100
_MAX_STDERR = 300


def hash_of(text: str, reaction: Reaction | None) -> str:
    """Return the name of a draft's words as the operator saw them: the start of their SHA-256, hex.

    A draft with no reaction is named by its text alone, as it was before a draft could stage one.
    """
    words = text if reaction is None else f"{text}\0{reaction}"
    return hashlib.sha256(words.encode()).hexdigest()[:HASH_CHARS]


def hash_of_version(version: records.DraftVersion) -> str:
    """Return the name of a version of a draft: its text and its reaction, as `hash_of` names them."""
    return hash_of(version.body, version.reaction)


def find(conn: sqlite3.Connection, run_id: int, number: int) -> records.Draft:
    """Return draft `number` of run `run_id`.

    Returns:
        The draft.

    Raises:
        Refused: (`unknown`) the run has no such draft.
    """
    found = records.fetch_one(
        conn, records.Draft, "SELECT * FROM drafts WHERE run_id = ? AND number = ?", (run_id, number)
    )
    if found is None:
        raise conversation.Refused("unknown", f"run {run_id} has no draft {number}")
    return found


def edit(
    conn: sqlite3.Connection, run_id: int, number: int, text: str, reaction: Reaction | None, *, channel: str
) -> records.DraftVersion:
    """Make the operator's `text` and `reaction` the draft's, as a new version beside the run's own.

    The text may be empty beside a reaction, which then goes alone.

    Returns:
        The draft's words as they now stand.

    Raises:
        Refused: (`inside_run`) inside one of canopy's ticks or runs; (`unknown`) no such draft; a status that takes no
            edit, named for it, such as `sent`; (`bad_text`) a text canopy would not keep, for the reason a run's
            draft would be refused, or none without a reaction; (`no_reaction`) a reaction on a draft that is not a
            thread's.
    """
    conversation.check_operator()
    draft = find(conn, run_id, number)
    _check_open(draft)
    if reaction is not None and draft.kind is not DraftKind.THREAD:
        raise conversation.Refused(
            "no_reaction", f"run {run_id}'s draft {number} is not a thread's; only a review comment takes a reaction"
        )
    try:
        body = drafts.check_words(text, reaction)
    except TextRefused as e:
        raise conversation.Refused("bad_text", str(e)) from e
    current = drafts.text_of(conn, draft.id)
    if (body, reaction) == (current.body, current.reaction):
        return current
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO draft_versions (draft_id, version, body, author, channel, created_at, reaction) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (draft.id, current.version + 1, body, DraftAuthor.OPERATOR, channel, db.now(), reaction),
        )
    return drafts.text_of(conn, draft.id)


def drop(conn: sqlite3.Connection, run_id: int, numbers: Iterable[int], *, undo: bool = False) -> list[records.Draft]:
    """Drop drafts, so nobody sends them, or with `undo` take a drop back. Dropping one already dropped changes nothing.

    Returns:
        The drafts as they now stand, in the order named.

    Raises:
        Refused: (`inside_run`); (`unknown`) no such draft; a status that cannot be dropped or taken back, named for it.
    """
    conversation.check_operator()
    found = [find(conn, run_id, n) for n in dict.fromkeys(numbers)]
    with db.transaction(conn):
        for draft in found:
            if undo:
                if draft.status is not DraftStatus.DROPPED:
                    raise conversation.Refused(draft.status, f"run {run_id}'s draft {draft.number} is not dropped")
                # Back to where it stood: a draft no read has checked yet waits on one again.
                back = DraftStatus.UNCHECKED if draft.kind is not DraftKind.TICKET and not draft.checked_at else None
                status, why = back or DraftStatus.WAITING, None
            elif draft.status is DraftStatus.DROPPED:
                continue
            else:
                _check_open(draft)
                status, why = DraftStatus.DROPPED, "dropped by the operator"
            conn.execute("UPDATE drafts SET status = ?, why = ? WHERE id = ?", (status, why, draft.id))
    return [d for d in (drafts.get(conn, d.id) for d in found) if d is not None]


def settle(conn: sqlite3.Connection, run_id: int, number: int, *, sent: bool) -> records.Draft:
    """Settle an unconfirmed draft by the operator's word: it was posted, or it was not and may be sent again.

    A PR's drafts are settled by a whole read of the PR (`settle_unconfirmed`); a ticket's has no reader, so the
    operator looks at the ticket and says.

    Returns:
        The draft as it now stands.

    Raises:
        Refused: (`inside_run`); (`unknown`) no such draft; (`not_unconfirmed`) it is not.
    """
    conversation.check_operator()
    draft = find(conn, run_id, number)
    if draft.status is not DraftStatus.UNCONFIRMED:
        raise conversation.Refused("not_unconfirmed", f"run {run_id}'s draft {number} is {draft.status}")
    with db.transaction(conn):
        if sent:
            conn.execute(
                "UPDATE drafts SET status = ?, sent_at = ?, why = 'settled sent by the operator' WHERE id = ?",
                (DraftStatus.SENT, db.now(), draft.id),
            )
        else:
            _unclaim(conn, [draft.id], why="settled unsent by the operator")
    found = drafts.get(conn, draft.id)
    if found is None:
        raise conversation.Refused("unknown", f"run {run_id} has no draft {number}")
    return found


def _check_open(draft: records.Draft) -> None:
    """Refuse an edit or a drop of a draft past both: one sent, sending, staged, superseded, refused, or unconfirmed.

    Raises:
        Refused: Named for the draft's status.
    """
    if draft.status not in (DraftStatus.WAITING, DraftStatus.UNCHECKED):
        raise conversation.Refused(draft.status, f"run {draft.run_id}'s draft {draft.number} is {draft.status}")


@dataclass(frozen=True)
class Wanted:
    """A draft the operator sends: its run, its number, and the hash of its text as they last saw it."""

    run_id: int
    number: int
    hash: str


@dataclass
class Sent:
    """What a send or a stage did: the drafts posted, staged, posted before, failed, and unconfirmed."""

    posted: list[records.Draft] = field(default_factory=list)
    already: list[records.Draft] = field(default_factory=list)
    failed: list[tuple[records.Draft, str]] = field(default_factory=list)
    unconfirmed: list[records.Draft] = field(default_factory=list)
    staged: list[records.Draft] = field(default_factory=list)


def send(
    conn: sqlite3.Connection,
    config: Config,
    runner: procs.Runner,
    wanted: Sequence[Wanted],
    *,
    channel: str,
    log: logs.TickAdapter,
) -> Sent:
    """Send drafts, each exactly as the operator last saw it, as their own words (DESIGN §29, Sending).

    Every check runs before anything posts, and a refusal posts nothing: each draft must wait on the operator, with the
    text its hash names; each PR is read again whole; and a comment on a draft's thread since its basis refuses
    `thread_changed`, moving the basis so sending again posts. A draft already sent records nothing new.

    Returns:
        What was posted, already posted, failed, or left unconfirmed.

    Raises:
        Refused: (`inside_run`); (`unknown`); a status that cannot be sent, named for it; (`stale`) a text changed since
            the operator saw it; (`unchecked`) a PR not read whole now; (`thread_changed`); (`staged`) its PR holds a
            review the operator staged; (`no_post`) no command posts there.
    """
    return _deliver(conn, config, runner, wanted, channel=channel, log=log, submit=True)


def stage(
    conn: sqlite3.Connection,
    config: Config,
    runner: procs.Runner,
    wanted: Sequence[Wanted],
    *,
    channel: str,
    log: logs.TickAdapter,
) -> Sent:
    """Stage drafts in a pending review on each one's PR, for the operator to finish and submit there themselves.

    Every check a send makes runs first, and each draft must be a PR's whose reaction, if any, is on GitHub already:
    GitHub has no pending reaction. Each PR's drafts go into one review, its own comment as the review's body, and
    are `staged` until a whole read of the PR settles them.

    Returns:
        What was staged, already posted, failed, or left unconfirmed.

    Raises:
        Refused: As `send` does; (`not_pr`) a ticket's draft, which has no review; (`reaction`) a reaction not yet
            added, which only a send adds.
    """
    return _deliver(conn, config, runner, wanted, channel=channel, log=log, submit=False)


def _deliver(
    conn: sqlite3.Connection,
    config: Config,
    runner: procs.Runner,
    wanted: Sequence[Wanted],
    *,
    channel: str,
    log: logs.TickAdapter,
    submit: bool,
) -> Sent:
    conversation.check_operator()
    outcome = Sent()
    chosen: dict[int, records.Draft] = {}
    seen: dict[int, str] = {}
    for w in wanted:
        draft = find(conn, w.run_id, w.number)
        if draft.status is DraftStatus.SENT:
            outcome.already.append(draft)
            continue
        _check_sendable(conn, draft, w.hash)
        if not submit:
            _check_stageable(conn, draft)
        chosen[draft.id] = draft
        seen[draft.id] = w.hash
    if not chosen:
        return outcome
    groups = _groups(chosen.values())
    sources = {key: _poster(config, key) for key in groups}
    prs = [k for k in groups if k.pr is not None]
    _check_threads(conn, config, runner, keys=prs, groups=groups, log=log)
    _check_none_staged(conn, [k.pr for k in prs if k.pr is not None])
    _claim(conn, chosen.values(), seen, channel)
    for key, group in groups.items():
        _post(conn, sources[key], runner, key=key, group=group, outcome=outcome, log=log, submit=submit)
    return outcome


def _check_sendable(conn: sqlite3.Connection, draft: records.Draft, seen: str) -> None:
    """Refuse a draft that does not wait on the operator, or whose text is not the one they saw.

    Raises:
        Refused: Named for its status, or `stale`.
    """
    where = f"run {draft.run_id}'s draft {draft.number}"
    match draft.status:
        case DraftStatus.WAITING:
            pass
        case DraftStatus.UNCHECKED:
            raise conversation.Refused("unchecked", f"{where} waits on a whole read of {draft.pr_url}")
        case DraftStatus.UNCONFIRMED:
            raise conversation.Refused(
                "unconfirmed", f"{where} may have been posted already; a read of its PR, or `canopy draft settle`, says"
            )
        case DraftStatus.STAGED:
            raise conversation.Refused("staged", f"{where} is in the review you staged on {draft.pr_url}: {_FINISH}")
        case DraftStatus.SUPERSEDED | DraftStatus.DROPPED | DraftStatus.REFUSED | DraftStatus.SENDING:
            raise conversation.Refused(draft.status, f"{where} is {draft.status}: {draft.why or 'not sendable'}")
        case DraftStatus.SENT:
            pass
        case _:
            assert_never(draft.status)
    current = hash_of_version(drafts.text_of(conn, draft.id))
    if current != seen:
        raise conversation.Refused("stale", _changed(draft, current))


# What the operator does with a review they staged, which a refusal for it says.
_FINISH = "submit or delete it on GitHub, and the next read of the PR settles it"


def _check_stageable(conn: sqlite3.Connection, draft: records.Draft) -> None:
    """Refuse a draft a pending review cannot hold: a ticket's, or a reaction not yet on GitHub.

    Raises:
        Refused: (`not_pr`) or (`reaction`).
    """
    where = f"run {draft.run_id}'s draft {draft.number}"
    if draft.kind is DraftKind.TICKET:
        raise conversation.Refused("not_pr", f"{where} is a ticket's comment, which no review holds; send it")
    reaction = drafts.text_of(conn, draft.id).reaction
    if reaction is not None and draft.reacted != reaction:
        raise conversation.Refused(
            "reaction",
            f"{where} adds {reaction}, and GitHub has no pending reaction; send it, or take the reaction off",
        )


def _check_none_staged(conn: sqlite3.Connection, prs: Iterable[str]) -> None:
    """Refuse to post on a PR that holds a review the operator staged: GitHub keeps one pending review a person.

    Raises:
        Refused: (`staged`), naming the PR.
    """
    for pr in prs:
        if conn.execute("SELECT 1 FROM drafts WHERE pr_url = ? AND status = ?", (pr, DraftStatus.STAGED)).fetchone():
            raise conversation.Refused("staged", f"{pr} holds a review you staged: {_FINISH}")


def _changed(draft: records.Draft, current: str) -> str:
    return f"run {draft.run_id}'s draft {draft.number}'s text changed since you saw it: it is {current} now"


@dataclass(frozen=True)
class _Key:
    """Where a group of drafts posts: a PR, or a ticket's issue."""

    pr: str | None
    issue: str | None
    ticket: str


def _groups(chosen: Iterable[records.Draft]) -> dict[_Key, list[records.Draft]]:
    found: dict[_Key, list[records.Draft]] = {}
    for d in sorted(chosen, key=lambda d: (d.run_id, d.number)):
        key = (
            _Key(pr=None, issue=d.issue_url, ticket=d.ticket_key)
            if d.kind is DraftKind.TICKET
            else _Key(pr=d.pr_url, issue=None, ticket=d.ticket_key)
        )
        found.setdefault(key, []).append(d)
    return found


def _poster(config: Config, key: _Key) -> Source:
    """The source whose `post_cmd` posts the group at `key`.

    Returns:
        The `vcs` source for a PR, the `tracker` source for a ticket.

    Raises:
        Refused: (`no_post`) no source posts there.
    """
    source = config.connect.vcs() if key.pr is not None else config.connect.tracker()
    if source is None or not notify_words(source.post_cmd):
        where = key.pr or f"{key.ticket}'s ticket"
        raise conversation.Refused("no_post", f"no [connect.sources] post_cmd posts to {where}")
    return source


def _check_threads(
    conn: sqlite3.Connection,
    config: Config,
    runner: procs.Runner,
    *,
    keys: Sequence[_Key],
    groups: Mapping[_Key, Sequence[records.Draft]],
    log: logs.TickAdapter,
) -> None:
    """Read each PR again whole, and refuse a draft whose thread has a comment newer than its basis.

    Raises:
        Refused: (`unchecked`) a PR not read whole now; (`thread_changed`) a comment arrived, which the refusal names.
    """
    prs = [k.pr for k in keys if k.pr is not None]
    if not prs:
        return
    read = observe.read(conn, config, runner, prs, log)
    missed = [pr for pr in prs if pr not in read.whole]
    if missed:
        raise conversation.Refused("unchecked", f"could not read {', '.join(missed)} whole now: {read.failure}")
    settle_by_read(conn, read.whole)
    changed: list[str] = []
    with db.transaction(conn):
        for key in keys:
            for draft in groups[key]:
                if draft.kind is not DraftKind.THREAD:
                    continue
                newer = _newer_comments(conn, draft)
                if newer:
                    conn.execute("UPDATE drafts SET basis = ? WHERE id = ?", (newer[-1].created_at, draft.id))
                    changed.extend(_quoted(draft, c) for c in newer)
    if changed:
        raise conversation.Refused(
            "thread_changed",
            "a comment arrived after the draft was made; read it, then send again: " + "; ".join(changed),
        )


def _newer_comments(conn: sqlite3.Connection, draft: records.Draft) -> list[records.ObservedReview]:
    """The comments on the draft's thread newer than its basis, but the operator's sent ones and a pending review's.

    The operator sent theirs through canopy, and nobody else sees a pending review's.

    Returns:
        The comments, oldest first.
    """
    return records.fetch_all(
        conn,
        records.ObservedReview,
        "SELECT * FROM observed_reviews o WHERE o.pr_url = ? AND o.item = ? AND o.thread_id = ? AND o.created_at > ? "
        "AND o.id NOT IN (SELECT sent_comment_id FROM drafts WHERE pr_url = ? AND sent_comment_id IS NOT NULL) "
        "AND NOT EXISTS (SELECT 1 FROM observed_reviews r WHERE r.pr_url = o.pr_url AND r.item = ? "
        "AND r.id = o.review_id AND r.state = ?) ORDER BY o.created_at, o.id",
        (
            draft.pr_url,
            ReviewItem.COMMENT,
            draft.thread_id,
            draft.basis,
            draft.pr_url,
            ReviewItem.REVIEW,
            ReviewState.PENDING,
        ),
    )


def _quoted(draft: records.Draft, comment: records.ObservedReview) -> str:
    body = " ".join(comment.body.split())
    cut = body if len(body) <= _MAX_QUOTED else f"{body[:_MAX_QUOTED]}…"
    return f"draft {draft.number} of run {draft.run_id}: comment {comment.id} by {comment.author}: {cut}"


def _claim(conn: sqlite3.Connection, chosen: Iterable[records.Draft], seen: Mapping[int, str], channel: str) -> None:
    """Claim the drafts for this send, so two sends at once post them once, each at the text the operator saw.

    The hash is checked again here, since the PRs were read between the first check and this one, and an edit may have
    come in meanwhile; once claimed, a draft takes no edit, so what posts is the version claimed.

    Raises:
        Refused: (`stale`) a text changed since the operator saw it; (`sending`, or the status it now has) another send
            claimed one first, or it changed since it was read.
    """
    now = db.now()
    with db.transaction(conn):
        for draft in chosen:
            text = drafts.text_of(conn, draft.id)
            current = hash_of_version(text)
            if current != seen[draft.id]:
                raise conversation.Refused("stale", _changed(draft, current))
            version = text.version
            claimed = conn.execute(
                "UPDATE drafts SET status = ?, send_started_at = ?, send_version = ?, sent_channel = ? "
                "WHERE id = ? AND status = ?",
                (DraftStatus.SENDING, now, version, channel, draft.id, DraftStatus.WAITING),
            ).rowcount
            if not claimed:
                now_is = drafts.get(conn, draft.id)
                status = now_is.status if now_is is not None else "unknown"
                where = f"run {draft.run_id}'s draft {draft.number}"
                raise conversation.Refused(status, f"{where} became {status} while this send checked it")


def _post(
    conn: sqlite3.Connection,
    source: Source,
    runner: procs.Runner,
    *,
    key: _Key,
    group: Sequence[records.Draft],
    outcome: Sent,
    log: logs.TickAdapter,
    submit: bool,
) -> None:
    """Post one PR's drafts as one review, or stage them, or a ticket's draft as one comment, and record each's fate."""
    versions = {d.id: drafts.text_of(conn, d.id) for d in group}
    texts = {i: v.body for i, v in versions.items()}
    if key.pr is not None:
        body = next((texts[d.id] for d in group if d.kind is DraftKind.PR), None)
        replies = [_reply(d, versions[d.id]) for d in group if d.kind is DraftKind.THREAD]
        request: dict[str, object] = {
            "pr": key.pr,
            "delete_pending": _left_pending(conn, key.pr),
            "body": body,
            "replies": replies,
        }
        if not submit:
            request["submit"] = False
    else:
        [draft] = group
        request = {"issue": key.issue, "ticket": key.ticket, "body": texts[draft.id]}
    try:
        result = runner.run(
            notify_words(source.post_cmd), stdin=json.dumps(request), timeout=source.timeout_minutes * 60
        )
    except procs.ProcError as e:
        # It never started, so it posted nothing.
        _back(conn, group, outcome, f"the post command did not start: {e}", None)
        log.warning("drafts not posted", extra={"drafts": [d.id for d in group], "reason": str(e)})
        return
    lines = _post_lines(result.stdout)
    _reacted(conn, group, versions, lines)
    said = result.stderr.strip()[-_MAX_STDERR:]
    end = lines.get("end")
    pending = lines.get("pending")
    if end is not None and end.get("submitted") is True:
        _posted(conn, group, lines, outcome)
    elif end is not None and end.get("staged") is True:
        # A staged review, or a reply in it, that a read cannot find by its id is not one canopy can settle as staged.
        if pending is not None and _int(pending.get("id")) is not None and _replies_known(group, lines):
            _staged(conn, group, lines, pending, outcome)
        else:
            _unconfirmed(conn, group, pending, outcome)
    elif end is not None:
        _back(conn, group, outcome, f"nothing was posted: {said or 'the post command refused'}", end)
    elif key.pr is not None and pending is None:
        # It opened no review, so it posted nothing. A ticket's comment has no review: without an end it may be posted.
        _back(conn, group, outcome, f"nothing was posted: {said or 'the post command failed'}", None)
    else:
        _unconfirmed(conn, group, pending, outcome)
    log.info(
        "drafts sent",
        extra={
            "drafts": [d.id for d in group],
            "submitted": bool(end and end.get("submitted")),
            "staged": bool(end and end.get("staged")),
            "stderr": said,
        },
    )


def _reply(draft: records.Draft, version: records.DraftVersion) -> dict[str, object]:
    """A thread's draft as the post command takes it: the comment it answers, its text, and its reaction, if any.

    Returns:
        The reply, with no `text` for a reaction sent alone and no `reaction` for a draft with none.
    """
    reply: dict[str, object] = {"comment": draft.comment_id}
    if version.body:
        reply["text"] = version.body
    if version.reaction is not None:
        reply["reaction"] = version.reaction
    return reply


def _reacted(
    conn: sqlite3.Connection,
    group: Sequence[records.Draft],
    versions: Mapping[int, records.DraftVersion],
    lines: Mapping[str, Mapping[str, object]],
) -> None:
    """Record each reaction the post command says it added, whatever became of the rest of the post.

    A reaction is added before the review is opened, and stays on GitHub if the review then fails, so the draft keeps
    it even when it waits again.
    """
    now = db.now()
    with db.transaction(conn):
        for d in group:
            # Only a thread's draft holds a reaction.
            reaction = versions[d.id].reaction
            if reaction is not None and lines.get(f"reaction:{d.comment_id}", {}).get("reaction") == reaction:
                conn.execute("UPDATE drafts SET reacted = ?, reacted_at = ? WHERE id = ?", (reaction, now, d.id))


def _left_pending(conn: sqlite3.Connection, pr: str) -> str | None:
    """The pending review an earlier post left on `pr`, which this one deletes first; never one the operator staged.

    Returns:
        Its node id, or None when no post left one.
    """
    row = conn.execute(
        "SELECT pending_review FROM drafts WHERE pr_url = ? AND pending_review IS NOT NULL AND status NOT IN (?, ?) "
        "LIMIT 1",
        (pr, DraftStatus.UNCONFIRMED, DraftStatus.STAGED),
    ).fetchone()
    return None if row is None else str(row["pending_review"])


def _post_lines(stdout: str) -> dict[str, dict[str, object]]:
    """The post command's lines by kind, the last of each.

    A comment's or a reaction's is keyed by the comment it names, `comment:<id>` or `reaction:<id>`.

    Returns:
        The lines, each a JSON object.
    """
    found: dict[str, dict[str, object]] = {}
    for text in stdout.splitlines():
        try:
            raw: object = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        line = {str(k): v for k, v in raw.items()}
        kind = str(line.get("kind"))
        if kind in {"comment", "reaction"} and "comment" in line:
            kind = f"{kind}:{line['comment']}"
        found[kind] = line
    return found


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _posted(
    conn: sqlite3.Connection, group: Sequence[records.Draft], lines: Mapping[str, Mapping[str, object]], outcome: Sent
) -> None:
    review = lines.get("review", {})
    issue_comment = lines.get("comment", {})
    now = db.now()
    with db.transaction(conn):
        for d in group:
            match d.kind:
                case DraftKind.THREAD:
                    # A reaction sent alone posts no comment: its line names the comment it went on.
                    line = lines.get(f"comment:{d.comment_id}") or lines.get(f"reaction:{d.comment_id}", {})
                case DraftKind.PR:
                    line = review
                case DraftKind.TICKET:
                    line = issue_comment
                case _:
                    assert_never(d.kind)
            conn.execute(
                "UPDATE drafts SET status = ?, sent_at = ?, sent_comment_id = ?, sent_review_id = ?, sent_url = ?, "
                "pending_review = NULL, pending_review_id = NULL, why = NULL WHERE id = ?",
                (
                    DraftStatus.SENT,
                    now,
                    _int(line.get("id")) if d.kind is not DraftKind.PR else None,
                    _int(review.get("id")),
                    _str(line.get("url")),
                    d.id,
                ),
            )
        pr = group[0].pr_url
        if pr is not None:
            # The pending review an earlier post left was deleted first.
            conn.execute("UPDATE drafts SET pending_review = NULL, pending_review_id = NULL WHERE pr_url = ?", (pr,))
    outcome.posted.extend(d for d in (drafts.get(conn, d.id) for d in group) if d is not None)


def _replies_known(group: Sequence[records.Draft], lines: Mapping[str, Mapping[str, object]]) -> bool:
    """Whether the post named each thread's draft's new comment by its id, which a staged draft is known by.

    Returns:
        True when every reply in `group` has its `comment` line, with an id.
    """
    return all(
        _int(lines.get(f"comment:{d.comment_id}", {}).get("id")) is not None
        for d in group
        if d.kind is DraftKind.THREAD
    )


def _staged(
    conn: sqlite3.Connection,
    group: Sequence[records.Draft],
    lines: Mapping[str, Mapping[str, object]],
    pending: Mapping[str, object],
    outcome: Sent,
) -> None:
    """A stage that holds every draft in its pending review: each is `staged`, a reply known by its comment's id."""
    node, review_id = _str(pending.get("review")), _int(pending.get("id"))
    with db.transaction(conn):
        for d in group:
            # A thread's line names the comment it answered; the PR's own draft is the review's body.
            comment: Mapping[str, object] = (
                lines.get(f"comment:{d.comment_id}", {}) if d.kind is DraftKind.THREAD else {}
            )
            conn.execute(
                "UPDATE drafts SET status = ?, why = NULL, pending_review = ?, pending_review_id = ?, "
                "sent_comment_id = ?, sent_url = ? WHERE id = ?",
                (DraftStatus.STAGED, node, review_id, _int(comment.get("id")), _str(comment.get("url")), d.id),
            )
    outcome.staged.extend(d for d in (drafts.get(conn, d.id) for d in group) if d is not None)


def _back(
    conn: sqlite3.Connection,
    group: Sequence[records.Draft],
    outcome: Sent,
    why: str,
    end: Mapping[str, object] | None,
) -> None:
    """A post that posted nothing: its drafts wait again, keeping a pending review it could not delete."""
    left = _str(end.get("pending")) if end is not None else None
    with db.transaction(conn):
        _unclaim(conn, [d.id for d in group], why=why)
        if left is not None:
            conn.executemany("UPDATE drafts SET pending_review = ? WHERE id = ?", [(left, d.id) for d in group])
    outcome.failed.extend((d, why) for d in group)


def _unclaim(conn: sqlite3.Connection, ids: Sequence[int], *, why: str) -> None:
    conn.executemany(
        "UPDATE drafts SET status = ?, why = ?, send_started_at = NULL, send_version = NULL, sent_channel = NULL "
        "WHERE id = ?",
        [(DraftStatus.WAITING, why, i) for i in ids],
    )


def _unconfirmed(
    conn: sqlite3.Connection, group: Sequence[records.Draft], pending: Mapping[str, object] | None, outcome: Sent
) -> None:
    """A post that may have posted: its drafts are unconfirmed until a read, or the operator, settles them."""
    node = _str(pending.get("review")) if pending is not None else None
    review_id = _int(pending.get("id")) if pending is not None else None
    with db.transaction(conn):
        conn.executemany(
            "UPDATE drafts SET status = ?, why = ?, pending_review = ?, pending_review_id = ? WHERE id = ?",
            [
                (DraftStatus.UNCONFIRMED, "the post ended without saying whether it submitted", node, review_id, d.id)
                for d in group
            ],
        )
    outcome.unconfirmed.extend(d for d in (drafts.get(conn, d.id) for d in group) if d is not None)


def settle_by_read(conn: sqlite3.Connection, whole: Iterable[str]) -> list[records.Draft]:
    """Settle the unconfirmed and staged drafts of the PRs just read whole, by their pending review's id, never by text.

    For an unconfirmed send, that review submitted means the drafts were posted, each reply known by its thread; still
    pending, or gone, means nothing was, and they wait again, a pending one to be deleted by the next post. A staged
    draft is the operator's to submit on GitHub, so one still pending stays staged; see `_settle_staged`.

    Returns:
        The drafts settled, as they now stand: those a staged review still holds are not among them.
    """
    settled: list[int] = []
    prs = sorted(set(whole))
    with db.transaction(conn):
        for pr in prs:
            for d in records.fetch_all(
                conn,
                records.Draft,
                "SELECT * FROM drafts WHERE pr_url = ? AND status IN (?, ?) AND pending_review_id IS NOT NULL",
                (pr, DraftStatus.UNCONFIRMED, DraftStatus.STAGED),
            ):
                if d.status is DraftStatus.UNCONFIRMED:
                    _settle_one(conn, d)
                    settled.append(d.id)
                elif _settle_staged(conn, d):
                    settled.append(d.id)
    return [d for d in (drafts.get(conn, i) for i in settled) if d is not None]


def _settle_staged(conn: sqlite3.Connection, draft: records.Draft) -> bool:
    """Settle a staged draft by what the read found of its review: still pending, submitted, or gone.

    Submitted, the draft is sent, unless the operator took its reply out of the review first, when it is dropped. Gone,
    the operator deleted the review on GitHub, and the draft waits on them again.

    Returns:
        Whether it is settled; False while the review is pending.
    """
    review = records.fetch_one(
        conn,
        records.ObservedReview,
        "SELECT * FROM observed_reviews WHERE pr_url = ? AND item = ? AND id = ?",
        (draft.pr_url, ReviewItem.REVIEW, draft.pending_review_id),
    )
    if review is not None and review.state is ReviewState.PENDING:
        return False
    if review is None:
        _unclaim(conn, [draft.id], why="the review you staged was deleted on GitHub")
        conn.execute(
            "UPDATE drafts SET pending_review = NULL, pending_review_id = NULL, sent_comment_id = NULL, "
            "sent_url = NULL WHERE id = ?",
            (draft.id,),
        )
        return True
    comment = None
    if draft.kind is DraftKind.THREAD:
        comment = records.fetch_one(
            conn,
            records.ObservedReview,
            "SELECT * FROM observed_reviews WHERE pr_url = ? AND item = ? AND review_id = ? AND id = ?",
            (draft.pr_url, ReviewItem.COMMENT, review.id, draft.sent_comment_id),
        )
        if comment is None:
            conn.execute(
                "UPDATE drafts SET status = ?, why = ?, pending_review = NULL, pending_review_id = NULL, "
                "sent_comment_id = NULL, sent_url = NULL WHERE id = ?",
                (DraftStatus.DROPPED, "taken out of the review you staged before you submitted it", draft.id),
            )
            return True
    conn.execute(
        "UPDATE drafts SET status = ?, sent_at = ?, sent_review_id = ?, sent_url = ?, pending_review = NULL, "
        "pending_review_id = NULL, why = 'submitted by the operator on GitHub' WHERE id = ?",
        (DraftStatus.SENT, db.now(), review.id, comment.url if comment is not None else review.url, draft.id),
    )
    return True


def _settle_one(conn: sqlite3.Connection, draft: records.Draft) -> None:
    review = records.fetch_one(
        conn,
        records.ObservedReview,
        "SELECT * FROM observed_reviews WHERE pr_url = ? AND item = ? AND id = ?",
        (draft.pr_url, ReviewItem.REVIEW, draft.pending_review_id),
    )
    if review is None or review.state is ReviewState.PENDING:
        pending = draft.pending_review if review is not None else None
        _unclaim(conn, [draft.id], why="the read found nothing posted")
        conn.execute("UPDATE drafts SET pending_review = ?, pending_review_id = NULL WHERE id = ?", (pending, draft.id))
        return
    comment = None
    if draft.kind is DraftKind.THREAD:
        comment = records.fetch_one(
            conn,
            records.ObservedReview,
            "SELECT * FROM observed_reviews WHERE pr_url = ? AND item = ? AND review_id = ? AND thread_id = ?",
            (draft.pr_url, ReviewItem.COMMENT, review.id, draft.thread_id),
        )
    conn.execute(
        "UPDATE drafts SET status = ?, sent_at = ?, sent_comment_id = ?, sent_review_id = ?, sent_url = ?, "
        "pending_review = NULL, pending_review_id = NULL, why = 'settled sent by a read' WHERE id = ?",
        (
            DraftStatus.SENT,
            db.now(),
            None if comment is None else comment.id,
            review.id,
            (comment.url if comment is not None else review.url),
            draft.id,
        ),
    )


def unsettled_prs(conn: sqlite3.Connection) -> list[str]:
    """Return the PRs with an unconfirmed or staged draft a read can settle, which each tick's reconcile reads again.

    A staged review is read each tick so the loop knows the operator submitted it before its overseer reads the PR.

    Returns:
        The PRs' URLs, in order.
    """
    rows = conn.execute(
        "SELECT DISTINCT pr_url FROM drafts WHERE status IN (?, ?) AND pending_review_id IS NOT NULL ORDER BY pr_url",
        (DraftStatus.UNCONFIRMED, DraftStatus.STAGED),
    )
    return [str(r["pr_url"]) for r in rows]
