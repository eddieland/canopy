"""What a feedback plan is offered of its PRs, what it saw of them, and what changed since (DESIGN §32).

An item is a review, or a thread of review comments, on one of a ticket's PRs, as the `vcs` source last read the PR
whole (DESIGN §29, §30). A thread is one item: the comment a feedback plan of the ticket covered, or else its first
comment, with each other comment on it a reply given beside it, so a reviewer's "never mind" or the PR author's "won't
do" reaches the planner as an answer to the item, never as work of its own. The operator's replies sent through canopy,
a worker's comments (D069), pending reviews, resolved threads, and reviews that say nothing are neither.

When a feedback plan is recorded, what its run's read saw is recorded with it (`take`, `record`): each PR's head, each
check's conclusion at that head, and each item and reply the planner was given, by id with a SHA-256 of its body, never
its text. An item a `resume` went ahead on stays handled while its body and its thread's replies are as that plan saw
them; once either changed, it is offered again. So the next round is what is new since the last plan, with the items a
failed `resume` handed back and those no plan covered. A plan is stale when what the connectors observe now differs
from what it saw (`changes`), each difference with its reason, computed here in code; the quiet period before a stale
plan is planned again runs from the newest item or reply on its PRs, or from when the harness first saw the head or
check conclusion they moved to, the newer (`newest`, `moved_at`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import astuple, dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, assert_never

from canopy.core import db, drafts, records, sql
from canopy.core.vocab import CheckConclusion, MoveKind, ReviewItem, ReviewState, RunStatus

if TYPE_CHECKING:
    import sqlite3
    from datetime import datetime

    from canopy.core.config import Trust

#: The file in a feedback planner's desk that holds its PRs' items, as the `vcs` source observed them: data to it.
ITEMS = ".canopy-feedback.json"
#: The file in a feedback planner's desk that says what changed since the plan it replaces: data to it.
CHANGES = ".canopy-feedback-changes.json"
#: The most changes a refusal names one by one.
MAX_SAID = 10

#: An item or a reply by its PR, its kind, and the id the `vcs` source observed.
type Key = tuple[str, ReviewItem, int]


class Changed(StrEnum):
    """What changed on a plan's PR since the plan saw it (DESIGN §32, Planning again)."""

    #: The PR's head moved.
    HEAD = "head"
    #: A check's conclusion at the head changed.
    CHECK = "check"
    #: A review, or a thread's first comment, the plan was not given.
    NEW = "new"
    #: A comment on a thread the plan was given, answering that thread's item.
    REPLY = "reply"
    #: An item the plan covers, or one a `resume` went ahead on, was edited: its body's hash changed.
    EDITED = "edited"
    #: A thread the plan covers was resolved.
    RESOLVED = "resolved"


@dataclass(frozen=True)
class Offered:
    """A review or review comment on one of a plan's PRs as the `vcs` source observed it: an item, or a reply to one."""

    pr_url: str
    item: ReviewItem
    id: int
    author: str | None
    #: Whether its author is the PR's, as the reader observed the PR.
    pr_author: bool
    #: Whether `trust.trusted_reviewers` names its author: shown to the operator, and never a gate (DESIGN §32).
    trusted: bool
    bot: bool
    state: ReviewState | None
    created_at: str | None
    url: str | None
    thread_id: str | None
    path: str | None
    line: int | None
    outdated: bool | None
    #: Its text, cut as a mirrored comment's is: model or human text, data to the planner, whoever wrote it.
    body: str
    #: An item's thread's other comments, oldest first, each given beside it as a reply: none for a reply or a review.
    replies: Sequence[Offered] = ()


@dataclass(frozen=True)
class Snapshot:
    """What a feedback plan's run read of its PRs before the planner started, recorded with the plan (`record`)."""

    #: Each PR's head, by URL; None where the reader did not say.
    heads: Mapping[str, str | None]
    #: Each check's conclusion at its PR's head, by PR and check name.
    checks: Mapping[tuple[str, str], CheckConclusion | None]
    #: The items the planner was given, each with its replies.
    given: Sequence[Offered]


