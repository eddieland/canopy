"""The observations in the overseer's state block (DESIGN §35, ROADMAP M37): the world as the connectors last read it.

Every ticket the block lists and every ticket the tracker query last returned is here, by key. Each is `fresh`, read
whole within `connect.max_age_minutes`; `stale`, past it or never read, naming what; or `unobserved`, when no source
covers it, as every ticket is without a `tracker` source. A fresh ticket is marked a candidate or not in code, from its
observed labels and state (§17). One that is not is listed by key and why, with none of its text, so a widened query
shows the overseer nothing of it (TRUST_MODEL T7). A fresh candidate carries its title, state, labels, and blockers, its
body until its first unit, and its new comments, each marked in code: whether its author is an authorized replier, and
whether it is a worker's (D069). Each of its units carries its PR, the checks at its head with passing CI only
counted, each person's latest verdict, and the new reviews and review comments, each marked trusted or not in code
(D089). Every subject carries the rows of §7 the tick's derivation found holding (§30): the harness's reading, which the
overseer may overrule.

Text is the observation's, as the connector's validation cut and marked it (§30). A subject shows at most
`MAX_NEW_ITEMS` new items, oldest first, and counts the rest, which stay new for a later tick. Nothing here authorizes:
it is what a connector printed, and the overseer's prompt says what it may use it for.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal, NotRequired, TypedDict, assert_never

from canopy.core import conversation, db, item_numbers, observe, records, sql
from canopy.core.vocab import CheckStatus, ReviewItem, ReviewState, SourceKind, TicketState
from canopy.core.workspace import CheckRole
from canopy.loop import phases
from canopy.reviews import review_requests

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Set as AbstractSet

    from canopy.core.context import Context

#: How many new items a subject shows, oldest first, before the rest are counted: a ticket's comments, and a unit's
#: reviews and review comments together. The rest stay new, so a later tick shows them. Chosen conservatively, for the
#: operator to set from the measurement's ticks (ROADMAP M37, Open): ten comments at their bound are about
#: 5,000 tokens, and a busier subject waits a tick rather than swelling every tick's block.
MAX_NEW_ITEMS = 10
#: Why a ticket's subject is unobserved when no source reads tickets.
NO_TRACKER = "no tracker source observes tickets"
#: How fresh a subject's observation is (DESIGN §35).
type Freshness = Literal["fresh", "stale", "unobserved"]


class ObservationsState(TypedDict):
    """The state block's `observations`: the world as the connectors last read it, each subject with its age.

    `review_query` only when `review.query` is set, and `review_prs` only where the overseer reads no GitHub itself,
    a `tracker` source running beside the `vcs` source, and reviews are on (DESIGN §39).
    """

    max_age_minutes: int
    max_new_items: int
    query: QueryState
    review_query: NotRequired[QueryState]
    #: Each PR an open review request names, then each the review query found fresh, as the `vcs` source read it.
    review_prs: NotRequired[list[ReviewPrObservation]]
    tickets: list[TicketObservation]


class QueryState(TypedDict):
    """A query's result as its source last read it to the end: tracker keys, or the review query's PR URLs.

    `why` says what is stale or unobserved; `read_at` and `result` are there whenever a run read it.
    """

    observed: Freshness
    why: NotRequired[str]
    read_at: NotRequired[str]
    result: NotRequired[list[str]]


class TicketObservation(TypedDict):
    """A ticket as the tracker source last read it. Only `key`, `observed`, and `why` when it is not fresh.

    A fresh ticket says whether it is a candidate; one that is not has only `why` besides, and nothing of its text. A
    candidate has the rest: `body` only until its first unit, `more_comments` only when some were left out, and
    `derived` only when the tick derived it. `units` are on every ticket but a fresh non-candidate.
    """

    key: str
    observed: Freshness
    why: NotRequired[str]
    candidate: NotRequired[bool]
    observed_at: NotRequired[str]
    title: NotRequired[str]
    state: NotRequired[str]
    labels: NotRequired[list[LabelState]]
    blockers: NotRequired[list[BlockerState]]
    body: NotRequired[str]
    comments: NotRequired[list[CommentState]]
    more_comments: NotRequired[int]
    derived: NotRequired[list[str]]
    units: NotRequired[list[UnitObservation]]


class LabelState(TypedDict):
    """A label on a ticket, and when it was added, None where the tracker does not say."""

    name: str
    added_at: str | None


class BlockerState(TypedDict):
    """A ticket named as blocking another, and its observed state."""

    key: str
    state: str


class CommentState(TypedDict):
    """A tracker comment, cut and marked where it was recorded. `truncated` only when it was cut.

    `number` is its journal number, what the `comment` cursor names (DESIGN §35). `authorized`: its author is in
    `trust.authorized_repliers`. `worker`: it carries the workers' marks (D069). Both are decided in code.
    """

    number: int | None
    id: str
    author: str
    at: str
    authorized: bool
    worker: bool
    body: str
    truncated: NotRequired[bool]


class UnitObservation(TypedDict):
    """One of a ticket's units as the `vcs` source last read it. Only `repo`, `observed`, and `why` when not fresh.

    A unit with a PR has `pr`, `checks`, `verdicts`, and `reviews`, `more_reviews` only when some were left out; one
    without has `branch`, the ticket's branch observed in its repository, or None. `derived` only when the tick derived
    it.
    """

    repo: str
    observed: Freshness
    why: NotRequired[str]
    observed_at: NotRequired[str]
    pr: NotRequired[PrObservation]
    branch: NotRequired[str | None]
    checks: NotRequired[ChecksState]
    verdicts: NotRequired[list[VerdictState]]
    reviews: NotRequired[list[ReviewItemState]]
    more_reviews: NotRequired[int]
    derived: NotRequired[list[str]]


class ReviewPrObservation(TypedDict):
    """A PR a review asks about, as the `vcs` source last read it. Only `url`, `observed`, and `why` when not fresh.

    Its `checks` are summed up as CI, every one: which of the workspace's repositories it is in is the overseer's to
    match, so no repository's check roles are applied.
    """

    url: str
    observed: Freshness
    why: NotRequired[str]
    observed_at: NotRequired[str]
    pr: NotRequired[PrObservation]
    checks: NotRequired[ChecksState]


class PrObservation(TypedDict):
    """A PR's state, head commit, base branch, whether it is a draft, and whether its host says it can merge."""

    url: str
    state: str | None
    head: str | None
    base: str | None
    draft: bool
    mergeable: str | None
    mergeable_state: str | None
    author: str | None


