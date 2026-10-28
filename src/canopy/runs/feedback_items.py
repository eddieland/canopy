"""What a feedback plan is offered of its PRs, what it saw of them, and what changed since (DESIGN §32).

An item is a review, or a thread of review comments, on one of a ticket's PRs, as the `vcs` source last read the PR
whole (DESIGN §29, §30). A thread is one item: the comment a feedback plan of the ticket covered, or else its first
comment, with each other comment on it a reply given beside it, so a reviewer's "never mind" or the PR author's "won't
do" reaches the planner as an answer to the item, never as work of its own. The operator's replies sent through canopy,
a worker's comments (D069), pending reviews, resolved threads, and reviews that say nothing are neither. A failed check
at a PR's head, but one its repository says is not CI, the PR's conflict with its base, and a merged blocker, another
ticket's PR that the PR is stacked on and that merged (DESIGN §10), are items too (`raised`), by ids canopy gives them
(`check_id`, `conflict_id`, `blocker_id`), since the source observes none.

When a feedback plan is recorded, what its run's read saw is recorded with it (`take`, `record`): each PR's head, each
CI check's conclusion at that head, and each item and reply the planner was given, by id with a SHA-256 of its body,
never its text: a check its repository gives another role (`not_ci`) is neither recorded nor compared. An item a
`resume` went ahead on stays handled while its body and its thread's replies are as that plan saw them; once either
changed, it is offered again. So the next round is what is new since the last plan, with the items a
failed `resume` handed back, those an approval left out, and those no plan covered. A plan is stale when what the
connectors observe now differs from what it saw (`changes`), each difference with its reason, computed here in code;
the quiet period before a stale plan is planned again runs from the newest item or reply on its PRs, or from when the
harness first saw the head or check conclusion they moved to, the newer (`newest`, `moved_at`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import astuple, dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, assert_never

from canopy.core import db, observe, records, sql
from canopy.core.vocab import (
    CheckConclusion,
    CheckStatus,
    MoveKind,
    PlanItem,
    PrState,
    ReviewItem,
    ReviewState,
    RunStatus,
)
from canopy.core.workspace import CheckRole
from canopy.runs import drafts

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Set as AbstractSet
    from datetime import datetime

    from canopy.core.config import Trust
    from canopy.core.workspace import Workspace

#: The file in a feedback planner's desk that holds its PRs' items, as the `vcs` source observed them: data to it.
ITEMS = ".canopy-feedback.json"
#: The file in a feedback planner's desk that says what changed since the plan it replaces: data to it.
CHANGES = ".canopy-feedback-changes.json"
#: The most changes a refusal names one by one.
MAX_SAID = 10

#: An item or a reply by its PR, its kind, and its id: the one the `vcs` source observed, or the one canopy gave it.
type Key = tuple[str, PlanItem, int]
#: How many bits of a SHA-256 a failed check's, a conflict's, or a merged blocker's id takes: few enough to stay an
#: exact number in JSON and JavaScript, and enough that two of a PR's never share one.
_ID_BITS = 48


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
    #: The PR came to conflict with its base, or no longer does, at a head that did not move.
    CONFLICT = "conflict"
    #: The PR's blocker merged under it, or it is no longer stacked on one that did, at a head that did not move.
    BLOCKER = "blocker"


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
    #: Its text, cut as a tracker comment's is: model or human text, data to the planner, whoever wrote it.
    body: str
    #: An item's thread's other comments, oldest first, each given beside it as a reply: none for a reply or a review.
    replies: Sequence[Offered] = ()


@dataclass(frozen=True)
class Raised:
    """A failed check at a PR's head, its conflict with its base, or its merged blocker: an item with an id canopy gave.

    None has an author, so none has a reply; a check's name and link are as the `vcs` source observed them, data to the
    planner.
    """

    pr_url: str
    item: PlanItem
    id: int
    head_sha: str
    #: A check's name, its conclusion, and its link; None for a conflict.
    name: str | None = None
    conclusion: CheckConclusion | None = None
    url: str | None = None
    #: The base branch a conflict is with, or the merged blocker's branch the PR still targets, as the reader said;
    #: None for a check.
    base_ref: str | None = None
    #: A merged blocker's ticket, and its PR that merged; None for any other item.
    blocker: str | None = None
    blocker_pr: str | None = None


#: Anything a feedback plan may cover: a review item, or a failed check, a conflict, or a merged blocker.
type Item = Offered | Raised


@dataclass(frozen=True)
class Snapshot:
    """What a feedback plan's run read of its PRs before the planner started, recorded with the plan (`record`)."""

    #: Each PR's head, by URL; None where the reader did not say.
    heads: Mapping[str, str | None]
    #: Each CI check's conclusion at its PR's head, by PR and check name: one its repository gives another role is
    #: left out, so none of its moves makes the plan stale (DESIGN §30).
    checks: Mapping[tuple[str, str], CheckConclusion | None]
    #: The review items the planner was given, each with its replies.
    given: Sequence[Offered]
    #: Whether each PR conflicted with its base, by URL; None where its host had not said.
    conflicts: Mapping[str, bool | None]
    #: The merged PR each PR was stacked on, its blocker's, by URL; None where it was on none.
    blockers: Mapping[str, str | None] = field(default_factory=dict[str, str | None])


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

    def said(self) -> str:  # noqa: PLR0911 - one return for each kind of change
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
            case Changed.CONFLICT:
                return f"{pr} now conflicts with its base" if self.now else f"{pr} no longer conflicts with its base"
            case Changed.BLOCKER:
                if self.now:
                    return f"{pr}'s blocker {self.now} merged"
                return f"{pr} is no longer stacked on {self.was}, which merged"
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
        if self.changed in (Changed.HEAD, Changed.CHECK, Changed.CONFLICT, Changed.BLOCKER):
            found |= {"was": self.was, "now": self.now}
        return found

    def _who(self) -> str:
        marks = [m for m, on in (("the PR's author", self.pr_author), ("trusted", self.trusted)) if on]
        return ", ".join([self.author or "an unknown author", *marks])