@dataclass(frozen=True)
class Change:
    """One thing that changed on a plan's PR since the plan saw it, in the harness's words: never an item's text."""

    changed: Changed
    pr_url: str
    #: The item or reply it is about, by its observed id; None for the head and a check.
    item: ReviewItem | None = None
    id: int | None = None
    #: A reply's: the id of the item it answers.
    answers: int | None = None
    author: str | None = None
    pr_author: bool = False
    trusted: bool = False
    #: A check's name.
    name: str | None = None
    #: The head, or a check's conclusion, as the plan saw it and as it is now.
    was: str | None = None
    now: str | None = None
    #: A new or edited item's or reply's body hash as the reads hold it now: what tells one edit from the next.
    body_sha256: str | None = None

    def said(self) -> str:
        """Return the change in the harness's words, for a refusal or a note.

        Returns:
            One clause naming the PR and what changed on it.
        """
        pr = self.pr_url
        match self.changed:
            case Changed.HEAD:
                return f"{pr}'s head moved from {_short(self.was)} to {_short(self.now)}"
            case Changed.CHECK:
                return f"check {self.name} on {pr} went from {self.was or 'no conclusion'} to {self.now or 'none yet'}"
            case Changed.NEW:
                return f"new {self.item} {self.id} on {pr} by {self._who()}"
            case Changed.REPLY:
                return f"reply {self.id} on {pr} by {self._who()}, answering item {self.answers}"
            case Changed.EDITED:
                what = f"item {self.id}" if self.answers is None else f"reply {self.id}"
                answering = "" if self.answers is None else f", answering item {self.answers},"
                return f"{what} on {pr}{answering} was edited"
            case Changed.RESOLVED:
                return f"item {self.id}'s thread on {pr} was resolved"
            case _:
                assert_never(self.changed)

    def to_json(self) -> dict[str, object]:
        """Return the change as the desk's changes file holds it: only the fields it has.

        Returns:
            One JSON object.
        """
        found: dict[str, object] = {"changed": str(self.changed), "pr": self.pr_url}
        if self.id is not None:
            found |= {"item": str(self.item), "id": self.id}
        if self.answers is not None:
            found["answers"] = self.answers
        if self.changed in (Changed.NEW, Changed.REPLY):
            found |= {"author": self.author, "pr_author": self.pr_author, "trusted": self.trusted}
        if self.name is not None:
            found["name"] = self.name
        if self.changed in (Changed.HEAD, Changed.CHECK):
            found |= {"was": self.was, "now": self.now}
        return found

    def _who(self) -> str:
        marks = [m for m, on in (("the PR's author", self.pr_author), ("trusted", self.trusted)) if on]
        return ", ".join([self.author or "an unknown author", *marks])


def offered(conn: sqlite3.Connection, trust: Trust, key: str, prs: Sequence[str]) -> list[Offered]:
    """Return each item on `prs` a feedback plan of `key` may cover, with its replies, as the journal's reads hold them.

    That is every review with text or asking for changes, and every thread not resolved, but those a `resume` went
    ahead on whose body and replies are as the plan that covered them saw them. Feedback is not split by reviewer: the
    trust of each item's author is shown, not used (DESIGN §32).

    Returns:
        The items, by PR in the order given, then oldest first.
    """
    sent = drafts.sent_by_pr(conn)
    handled = _Handled(conn, key)
    found: list[Offered] = []
    for pr in prs:
        author = _pr_author(conn, pr)
        found.extend(
            _offer(thread.row, author, trust, replies=thread.replies)
            for thread in _threads(conn, trust, key, pr, sent.get(pr, {}))
            if not handled.still(thread)
        )
    return found


def items_file(items: Iterable[Offered]) -> str:
    """Return the desk's items file: each item as JSON, its replies beside it, all of it data to the planner."""
    return json.dumps([_item_json(o) for o in items], indent=1)


def take(conn: sqlite3.Connection, prs: Iterable[str], given: Sequence[Offered]) -> Snapshot:
    """Return what the journal's latest reads hold of `prs`, with the items `given` to a planner: its snapshot.

    Returns:
        Each PR's head, the conclusion of each check at it, and the items given.
    """
    heads: dict[str, str | None] = {}
    checks: dict[tuple[str, str], CheckConclusion | None] = {}
    for pr in prs:
        observed = records.fetch_one(
            conn,
            records.ObservedPr,
            sql.select("*").from_("observed_prs").where("url = ?", pr),
        )
        head = None if observed is None else observed.head_sha
        heads[pr] = head
        for check in _checks_at(conn, pr, head):
            checks[pr, check.name] = check.conclusion
    return Snapshot(heads=heads, checks=checks, given=given)