class ChecksState(TypedDict):
    """The named checks at a PR's head, summarized: CI that passed is only counted, so a busy repository's stay short.

    `stale` only when a check ended neither passing nor failing, and `human` only when a check at the head is one its
    repository says waits on a person: those are not CI, and count in none of the others. A check its repository says
    gates the merge, or ignores, is in none of them (DESIGN §30).
    """

    passed: int
    pending: list[str]
    failed: list[FailedCheck]
    stale: NotRequired[list[str]]
    human: NotRequired[list[HumanCheck]]


class FailedCheck(TypedDict):
    """A check that failed at a PR's head: what a `resume` for `ci` names, its run's journal number as the cursor."""

    number: int | None
    name: str
    conclusion: str
    run_id: int | None
    url: str | None


class HumanCheck(TypedDict):
    """A check its repository says waits on a person, at a PR's head, as it stands."""

    name: str
    status: str
    conclusion: str | None


class VerdictState(TypedDict):
    """A person's latest approval, change request, or dismissed review of a PR, at any time: a bot's never counts."""

    author: str
    state: str
    trusted: bool


class ReviewItemState(TypedDict):
    """A review or review comment past the unit's `review` cursor. `state` only on a review.

    `number` is its journal number, what the `review` cursor names (DESIGN §35). `trusted`: its author is in
    `trust.trusted_reviewers`. `worker`: it carries the workers' marks (D069). Both are decided in code.
    """

    number: int | None
    item: str
    id: int
    author: str | None
    trusted: bool
    worker: bool
    state: NotRequired[str | None]
    at: str | None
    url: str | None
    body: str