def offered(conn: sqlite3.Connection, trust: Trust, key: str, prs: Sequence[str]) -> list[Offered]:
    """Return each review item on `prs` a feedback plan of `key` may cover, with its replies, as the reads hold them.

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


def raised(
    conn: sqlite3.Connection,
    key: str,
    prs: Sequence[str],
    not_ci: Mapping[str, AbstractSet[str]],
) -> list[Raised]:
    """Return each failed check, conflict, and merged blocker on `prs` a feedback plan of `key` may cover, as read.

    A failed check is one completed red at its PR's head, but one `not_ci` names for that PR: those wait on a person,
    gate the merge, or are ignored, and are not CI (DESIGN §30). A conflict is the PR's with its base, while its host
    says so. A merged blocker is another ticket's PR, merged, whose branch the open PR still targets (DESIGN §10). A
    `resume` that went ahead on one handled it while the PR's head is where it was, since its id names that head.

    Returns:
        The items, by PR in the order given, each PR's checks by name, then its conflict, then its merged blocker.
    """
    handled = _Handled(conn, key)
    found: list[Raised] = []
    for pr in prs:
        observed = records.fetch_one(
            conn,
            records.ObservedPr,
            sql.select("*").from_("observed_prs").where("url = ?", pr),
        )
        if observed is None or observed.head_sha is None:
            continue
        head = observed.head_sha
        skip = not_ci.get(pr, frozenset[str]())
        found.extend(
            Raised(pr, PlanItem.CHECK, check_id(pr, head, c.name), head, c.name, c.conclusion, c.url)
            for c in _checks_at(conn, pr, head)
            if c.name not in skip and c.status is CheckStatus.COMPLETED and c.conclusion in observe.FAILED
        )
        if observe.conflicts(observed):
            base = observed.base_ref
            found.append(Raised(pr, PlanItem.CONFLICT, conflict_id(pr, head, base), head, base_ref=base))
        blocker = _merged_blocker(conn, observed)
        if blocker is not None:
            ticket, merged = blocker
            found.append(
                Raised(
                    pr,
                    PlanItem.BLOCKER,
                    blocker_id(pr, head, merged),
                    head,
                    base_ref=observed.base_ref,
                    blocker=ticket,
                    blocker_pr=merged,
                ),
            )
    return [r for r in found if not handled.has((r.pr_url, r.item, r.id))]


def not_ci(conn: sqlite3.Connection, ws: Workspace, prs: Iterable[str]) -> dict[str, frozenset[str]]:
    """Return the checks each of `prs`'s repository gives a role other than CI, by PR (DESIGN §30).

    None of them is a feedback plan's item (`raised`) or part of what a plan saw (`take`, `changes`): a check that
    waits on a person, gates the merge, or is ignored makes no plan stale when it moves. A PR's repository is that of
    the ticket's unit whose PR it is.

    Returns:
        Their names, by PR URL; none for a PR no unit has, or whose repository the map does not have.
    """
    rows = sql.execute(conn, sql.select("pr_url, repo").from_("ticket_units").where_in("pr_url", tuple(prs)))
    found: dict[str, frozenset[str]] = {}
    for row in rows:
        roles = ws.check_roles(str(row[1]))
        found[str(row[0])] = frozenset(name for name, role in roles.items() if role is not CheckRole.CI)
    return found


def check_id(pr: str, head: str, name: str) -> int:
    """Return the id canopy gives the check named `name` at `pr`'s `head`, as a feedback plan's item.

    Returns:
        A number below zero, the same on every read of that head.
    """
    return _raised_id(PlanItem.CHECK, pr, head, name)


def conflict_id(pr: str, head: str, base: str | None) -> int:
    """Return the id canopy gives `pr`'s conflict with its `base` at its `head`, as a feedback plan's item.

    Returns:
        A number below zero, the same on every read of that head against that base.
    """
    return _raised_id(PlanItem.CONFLICT, pr, head, base or "")


def blocker_id(pr: str, head: str, blocker_pr: str) -> int:
    """Return the id canopy gives `pr`'s merged blocker, the PR `blocker_pr`, at its `head`, as a feedback plan's item.

    Returns:
        A number below zero, the same on every read of that head while it is stacked on that PR.
    """
    return _raised_id(PlanItem.BLOCKER, pr, head, blocker_pr)


def blockers(conn: sqlite3.Connection, plan_id: int) -> dict[tuple[str, int], str]:
    """Return the merged PR each of a feedback plan's PRs was stacked on, by PR and the id canopy gives that blocker.

    Returns:
        The blockers' PR URLs, from the plan's snapshot; none for a plan recorded before blockers were items.
    """
    heads = records.fetch_all(
        conn,
        records.FeedbackPlanPr,
        sql.select("*").from_("feedback_plan_prs").where("plan_id = ? AND merged_blocker IS NOT NULL", plan_id),
    )
    return {
        (h.pr_url, blocker_id(h.pr_url, h.head_sha, h.merged_blocker)): h.merged_blocker
        for h in heads
        if h.head_sha is not None and h.merged_blocker is not None
    }


def check_names(conn: sqlite3.Connection, plan_id: int) -> dict[tuple[str, int], str]:
    """Return the name of each check a feedback plan saw at its PRs' heads, by PR and the id canopy gives it.

    Returns:
        The names, from the plan's snapshot; none for a plan recorded before snapshots were.
    """
    heads = records.fetch_all(
        conn,
        records.FeedbackPlanPr,
        sql.select("*").from_("feedback_plan_prs").where("plan_id = ?", plan_id),
    )
    checks = records.fetch_all(
        conn,
        records.FeedbackPlanCheck,
        sql.select("*").from_("feedback_plan_checks").where("plan_id = ?", plan_id),
    )
    at = {h.pr_url: h.head_sha for h in heads if h.head_sha is not None}
    return {(c.pr_url, check_id(c.pr_url, at[c.pr_url], c.name)): c.name for c in checks if c.pr_url in at}


def items_file(items: Iterable[Item]) -> str:
    """Return the desk's items file: each item as JSON, its replies beside it, all of it data to the planner."""
    return json.dumps([_item_json(o) if isinstance(o, Offered) else _raised_json(o) for o in items], indent=1)