def record(conn: sqlite3.Connection, plan_id: int, snapshot: Snapshot) -> None:
    """Record `snapshot` as what feedback plan `plan_id` saw. Call inside the transaction that records the plan."""
    sql.execute_many(
        conn,
        sql.insert_rows("feedback_plan_prs", ("plan_id", "pr_url", "head_sha")),
        [(plan_id, pr, head) for pr, head in snapshot.heads.items()],
    )
    sql.execute_many(
        conn,
        sql.insert_rows("feedback_plan_checks", ("plan_id", "pr_url", "name", "conclusion")),
        [(plan_id, pr, name, conclusion) for (pr, name), conclusion in snapshot.checks.items()],
    )
    rows = [
        (plan_id, o.pr_url, o.item, o.id, o.thread_id, o.author, _sha(o.body), answers)
        for item in snapshot.given
        for o, answers in [(item, None), *((r, item.id) for r in item.replies)]
    ]
    sql.execute_many(
        conn,
        sql.insert_rows(
            "feedback_plan_seen",
            ("plan_id", "pr_url", "item", "item_id", "thread_id", "author", "body_sha256", "answers"),
        ),
        rows,
    )


def changes(conn: sqlite3.Connection, trust: Trust, plan: records.FeedbackPlan) -> list[Change]:
    """Return what changed on `plan`'s PRs since it saw them, as the journal's latest reads hold them (DESIGN §32).

    A head that moved; a check whose conclusion at an unmoved head changed; a review or thread the plan was not given;
    a reply on a thread it was given, named as answering that thread's item; an item it covers edited or its thread
    resolved; and an item a `resume` went ahead on, edited since. A plan recorded before snapshots were has none.

    Returns:
        The changes, heads and checks first, then by PR and item, oldest first; empty when the plan is not stale.
    """
    heads = records.fetch_all(
        conn,
        records.FeedbackPlanPr,
        sql.select("*").from_("feedback_plan_prs").where("plan_id = ?", plan.id).order_by("pr_url"),
    )
    if not heads:
        return []
    found = [c for h in heads for c in _moved(conn, plan.id, h)]
    seen = _seen(conn, plan.id)
    sent = drafts.sent_by_pr(conn)
    handled = _Handled(conn, plan.ticket_key)
    for h in heads:
        author = _pr_author(conn, h.pr_url)
        for thread in _threads(conn, trust, plan.ticket_key, h.pr_url, sent.get(h.pr_url, {})):
            if not handled.still(thread):
                found += _arrived(thread, seen, handled.seen_by(thread.row), author, trust)
    found += _covered(conn, plan.id, seen)
    return found


def prs_of(conn: sqlite3.Connection, plan_id: int) -> list[str]:
    """The PRs feedback plan `plan_id` read, as its snapshot holds them.

    Returns:
        Their URLs, in order; none for a plan recorded before snapshots were.
    """
    rows = sql.execute(
        conn,
        sql.select("pr_url").from_("feedback_plan_prs").where("plan_id = ?", plan_id).order_by("pr_url"),
    )
    return [str(r[0]) for r in rows]


def said(found: Sequence[Change]) -> str:
    """Return `found` in the harness's words, the first `MAX_SAID` one by one.

    Returns:
        The changes, joined by semicolons.
    """
    named = "; ".join(c.said() for c in found[:MAX_SAID])
    more = f"; and {len(found) - MAX_SAID} more" if len(found) > MAX_SAID else ""
    return named + more


def digest(found: Iterable[Change]) -> str:
    """Return a SHA-256 of `found`, so a refusal shown for them can be told from one for something else.

    It covers what each change is made of, a body's hash and a head's or a check's value among it, not only the words a
    refusal shows: a second edit to the same item is another change.

    Returns:
        The hex digest.
    """
    return _sha(json.dumps([astuple(c) for c in found]))


def changes_file(found: Iterable[Change]) -> str:
    """Return the desk's changes file: each change as JSON, by id, never an item's text, which the items file holds."""
    return json.dumps([c.to_json() for c in found], indent=1)