def section(
    ctx: Context,
    tick_id: int,
    now: datetime,
    tickets: Iterable[records.Ticket],
    *,
    decided: AbstractSet[str] = frozenset(),
) -> ObservationsState:
    """Read the observations of tick `tick_id` for the state block, as they stand at `now`.

    `tickets` are those the block lists: open and not stopped. The query's tickets join them, less those stopped or
    marked done, as the derivation's do (§30), and less `decided`, those the harness decided this tick (§37).

    Returns:
        The block's `observations`.
    """
    reader = Reader.read(ctx, phases.recorded(ctx.conn, tick_id), now, tickets)
    found: ObservationsState = {
        "max_age_minutes": ctx.config.connect.max_age_minutes,
        "max_new_items": MAX_NEW_ITEMS,
        "query": reader.query(SourceKind.TRACKER),
        "tickets": [reader.ticket(key) for key in reader.keys if key not in decided],
    }
    if ctx.config.review.query.strip():
        found["review_query"] = reader.query(SourceKind.VCS)
    # The overseer reads no GitHub where both sources run (§39): the PRs it reviews are read here for it.
    if ctx.config.connect.observes_all() and review_requests.reviews_on(ctx.conn, ctx.config):
        query = found.get("review_query")
        fresh = query.get("result", []) if query is not None and query["observed"] == "fresh" else []
        urls = dict.fromkeys([*(r.pr_url for r in review_requests.open_requests(ctx.conn)), *fresh])
        found["review_prs"] = [reader.review_pr(url) for url in urls]
    return found


def rendered(found: ObservationsState) -> dict[str, object]:
    """`found` as the state block renders it: each observed PR without its URL, which the block says already.

    A unit's PR is the `pr_url` of its unit in `tickets`, and a PR a review asks about has its `url` beside its `pr`.
    The claims and the harness read `found` itself, with the URLs.

    Returns:
        A copy of `found` without those URLs.
    """
    tickets = [{**t, "units": [_without_url(u) for u in t["units"]]} if "units" in t else t for t in found["tickets"]]
    shown: dict[str, object] = {**found, "tickets": tickets}
    if "review_prs" in found:
        shown["review_prs"] = [_without_url(p) for p in found["review_prs"]]
    return shown


def fresh_query(ctx: Context, now: datetime) -> list[str] | None:
    """The tracker query's result when the block shows it `fresh` at `now`: a source read it whole within its age.

    The harness then records it as `canopy queried` would, so the overseer neither runs nor records it (DESIGN §6).

    Returns:
        The keys, in the order the source read them; None when no source read the query within
        `connect.max_age_minutes`, or none observes tickets.
    """
    run = _query_run(ctx.conn, SourceKind.TRACKER, "query_result")
    tracked = ctx.config.connect.observes_tickets()
    found = _query_state(run, SourceKind.TRACKER, tracked=tracked, cutoff=_cutoff(ctx, now))
    return found.get("result") if found["observed"] == "fresh" else None


def past_comments(comments: Iterable[records.ObservedComment], cursor: int | None) -> list[records.ObservedComment]:
    """The comments past the `comment` cursor, a journal number (DESIGN §35): first observed after the one it names.

    Returns:
        The comments, in `comments`' order, which is the order they were first observed.
    """
    return [c for c in comments if item_numbers.newer(c.number, cursor)]


def new_reviews(reviews: Iterable[records.ObservedReview], cursor: int | None) -> list[records.ObservedReview]:
    """The reviews and review comments past a unit's `review` cursor, a journal number (DESIGN §35).

    Returns:
        The items, in the order they were first observed, which a late submission does not backdate.
    """
    new = [r for r in reviews if item_numbers.newer(r.number, cursor)]
    return sorted(new, key=lambda r: (r.number is None, r.number or 0))