def take(
    conn: sqlite3.Connection,
    prs: Iterable[str],
    given: Sequence[Offered],
    not_ci: Mapping[str, AbstractSet[str]],
) -> Snapshot:
    """Return what the journal's latest reads hold of `prs`, with the review items `given` to a planner: its snapshot.

    Returns:
        Each PR's head, the conclusion of each check at it but those `not_ci` names for that PR, whether it
        conflicted, the merged PR it was stacked on, and the items given.
    """
    heads: dict[str, str | None] = {}
    checks: dict[tuple[str, str], CheckConclusion | None] = {}
    conflicts: dict[str, bool | None] = {}
    stacked: dict[str, str | None] = {}
    for pr in prs:
        observed = records.fetch_one(
            conn,
            records.ObservedPr,
            sql.select("*").from_("observed_prs").where("url = ?", pr),
        )
        head = None if observed is None else observed.head_sha
        heads[pr] = head
        conflicts[pr] = None if observed is None else observe.conflicts(observed)
        stacked[pr] = None if observed is None else _merged_blocker_pr(conn, observed)
        skip = not_ci.get(pr, frozenset[str]())
        for check in _checks_at(conn, pr, head):
            if check.name not in skip:
                checks[pr, check.name] = check.conclusion
    return Snapshot(heads=heads, checks=checks, given=given, conflicts=conflicts, blockers=stacked)