def newest(conn: sqlite3.Connection, trust: Trust, prs: Collection[str]) -> datetime | None:
    """Return when the newest item or reply on `prs` was made, as their reader says.

    Returns:
        The moment, or None when they have no item or reply with a time.
    """
    sent = drafts.sent_by_pr(conn)
    found: datetime | None = None
    for pr in prs:
        for thread in _threads(conn, trust, None, pr, sent.get(pr, {})):
            for row in (thread.row, *thread.replies):
                at = _time(row.created_at)
                if at is not None and (found is None or at > found):
                    found = at
    return found


def record_values(conn: sqlite3.Connection, plan_id: int, prs: Iterable[str], now: str) -> None:
    """Record each head and check conclusion of a waiting plan's `prs` as the reads hold them, first seen `now`.

    A head or check that keeps its value keeps its time; one that takes another value, or takes back one it held
    before, is timed `now`, so each new push or flap of a check starts the quiet period again (DESIGN §32, Planning
    again). Call after every read that may move them, each tick.
    """
    rows: list[tuple[int, str, MoveKind, str, str, str]] = []
    for pr in prs:
        found = records.fetch_one(conn, records.ObservedPr, sql.select("*").from_("observed_prs").where("url = ?", pr))
        if found is None:
            continue
        rows.append((plan_id, pr, MoveKind.HEAD, "", found.head_sha or "", now))
        rows.extend(
            (plan_id, pr, MoveKind.CHECK, c.name, _str(c.conclusion) or "", now)
            for c in _checks_at(conn, pr, found.head_sha)
        )
    sql.execute_many(
        conn,
        sql.insert_rows("feedback_plan_moves", ("plan_id", "pr_url", "kind", "name", "value", "seen_at")).on_conflict(
            "(plan_id, pr_url, kind, name) DO UPDATE SET value = excluded.value, seen_at = excluded.seen_at "
            "WHERE value != excluded.value",
        ),
        rows,
    )


def moved_at(conn: sqlite3.Connection, plan_id: int, found: Iterable[Change], now: datetime) -> datetime | None:
    """Return when the harness saw the newest of the heads and check conclusions among `found` take their value.

    Returns:
        The moment; `now` for one whose value it has not recorded yet; None when `found` holds no head or check.
    """
    held = {
        (m.pr_url, m.kind, m.name): m
        for m in records.fetch_all(
            conn,
            records.FeedbackPlanMove,
            sql.select("*").from_("feedback_plan_moves").where("plan_id = ?", plan_id),
        )
    }
    latest: datetime | None = None
    for c in found:
        kind = _move(c)
        if kind is None:
            continue
        row = held.get((c.pr_url, kind, c.name or ""))
        at = (_time(row.seen_at) if row is not None and row.value == (c.now or "") else None) or now
        latest = at if latest is None or at > latest else latest
    return latest


def _move(change: Change) -> MoveKind | None:
    match change.changed:
        case Changed.HEAD:
            return MoveKind.HEAD
        case Changed.CHECK:
            return MoveKind.CHECK
        case Changed.NEW | Changed.REPLY | Changed.EDITED | Changed.RESOLVED:
            return None
        case _:
            assert_never(change.changed)


@dataclass(frozen=True)
class _Thread:
    """An item as the reads hold it: a review, or a thread's item comment, with the thread's other comments."""

    row: records.ObservedReview
    replies: Sequence[records.ObservedReview] = ()


def _threads(
    conn: sqlite3.Connection,
    trust: Trust,
    key: str | None,
    pr: str,
    sent: Mapping[str, Sequence[int]],
) -> list[_Thread]:
    """Return the items on `pr`, each thread one, as the journal's latest whole read holds them.

    A thread's item is the comment on it a feedback plan of `key` covered, the first if several were, or else its first
    comment; its other comments are its replies. Without `key`, every thread's item is its first comment.

    Returns:
        The items, oldest first.
    """
    rows = records.fetch_all(
        conn,
        records.ObservedReview,
        sql.select("*").from_("observed_reviews").where("pr_url = ?", pr).order_by("created_at, item, id"),
    )
    kept = [r for r in rows if not _skipped(r, trust, sent)]
    covered = _covered_comments(conn, key, pr) if key is not None else frozenset[int]()
    by_thread: dict[str, list[records.ObservedReview]] = {}
    for r in kept:
        if r.item is ReviewItem.COMMENT:
            by_thread.setdefault(r.thread_id or "", []).append(r)
    heads: dict[str, records.ObservedReview] = {}
    for thread_id, comments in by_thread.items():
        mine = [c for c in comments if c.id in covered]
        heads[thread_id] = min(mine, key=lambda c: c.id) if mine else comments[0]
    found: list[_Thread] = []
    for r in kept:
        if r.item is ReviewItem.REVIEW:
            found.append(_Thread(r))
            continue
        thread_id = r.thread_id or ""
        if heads[thread_id] is r:
            found.append(_Thread(r, tuple(c for c in by_thread[thread_id] if c is not r)))
    return found