@dataclass(frozen=True)
class Reader:
    """What one tick's observations read: the journal and the connectors' rows, once.

    The state block's section reads every subject through it, and a dispatch's claims the subjects they rest on
    (`loop.claims`), so a claim is checked against the observation the block showed.
    """

    ctx: Context
    #: Before this, an observation is stale (`connect.max_age_minutes`).
    cutoff: datetime
    keys: Sequence[str]
    journal: Mapping[str, records.Ticket]
    observed: Mapping[str, records.ObservedTicket]
    comments: Mapping[str, Sequence[records.ObservedComment]]
    prs: Mapping[str, records.ObservedPr]
    checks: Mapping[str, Sequence[records.ObservedCheck]]
    reviews: Mapping[str, Sequence[records.ObservedReview]]
    branches: Mapping[str, Sequence[records.ObservedBranch]]
    fresh_repos: AbstractSet[str]
    units_of: Mapping[str, Sequence[records.TicketUnit]]
    #: The tick's derivation, by ticket and unit (None for the ticket's own).
    derived: Mapping[tuple[str, str | None], phases.Derived]
    runs: Mapping[SourceKind, records.ConnectorRun]
    #: Whether a `tracker` source observes tickets at all.
    tracked: bool

    @classmethod
    def read(
        cls,
        ctx: Context,
        derived: Iterable[phases.Derived],
        now: datetime,
        tickets: Iterable[records.Ticket],
    ) -> Reader:
        """Read the observations as they stand at `now`, with `tickets` the ones the block lists.

        `derived` is the tick's derivation, which a tick has recorded and the loop's poll has not (DESIGN §39).

        Returns:
            The reader.
        """
        conn = ctx.conn
        cutoff = _cutoff(ctx, now)
        listed = {t.key: t for t in tickets}
        stopped = set(conversation.stopped(conn))
        done = {str(r[0]) for r in sql.execute(conn, sql.select("key").from_("tickets").where("done = 1"))}
        runs = _query_runs(conn)
        tracker = runs.get(SourceKind.TRACKER)
        queried = [] if tracker is None else _result(tracker.query_result)
        keys: list[str] = sorted(set(listed) | (set(queried) - stopped - done))
        journal = {t.key: t for t in records.select(records.Ticket).all(conn)}
        comments: dict[str, list[records.ObservedComment]] = {}
        # In the order they were first observed, as their numbers say (DESIGN §35).
        query = (
            sql.select("*")
            .from_("observed_comments")
            .where_in("ticket", keys)
            .order_by("number IS NULL, number, commented_at, id")
        )
        for c in records.fetch_all(conn, records.ObservedComment, query):
            comments.setdefault(c.ticket, []).append(c)
        checks: dict[str, list[records.ObservedCheck]] = {}
        for c in records.select(records.ObservedCheck).order_by("name").all(conn):
            checks.setdefault(c.pr_url, []).append(c)
        reviews: dict[str, list[records.ObservedReview]] = {}
        query = sql.select("*").from_("observed_reviews").order_by("pr_url, created_at, id")
        for r in records.fetch_all(conn, records.ObservedReview, query):
            reviews.setdefault(r.pr_url, []).append(r)
        branches: dict[str, list[records.ObservedBranch]] = {}
        for b in records.select(records.ObservedBranch).all(conn):
            branches.setdefault(b.repository, []).append(b)
        return cls(
            ctx=ctx,
            cutoff=cutoff,
            keys=keys,
            journal=journal,
            observed={t.key: t for t in records.select(records.ObservedTicket).all(conn)},
            comments=comments,
            prs={p.url: p for p in records.select(records.ObservedPr).all(conn)},
            checks=checks,
            reviews=reviews,
            branches=branches,
            fresh_repos=phases.fresh_repos(conn, branches, cutoff),
            units_of=db.all_units(conn),
            derived={(d.ticket_key, d.repo): d for d in derived},
            runs=runs,
            tracked=ctx.config.connect.observes_tickets(),
        )

    # The queries

    def query(self, kind: SourceKind) -> QueryState:
        """A query's result as the newest run of `kind`'s source that read it to the end left it.

        Returns:
            Its freshness, and the result when a run read it.
        """
        return _query_state(self.runs.get(kind), kind, tracked=self.tracked, cutoff=self.cutoff)

    def review_pr(self, url: str) -> ReviewPrObservation:
        """A PR a review asks about: its state, head, and checks at its head, as last read whole.

        Returns:
            The PR's entry.
        """
        if not observe.is_pr_url(url):
            return {"url": url, "observed": "unobserved", "why": f"{url} is not a PR's URL, so it is not observed"}
        pr = self.prs.get(url)
        why = self._age(url, pr)
        if why is not None or pr is None:
            return {"url": url, "observed": "stale", "why": why or f"{url} never observed"}
        return {
            "url": url,
            "observed": "fresh",
            "observed_at": db.to_minute(pr.observed_at),
            "pr": _pr(url, pr),
            "checks": _checks([c for c in self.checks.get(url, []) if c.head_sha == pr.head_sha], {}),
        }

    # A ticket

    def ticket(self, key: str) -> TicketObservation:
        """A ticket's observation: a fresh candidate's whole, a non-candidate's key and why, a stale one's what.

        Returns:
            The ticket's entry.
        """
        seen = self.observed.get(key)
        why = NO_TRACKER if not self.tracked else self._age(key, seen)
        if why is None and seen is not None:
            labels = phases.labels_of(seen)
            private = conversation.is_started(conversation.start_of(self.ctx.conn, key))
            closed = seen.state is TicketState.CLOSED
            queued = {label["name"] for label in labels} & set(self.ctx.config.tracker.labels)
            if closed or not (private or queued):
                # A non-candidate's text never reaches the overseer: a widened query shows it nothing (TRUST_MODEL T7).
                why_not = "closed" if closed else "not labeled"
                return {"key": key, "observed": "fresh", "candidate": False, "why": why_not}
            why = self._candidate_stale(key, seen)
            if why is None:
                return self._candidate(key, seen, labels)
        return {
            "key": key,
            "observed": "unobserved" if why == NO_TRACKER else "stale",
            "why": why or f"{key} never observed",
            "units": self.units(key),
        }

    def _candidate(self, key: str, seen: records.ObservedTicket, labels: Iterable[phases.Label]) -> TicketObservation:
        """A fresh candidate's observation: its title, state, labels, blockers, body, new comments, and units.

        Returns:
            The ticket's entry.
        """
        found: TicketObservation = {
            "key": key,
            "observed": "fresh",
            "candidate": True,
            "observed_at": db.to_minute(seen.observed_at),
            "title": seen.title,
            "state": seen.state,
            "labels": [{"name": str(x["name"]), "added_at": db.to_minute(x.get("added_at"))} for x in labels],
            "blockers": [{"key": b, "state": self.observed[b].state} for b in phases.blockers_of(seen)],
        }
        # The repository and the slug are chosen from the body; once the ticket has a unit, its work says the rest.
        if not self.units_of.get(key):
            found["body"] = seen.body
        record = self.journal[key]
        new = past_comments(self.comments.get(key, []), record.comment_cursor)
        found["comments"] = [self._comment(c) for c in new[:MAX_NEW_ITEMS]]
        if len(new) > MAX_NEW_ITEMS:
            found["more_comments"] = len(new) - MAX_NEW_ITEMS
        derived = self.derived.get((key, None))
        if derived is not None and derived.stale is None:
            found["derived"] = [str(p) for p in derived.phases]
        found["units"] = self.units(key)
        return found

    def _candidate_stale(self, key: str, seen: records.ObservedTicket) -> str | None:
        """Say what else a candidate's decision rests on that is stale or missing, as the derivation does.

        Its blockers' observations, its comments since canopy first held it, and, with no PR, its repositories'
        branches, which say whether it is `ready` or has work on origin.

        Returns:
            What, or None when all of it is fresh.
        """
        for blocker in phases.blockers_of(seen):
            why = self._age(f"blocker {blocker}", self.observed.get(blocker))
            if why is not None:
                return why
        record = self.journal.get(key)
        # Comments are recorded only of a ticket canopy holds (§30): one read before then has none recorded.
        if record is None or record.first_seen_at > seen.observed_at:
            return f"comments of {key} not observed since canopy first held it"
        if not any(u.pr_url for u in self.units_of.get(key, [])):
            old = sorted(r.name for r in self.ctx.workspace.repos if r.name not in self.fresh_repos)
            if old:
                return f"branches of {', '.join(old)} not observed since {db.to_minute(self.cutoff)}"
        return None

    def _age(self, what: str, seen: records.ObservedTicket | records.ObservedPr | None) -> str | None:
        if seen is None:
            return f"{what} never observed"
        if db.parse_time(seen.observed_at) < self.cutoff:
            return f"{what} last observed {db.to_minute(seen.observed_at)}"
        return None

    def _comment(self, c: records.ObservedComment) -> CommentState:
        found: CommentState = {
            "number": c.number,
            "id": c.id,
            "author": c.author,
            "at": db.to_minute(c.commented_at),
            "authorized": c.author in self.ctx.config.trust.authorized_repliers,
            "worker": c.source == "worker",
            "body": c.body,
        }
        if c.truncated:
            found["truncated"] = True
        return found

    # Its units

    def units(self, key: str) -> list[UnitObservation]:
        """Each of a ticket's units: those the journal holds, and any the tick derived from a branch observed.

        Returns:
            One entry per unit, by repository.
        """
        # A unit with no repository is from before the workspace map named one (D058): no subject to observe.
        units = {u.repo: u for u in self.units_of.get(key, []) if u.repo is not None}
        repos = sorted({*units, *(repo for k, repo in self.derived if k == key and repo is not None)})
        return [self._unit(key, repo, units.get(repo)) for repo in repos]

    def _unit(self, key: str, repo: str, unit: records.TicketUnit | None) -> UnitObservation:
        found: UnitObservation
        if unit is not None and unit.pr_url is not None:
            found = self._pr_unit(repo, unit, unit.pr_url)
        elif repo not in self.fresh_repos:
            why = f"branches of {repo} not observed since {db.to_minute(self.cutoff)}"
            found = {"repo": repo, "observed": "stale", "why": why}
        else:
            record = self.journal.get(key)
            branch = None if record is None else record.branch
            prefix = self.ctx.config.trust.branch_prefix
            found = {
                "repo": repo,
                "observed": "fresh",
                "branch": phases.branch_of(self.branches.get(repo, []), prefix, key, branch),
            }
        derived = self.derived.get((key, repo))
        if found["observed"] == "fresh" and derived is not None and derived.stale is None:
            found["derived"] = [str(p) for p in derived.phases]
        return found

    def _pr_unit(self, repo: str, unit: records.TicketUnit, url: str) -> UnitObservation:
        """A unit with a PR: the PR as last read whole, its checks at its head, verdicts, and new review items.

        Returns:
            The unit's entry.
        """
        if not observe.is_pr_url(url):
            return {"repo": repo, "observed": "unobserved", "why": f"{url} is not a PR's URL, so it is not observed"}
        pr = self.prs.get(url)
        why = self._age(url, pr)
        if why is not None or pr is None:
            return {"repo": repo, "observed": "stale", "why": why or f"{url} never observed"}
        roles = self.ctx.workspace.check_roles(repo)
        trusted = {t.lower() for t in self.ctx.config.trust.trusted_reviewers}
        new = new_reviews(self.reviews.get(url, []), unit.review_cursor)
        observed: UnitObservation = {
            "repo": repo,
            "observed": "fresh",
            "observed_at": db.to_minute(pr.observed_at),
            "pr": _pr(url, pr),
            "checks": _checks([c for c in self.checks.get(url, []) if c.head_sha == pr.head_sha], roles),
            "verdicts": _verdicts(self.reviews.get(url, []), trusted),
            "reviews": [self._review(r, trusted) for r in new[:MAX_NEW_ITEMS]],
        }
        if len(new) > MAX_NEW_ITEMS:
            observed["more_reviews"] = len(new) - MAX_NEW_ITEMS
        return observed

    def _review(self, r: records.ObservedReview, trusted: AbstractSet[str]) -> ReviewItemState:
        trust = self.ctx.config.trust
        found: ReviewItemState = {
            "number": r.number,
            "item": r.item,
            "id": r.id,
            "author": r.author,
            "trusted": (r.author or "").lower() in trusted,
            "worker": conversation.worker_marked(r.body, trust.comment_prefix, trust.comment_suffix),
            "at": db.to_minute(r.created_at),
            "url": r.url,
            "body": r.body,
        }
        if r.item is ReviewItem.REVIEW:
            found["state"] = r.state
        return found