def record(conn: sqlite3.Connection, plan_id: int, snapshot: Snapshot) -> None:
    """Record `snapshot` as what feedback plan `plan_id` saw. Call inside the transaction that records the plan."""
    sql.execute_many(
        conn,
        sql.insert_rows("feedback_plan_prs", ("plan_id", "pr_url", "head_sha", "conflicted", "merged_blocker")),
        [
            (plan_id, pr, head, snapshot.conflicts.get(pr), snapshot.blockers.get(pr))
            for pr, head in snapshot.heads.items()
        ],
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


def changes(conn: sqlite3.Connection, trust: Trust, plan: records.FeedbackPlan, ws: Workspace) -> list[Change]:
    """Return what changed on `plan`'s PRs since it saw them, as the journal's latest reads hold them (DESIGN §32).

    A head that moved; a check whose conclusion at an unmoved head changed, or a conflict with its base or a merged
    blocker that came or went there; a review or thread the plan was not given; a reply on a thread it was given, named
    as answering that thread's item; an item it covers edited or its thread resolved; and an item a `resume` went
    ahead on, edited since. A plan recorded before snapshots were has none. A check `ws` gives a role other than CI is
    compared on neither side (`not_ci`), so a snapshot that still holds one is not stale for it.

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
    skip = not_ci(conn, ws, (h.pr_url for h in heads))
    found = [c for h in heads for c in _moved(conn, plan.id, h, skip.get(h.pr_url, frozenset[str]()))]
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


def record_values(conn: sqlite3.Connection, ws: Workspace, plan_id: int, prs: Collection[str], now: str) -> None:
    """Record each head and CI check conclusion of a waiting plan's `prs` as the reads hold them, first seen `now`.

    A head or check that keeps its value keeps its time; one that takes another value, or takes back one it held
    before, is timed `now`, so each new push or flap of a check starts the quiet period again (DESIGN §32, Planning
    again). A check `ws` gives another role is not recorded: it makes no plan stale, so it holds no quiet period. Call
    after every read that may move them, each tick.
    """
    skip = not_ci(conn, ws, prs)
    rows: list[tuple[int, str, MoveKind, str, str, str]] = []
    for pr in prs:
        found = records.fetch_one(conn, records.ObservedPr, sql.select("*").from_("observed_prs").where("url = ?", pr))
        if found is None:
            continue
        rows.append((plan_id, pr, MoveKind.HEAD, "", found.head_sha or "", now))
        rows.extend(
            (plan_id, pr, MoveKind.CHECK, c.name, _str(c.conclusion) or "", now)
            for c in _checks_at(conn, pr, found.head_sha)
            if c.name not in skip.get(pr, frozenset[str]())
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
        case Changed.NEW | Changed.REPLY | Changed.EDITED | Changed.RESOLVED | Changed.CONFLICT | Changed.BLOCKER:
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
    stopped, or never started hands its items back to the next plan, rather than dropping them unseen. An item the
    operator's approval left out was never the `resume`'s to handle, so the next plan gets it too.
    """

    def __init__(self, conn: sqlite3.Connection, key: str) -> None:
        self._conn = conn
        rows = sql.execute(
            conn,
            sql.select("i.pr_url, i.item, i.item_id, max(p.id)")
            .from_("feedback_plan_items i")
            .join("feedback_plans p ON p.id = i.plan_id")
            .join("runs r ON r.id = p.spent_run_id")
            .where("p.ticket_key = ? AND NOT i.left_out", key)
            .where_in("r.status", (RunStatus.RUNNING, RunStatus.DONE, RunStatus.BLOCKED))
            .group_by("i.pr_url, i.item, i.item_id"),
        )
        #: The plan that last covered each handled item.
        self._by: dict[Key, int] = {(str(r[0]), PlanItem(r[1]), int(r[2])): int(r[3]) for r in rows}
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

    def has(self, key: Key) -> bool:
        """Whether a `resume` went ahead on the item `key`, which holds a failed check or a conflict handled.

        Its id names the head it was at, so it stays handled until a push makes a new one.

        Returns:
            True when a plan a `resume` went ahead on covered it, and the approval left it in.
        """
        return key in self._by

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
    return {(r.pr_url, PlanItem(r.item), r.item_id): r for r in rows}


def _unchanged(row: records.ObservedReview, seen: Mapping[Key, records.FeedbackPlanSeen]) -> bool:
    """Whether a plan saw `row`, with the body it has now.

    Returns:
        True when its snapshot holds it with the same body hash.
    """
    then = seen.get(_key(row))
    return then is not None and then.body_sha256 == _sha(row.body)


def _key(row: records.ObservedReview) -> Key:
    return (row.pr_url, PlanItem(row.item), row.id)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _raised_id(item: PlanItem, pr: str, head: str, what: str) -> int:
    """The id canopy gives a failed check, a conflict, or a merged blocker, which has none of the `vcs` source's.

    Returns:
        The id.
    """
    # Below zero, so it never meets an observed review's or comment's id, which the connector contract holds to 1 and
    # up (`observe`), in a plan's result line or wherever an item is named. Made of what the item is, its PR, the head,
    # and the check's name, the base, or the blocker's PR, and of nothing a read changes at that head, such as a check
    # run's id or its time: every read of the same head names the same failure by the same id, so an item a `resume`
    # handled stays handled, and one no plan covered is offered again as itself, until a push makes a new one. Two of a
    # PR's sharing one, a chance near n²/2^49 for its n items, makes `feedback_plans.match` refuse that id with a note,
    # so neither is planned until a push: a rare re-plan, never a wrong item approved, and more bits would not stay
    # exact in JSON.
    digest = hashlib.sha256(f"{item}\0{pr}\0{head}\0{what}".encode()).digest()
    return -(int.from_bytes(digest) >> (256 - _ID_BITS)) - 1


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


def _raised_json(r: Raised) -> dict[str, object]:
    found: dict[str, object] = {"id": r.id, "pr": r.pr_url, "item": str(r.item), "head_sha": r.head_sha}
    match r.item:
        case PlanItem.CHECK:
            conclusion = None if r.conclusion is None else str(r.conclusion)
            found |= {"name": r.name, "conclusion": conclusion, "url": r.url}
        case PlanItem.CONFLICT:
            found["base_ref"] = r.base_ref
        case PlanItem.BLOCKER:
            found |= {"base_ref": r.base_ref, "blocker": r.blocker, "blocker_pr": r.blocker_pr}
        case PlanItem.REVIEW | PlanItem.COMMENT:
            pass
        case _:
            assert_never(r.item)
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


def _moved(
    conn: sqlite3.Connection,
    plan_id: int,
    then: records.FeedbackPlanPr,
    not_ci: AbstractSet[str],
) -> list[Change]:
    """What changed at a plan's PR's head: the head itself, or the checks, conflict, and blocker while it did not move.

    Returns:
        The head's move, or each check but those `not_ci` names whose conclusion changed, a conflict that came or
        went, and a merged blocker that came or went; empty while the reads hold nothing of the PR.
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
    found = [
        Change(Changed.CHECK, pr, name=c.name, was=_str(was.get(c.name)), now=_str(c.conclusion))
        for c in _checks_at(conn, pr, observed.head_sha)
        if c.name not in not_ci and c.conclusion != was.get(c.name)
    ]
    # Only once the host has said now: a PR whose mergeability it is still working out has not moved. One it had not
    # settled when the plan read it was offered no conflict, so a conflict it settles since is new to the plan, and no
    # conflict is no change.
    now = observe.conflicts(observed)
    if now is not None and now != then.conflicted and (now or then.conflicted is not None):
        found.append(Change(Changed.CONFLICT, pr, was=_conflicting(then.conflicted), now=_conflicting(now)))
    # A plan recorded before blockers were items holds none, so a blocker merged under its PR since is new to it.
    stacked = _merged_blocker_pr(conn, observed)
    if stacked != then.merged_blocker:
        found.append(Change(Changed.BLOCKER, pr, was=then.merged_blocker, now=stacked))
    return found


def _merged_blocker(conn: sqlite3.Connection, pr: records.ObservedPr) -> tuple[str, str] | None:
    """The merged blocker an open PR is stacked on: another ticket's PR, merged, whose branch it still targets (§10).

    The branch is the blocker's unit's in the same repository, as canopy recorded it, and the merge as the reader last
    read the blocker's PR. A host that retargets the PR once its base's branch is deleted leaves no blocker to plan.

    Returns:
        The blocker's ticket and its PR's URL; None when the PR is not open, targets no ticket's branch, or that
        ticket's PR there has not merged.
    """
    if pr.state is not PrState.OPEN or pr.base_ref is None:
        return None
    found = sql.execute(
        conn,
        sql.select("u.ticket_key, o.url")
        .from_("ticket_units u")
        .join("observed_prs o ON o.url = u.pr_url")
        .where("u.branch = ? AND o.url != ?", pr.base_ref, pr.url)
        .where("o.repository = ? AND o.state = ?", pr.repository, PrState.MERGED)
        .order_by("o.url")
        .limit(1),
    ).fetchone()
    return None if found is None else (str(found[0]), str(found[1]))


def _merged_blocker_pr(conn: sqlite3.Connection, pr: records.ObservedPr) -> str | None:
    """The URL of the merged PR an open PR is stacked on, as `_merged_blocker` finds it.

    Returns:
        The URL; None when it is on none.
    """
    found = _merged_blocker(conn, pr)
    return None if found is None else found[1]


def _conflicting(conflicts: bool | None) -> str | None:  # noqa: FBT001
    return "conflicting" if conflicts else None


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
        sql.select("*")
        .from_("feedback_plan_items")
        .where("plan_id = ?", plan_id)
        .where_in("item", (PlanItem.REVIEW, PlanItem.COMMENT))
        .order_by("number"),
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
            found.append(Change(Changed.RESOLVED, i.pr_url, item=row.item, id=i.item_id))
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