def _skipped(row: records.ObservedReview, trust: Trust, sent: Mapping[str, Sequence[int]]) -> bool:
    """Whether an observed row is neither an item for a plan nor a reply to one.

    Returns:
        True for the operator's own reply sent through canopy, a worker's comment, a pending review, a comment on a
        resolved thread, or a review that says nothing of its own.
    """
    if row.item is ReviewItem.COMMENT:
        return row.id in sent.get("comments", ()) or bool(row.resolved) or _marked(row.body, trust)
    if row.id in sent.get("reviews", ()) or row.state is ReviewState.PENDING:
        return True
    return (not row.body.strip() and row.state is not ReviewState.CHANGES_REQUESTED) or _marked(row.body, trust)


def _marked(body: str, trust: Trust) -> bool:
    """Whether `body` carries a worker's marks (D069).

    Returns:
        True when it carries every mark the operator set, and there is one.
    """
    prefix, suffix = trust.comment_prefix, trust.comment_suffix
    if not prefix and not suffix:
        return False
    return body.lstrip().startswith(prefix) and body.rstrip().endswith(suffix)


def _covered_comments(conn: sqlite3.Connection, key: str, pr: str) -> frozenset[int]:
    """The review comments on `pr` a feedback plan of `key` covered, whatever became of the plan.

    Returns:
        Their observed ids.
    """
    rows = sql.execute(
        conn,
        sql.select("i.item_id")
        .from_("feedback_plan_items i")
        .join("feedback_plans p ON p.id = i.plan_id")
        .where("p.ticket_key = ? AND i.pr_url = ? AND i.item = ?", key, pr, ReviewItem.COMMENT),
    )
    return frozenset(int(r[0]) for r in rows)


class _Handled:
    """The items of a ticket a `resume` went ahead on, and what the plan that covered each saw of it.

    The approval is spent when the `resume` is recorded, before its worker does anything, so an item counts as handled
    only while that run works or once it ended `done` or `blocked`. A resume that failed, crashed, timed out, was
    stopped, or never started hands its items back to the next plan, rather than dropping them unseen.
    """

    def __init__(self, conn: sqlite3.Connection, key: str) -> None:
        self._conn = conn
        rows = sql.execute(
            conn,
            sql.select("i.pr_url, i.item, i.item_id, max(p.id)")
            .from_("feedback_plan_items i")
            .join("feedback_plans p ON p.id = i.plan_id")
            .join("runs r ON r.id = p.spent_run_id")
            .where("p.ticket_key = ?", key)
            .where_in("r.status", (RunStatus.RUNNING, RunStatus.DONE, RunStatus.BLOCKED))
            .group_by("i.pr_url, i.item, i.item_id"),
        )
        #: The plan that last covered each handled item.
        self._by: dict[Key, int] = {(str(r[0]), ReviewItem(r[1]), int(r[2])): int(r[3]) for r in rows}
        self._seen: dict[int, dict[Key, records.FeedbackPlanSeen]] = {}

    def still(self, thread: _Thread) -> bool:
        """Whether `thread`'s item is handled, its body and replies as the plan that covered it saw them.

        Returns:
            True when a `resume` went ahead on it, and nothing on it changed since; a plan recorded before snapshots
            were saw nothing to compare, so its items stay handled.
        """
        plan_id = self._by.get(_key(thread.row))
        if plan_id is None:
            return False
        seen = self._of(plan_id)
        if not seen:
            return True
        return all(_unchanged(row, seen) for row in (thread.row, *thread.replies))

    def seen_by(self, row: records.ObservedReview) -> Mapping[Key, records.FeedbackPlanSeen]:
        """What the plan that last covered `row`'s item, with a `resume` gone ahead on it, saw.

        Returns:
            Its snapshot's items and replies, by key; empty when no such plan covered it.
        """
        plan_id = self._by.get(_key(row))
        return {} if plan_id is None else self._of(plan_id)

    def _of(self, plan_id: int) -> dict[Key, records.FeedbackPlanSeen]:
        if plan_id not in self._seen:
            self._seen[plan_id] = _seen(self._conn, plan_id)
        return self._seen[plan_id]