def _pr(url: str, pr: records.ObservedPr) -> PrObservation:
    return {
        "url": url,
        "state": pr.state,
        "head": pr.head_sha,
        "base": pr.base_ref,
        "draft": pr.draft,
        "mergeable": pr.mergeable,
        "mergeable_state": pr.mergeable_state,
        "author": pr.author,
    }


def _without_url(entry: UnitObservation | ReviewPrObservation) -> dict[str, object]:
    pr = entry.get("pr")
    if pr is None:
        return dict(entry)
    return {**entry, "pr": {k: v for k, v in pr.items() if k != "url"}}


def _cutoff(ctx: Context, now: datetime) -> datetime:
    # Before this, an observation is stale.
    return now - timedelta(minutes=ctx.config.connect.max_age_minutes)


def _query_state(
    run: records.ConnectorRun | None,
    kind: SourceKind,
    *,
    tracked: bool,
    cutoff: datetime,
) -> QueryState:
    """A query's result as `run`, the newest run of `kind`'s source that read it to the end, left it.

    Returns:
        Its freshness, and the result when a run read it.
    """
    if kind is SourceKind.TRACKER and not tracked:
        return {"observed": "unobserved", "why": NO_TRACKER}
    if run is None:
        return {"observed": "stale", "why": "never read to its end"}
    found: QueryState = {
        "observed": "fresh",
        "read_at": db.to_minute(run.ended_at),
        "result": _result(_query_of(run, kind)),
    }
    if db.parse_time(run.ended_at) < cutoff:
        found["observed"] = "stale"
        found["why"] = f"last read {db.to_minute(run.ended_at)}"
    return found