def _seen(conn: sqlite3.Connection, plan_id: int) -> dict[Key, records.FeedbackPlanSeen]:
    """What feedback plan `plan_id` was given, by key.

    Returns:
        Its snapshot's items and replies.
    """
    rows = records.fetch_all(
        conn,
        records.FeedbackPlanSeen,
        sql.select("*").from_("feedback_plan_seen").where("plan_id = ?", plan_id),
    )
    return {(r.pr_url, r.item, r.item_id): r for r in rows}


def _unchanged(row: records.ObservedReview, seen: Mapping[Key, records.FeedbackPlanSeen]) -> bool:
    """Whether a plan saw `row`, with the body it has now.

    Returns:
        True when its snapshot holds it with the same body hash.
    """
    then = seen.get(_key(row))
    return then is not None and then.body_sha256 == _sha(row.body)


def _key(row: records.ObservedReview) -> Key:
    return (row.pr_url, row.item, row.id)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _pr_author(conn: sqlite3.Connection, pr: str) -> str | None:
    found = sql.execute(conn, sql.select("author").from_("observed_prs").where("url = ?", pr)).fetchone()
    return None if found is None or found[0] is None else str(found[0])


def _offer(
    row: records.ObservedReview,
    pr_author: str | None,
    trust: Trust,
    *,
    replies: Iterable[records.ObservedReview] = (),
) -> Offered:
    return Offered(
        pr_url=row.pr_url,
        item=row.item,
        id=row.id,
        author=row.author,
        pr_author=row.author is not None and row.author == pr_author,
        trusted=row.author is not None and row.author in trust.trusted_reviewers,
        bot=row.bot,
        state=row.state,
        created_at=row.created_at,
        url=row.url,
        thread_id=row.thread_id,
        path=row.path,
        line=row.line,
        outdated=row.outdated,
        body=row.body,
        replies=tuple(_offer(r, pr_author, trust) for r in replies),
    )


def _item_json(o: Offered) -> dict[str, object]:
    found: dict[str, object] = {
        "id": o.id,
        "pr": o.pr_url,
        "item": str(o.item),
        "author": o.author,
        "pr_author": o.pr_author,
        "trusted": o.trusted,
        "bot": o.bot,
        "state": None if o.state is None else str(o.state),
        "created_at": o.created_at,
        "url": o.url,
        "path": o.path,
        "line": o.line,
        "outdated": o.outdated,
        "body": o.body,
    }
    if o.item is ReviewItem.COMMENT:
        found["replies"] = [
            {
                "id": r.id,
                "author": r.author,
                "pr_author": r.pr_author,
                "trusted": r.trusted,
                "bot": r.bot,
                "created_at": r.created_at,
                "url": r.url,
                "body": r.body,
            }
            for r in o.replies
        ]
    return found


def _checks_at(conn: sqlite3.Connection, pr: str, head: str | None) -> list[records.ObservedCheck]:
    """The checks the reads hold at `pr`'s `head`, by name.

    Returns:
        Their rows; none without a head.
    """
    if head is None:
        return []
    return records.fetch_all(
        conn,
        records.ObservedCheck,
        sql.select("*").from_("observed_checks").where("pr_url = ? AND head_sha = ?", pr, head).order_by("name"),
    )