def _query_runs(conn: sqlite3.Connection) -> dict[SourceKind, records.ConnectorRun]:
    """The newest run of each kind of source that read its query to the end.

    Returns:
        The runs, by kind: the tracker query's, and the review query's.
    """
    found = {
        SourceKind.TRACKER: _query_run(conn, SourceKind.TRACKER, "query_result"),
        SourceKind.VCS: _query_run(conn, SourceKind.VCS, "review_query_result"),
    }
    return {kind: run for kind, run in found.items() if run is not None}


def _query_run(
    conn: sqlite3.Connection,
    kind: SourceKind,
    column: Literal["query_result", "review_query_result"],
) -> records.ConnectorRun | None:
    return (
        records.select(records.ConnectorRun)
        .where("kind = ? AND {} IS NOT NULL", kind, sql.name(column))
        .order_by("id DESC")
        .limit(1)
        .one(conn)
    )


def _query_of(run: records.ConnectorRun, kind: SourceKind) -> str | None:
    return run.query_result if kind is SourceKind.TRACKER else run.review_query_result


def _result(stored: str | None) -> list[str]:
    return [str(x) for x in json.loads(stored)] if stored is not None else []


def _checks(checks: Iterable[records.ObservedCheck], roles: Mapping[str, CheckRole]) -> ChecksState:
    """Summarize the checks at a PR's head as the phase table reads them (DESIGN §7): passed, pending, or failed.

    Args:
        checks: The checks at the head.
        roles: The role its repository gives each check it names; every other one is CI (DESIGN §30).

    Returns:
        How many passed, the names of those pending, each failure whole, and the stale and human checks when any.
    """
    found: ChecksState = {"passed": 0, "pending": [], "failed": []}
    stale: list[str] = []
    people: list[HumanCheck] = []
    for c in checks:
        role = roles.get(c.name, CheckRole.CI)
        match role:
            case CheckRole.CI:
                pass
            case CheckRole.HUMAN:
                people.append({"name": c.name, "status": c.status, "conclusion": c.conclusion})
                continue
            case CheckRole.MERGE | CheckRole.IGNORE:
                continue
            case _:
                assert_never(role)
        if c.status is not CheckStatus.COMPLETED:
            found["pending"].append(c.name)
        elif c.conclusion in observe.PASSED:
            found["passed"] += 1
        elif c.conclusion is not None and c.conclusion in observe.FAILED:
            found["failed"].append(
                {"number": c.number, "name": c.name, "conclusion": c.conclusion, "run_id": c.run_id, "url": c.url},
            )
        else:
            stale.append(c.name)
    if stale:
        found["stale"] = stale
    if people:
        found["human"] = people
    return found


def _verdicts(reviews: Collection[records.ObservedReview], trusted: AbstractSet[str]) -> list[VerdictState]:
    """Each person's latest approval, change request, or dismissed review: what `approved` is read from (DESIGN §7).

    Returns:
        One per author, by when their verdict came; a bot's is left out, since it never counts.
    """
    latest: dict[str, tuple[str, ReviewState]] = {}
    kinds = {ReviewState.APPROVED, ReviewState.CHANGES_REQUESTED, ReviewState.DISMISSED}
    for r in reviews:
        if r.item is ReviewItem.REVIEW and not r.bot and r.author is not None and r.state in kinds:
            latest.pop(r.author.lower(), None)
            latest[r.author.lower()] = (r.author, r.state)
    return [{"author": a, "state": s, "trusted": a.lower() in trusted} for a, s in latest.values()]