def _moved(conn: sqlite3.Connection, plan_id: int, then: records.FeedbackPlanPr) -> list[Change]:
    """What changed at a plan's PR's head: the head itself, or the checks at it while it did not move.

    Returns:
        The head's move, or each check whose conclusion changed; empty while the reads hold nothing of the PR.
    """
    pr = then.pr_url
    observed = records.fetch_one(conn, records.ObservedPr, sql.select("*").from_("observed_prs").where("url = ?", pr))
    if observed is None:
        return []
    if observed.head_sha != then.head_sha:
        return [Change(Changed.HEAD, pr, was=then.head_sha, now=observed.head_sha)]
    was = {
        c.name: c.conclusion
        for c in records.fetch_all(
            conn,
            records.FeedbackPlanCheck,
            sql.select("*").from_("feedback_plan_checks").where("plan_id = ? AND pr_url = ?", plan_id, pr),
        )
    }
    return [
        Change(Changed.CHECK, pr, name=c.name, was=_str(was.get(c.name)), now=_str(c.conclusion))
        for c in _checks_at(conn, pr, observed.head_sha)
        if c.conclusion != was.get(c.name)
    ]


def _str(value: CheckConclusion | None) -> str | None:
    return None if value is None else str(value)


def _arrived(
    thread: _Thread,
    seen: Mapping[Key, records.FeedbackPlanSeen],
    handler: Mapping[Key, records.FeedbackPlanSeen],
    pr_author: str | None,
    trust: Trust,
) -> list[Change]:
    """What arrived on an item a plan may cover since the plan saw it: the item itself, or replies on its thread.

    `handler` is what the plan that a `resume` went ahead on for this item saw, if one did: an item it saw is not new,
    but edited if its body changed, and a reply it saw is not new either.

    Returns:
        The item, new or edited, then each reply neither plan saw.
    """
    row = thread.row
    found: list[Change] = []
    if _key(row) not in seen:
        then = handler.get(_key(row))
        if then is None:
            found.append(_by(Changed.NEW, row, pr_author, trust))
        elif then.body_sha256 != _sha(row.body):
            found.append(_edited(row))
    for reply in thread.replies:
        then = seen.get(_key(reply)) or handler.get(_key(reply))
        if then is None:
            found.append(_by(Changed.REPLY, reply, pr_author, trust, answers=row.id))
        elif then.body_sha256 != _sha(reply.body):
            found.append(_edited(reply, answers=row.id))
    return found


def _edited(row: records.ObservedReview, *, answers: int | None = None) -> Change:
    """An item, or a reply to item `answers`, whose body changed since a plan saw it.

    Returns:
        The change, with the body's hash as it is now.
    """
    return Change(Changed.EDITED, row.pr_url, item=row.item, id=row.id, answers=answers, body_sha256=_sha(row.body))


def _by(
    changed: Changed,
    row: records.ObservedReview,
    pr_author: str | None,
    trust: Trust,
    *,
    answers: int | None = None,
) -> Change:
    """A new item or reply, named with its author, and whether they are the PR's author and trusted.

    Returns:
        The change.
    """
    return Change(
        changed,
        row.pr_url,
        item=row.item,
        id=row.id,
        answers=answers,
        author=row.author,
        pr_author=row.author is not None and row.author == pr_author,
        trusted=row.author is not None and row.author in trust.trusted_reviewers,
        body_sha256=_sha(row.body),
    )


def _covered(conn: sqlite3.Connection, plan_id: int, seen: Mapping[Key, records.FeedbackPlanSeen]) -> list[Change]:
    """What changed of the items a plan covers: an edited body, or a resolved thread.

    Returns:
        A change for each, in the plan's order; an item the reads no longer hold has none.
    """
    found: list[Change] = []
    covered = records.fetch_all(
        conn,
        records.FeedbackPlanItem,
        sql.select("*").from_("feedback_plan_items").where("plan_id = ?", plan_id).order_by("number"),
    )
    for i in covered:
        row = records.fetch_one(
            conn,
            records.ObservedReview,
            sql.select("*")
            .from_("observed_reviews")
            .where("pr_url = ? AND item = ? AND id = ?", i.pr_url, i.item, i.item_id),
        )
        then = seen.get((i.pr_url, i.item, i.item_id))
        if row is None or then is None:
            continue
        if row.resolved:
            found.append(Change(Changed.RESOLVED, i.pr_url, item=i.item, id=i.item_id))
        elif _sha(row.body) != then.body_sha256:
            found.append(_edited(row))
    return found


def _short(sha: str | None) -> str:
    return "none" if sha is None else sha[:12]


def _time(stamp: str | None) -> datetime | None:
    """The moment a reader's time names.

    Returns:
        The moment, or None when it names none canopy can read.
    """
    if stamp is None:
        return None
    try:
        return db.parse_time(stamp)
    except ValueError:
        return None
