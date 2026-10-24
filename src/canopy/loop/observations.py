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
from typing import TYPE_CHECKING, Literal, NotRequired, TypedDict

from canopy.core import conversation, db, observe, records, sql
from canopy.core.vocab import CheckStatus, ReviewItem, ReviewState, SourceKind, TicketState
from canopy.loop import phases

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

    `review_query` only when `review.query` is set.
    """

    max_age_minutes: int
    max_new_items: int
    query: QueryState
    review_query: NotRequired[QueryState]
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

    `authorized`: its author is in `trust.authorized_repliers`. `worker`: it carries the workers' marks (D069). Both
    are decided in code.
    """

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

    `stale` only when a check ended neither passing nor failing, and `human` only when the repository's
    `human_checks` names a check at the head: those wait on a person, are not CI, and count in none of the others
    (DESIGN §30).
    """

    passed: int
    pending: list[str]
    failed: list[FailedCheck]
    stale: NotRequired[list[str]]
    human: NotRequired[list[HumanCheck]]


class FailedCheck(TypedDict):
    """A check that failed at a PR's head: what a `resume` for `ci` names, its run as the cursor."""

    name: str
    conclusion: str
    run_id: int | None
    url: str | None


class HumanCheck(TypedDict):
    """A check the repository's `human_checks` names, at a PR's head, as it stands."""

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

    `trusted`: its author is in `trust.trusted_reviewers`. `worker`: it carries the workers' marks (D069). Both are
    decided in code.
    """

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
    reader = Reader.read(ctx, tick_id, now, tickets)
    found: ObservationsState = {
        "max_age_minutes": ctx.config.connect.max_age_minutes,
        "max_new_items": MAX_NEW_ITEMS,
        "query": reader.query(SourceKind.TRACKER),
        "tickets": [reader.ticket(key) for key in reader.keys if key not in decided],
    }
    if ctx.config.review.query.strip():
        found["review_query"] = reader.query(SourceKind.VCS)
    return found


def fresh_query(ctx: Context, now: datetime) -> list[str] | None:
    """The tracker query's result when the block shows it `fresh` at `now`: a source read it whole within its age.

    The harness then records it as `canopy queried` would, so the overseer neither runs nor records it (DESIGN §6).

    Returns:
        The keys, in the order the source read them; None when no source read the query within
        `connect.max_age_minutes`, or none observes tickets.
    """
    run = _query_run(ctx.conn, SourceKind.TRACKER, "query_result")
    found = _query_state(run, SourceKind.TRACKER, tracked=_tracked(ctx), cutoff=_cutoff(ctx, now))
    return found.get("result") if found["observed"] == "fresh" else None


def past_comments(comments: Sequence[records.ObservedComment], *cursors: str | None) -> list[records.ObservedComment]:
    """The comments past the earliest of `cursors`, oldest first: those not every cursor has passed.

    A cursor names a comment by the tracker's id. One naming no observed comment is passed by the comments whose ids
    are larger numbers, where both are numbers, as the trackers canopy reads number them; by none otherwise.

    Returns:
        The comments, in `comments`' order, which is the time they were written.
    """
    return list(comments[min((_after(comments, c) for c in cursors), default=0) :])


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
    #: This tick's derivation, by ticket and unit (None for the ticket's own).
    derived: Mapping[tuple[str, str | None], records.Derivation]
    runs: Mapping[SourceKind, records.ConnectorRun]
    #: Whether a `tracker` source observes tickets at all.
    tracked: bool

    @classmethod
    def read(cls, ctx: Context, tick_id: int, now: datetime, tickets: Iterable[records.Ticket]) -> Reader:
        """Read the observations of tick `tick_id` as they stand at `now`, with `tickets` the ones the block lists.

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
        journal = {t.key: t for t in records.fetch_all(conn, records.Ticket, sql.select("*").from_("tickets"))}
        comments: dict[str, list[records.ObservedComment]] = {}
        query = sql.select("*").from_("observed_comments").where_in("ticket", keys).order_by("commented_at, id")
        for c in records.fetch_all(conn, records.ObservedComment, query):
            comments.setdefault(c.ticket, []).append(c)
        checks: dict[str, list[records.ObservedCheck]] = {}
        for c in records.fetch_all(
            conn,
            records.ObservedCheck,
            sql.select("*").from_("observed_checks").order_by("name"),
        ):
            checks.setdefault(c.pr_url, []).append(c)
        reviews: dict[str, list[records.ObservedReview]] = {}
        query = sql.select("*").from_("observed_reviews").order_by("pr_url, created_at, id")
        for r in records.fetch_all(conn, records.ObservedReview, query):
            reviews.setdefault(r.pr_url, []).append(r)
        branches: dict[str, list[records.ObservedBranch]] = {}
        for b in records.fetch_all(conn, records.ObservedBranch, sql.select("*").from_("observed_branches")):
            branches.setdefault(b.repository, []).append(b)
        derivations = records.fetch_all(
            conn,
            records.Derivation,
            sql.select("*").from_("derivations").where("tick_id = ?", tick_id),
        )
        return cls(
            ctx=ctx,
            cutoff=cutoff,
            keys=keys,
            journal=journal,
            observed={
                t.key: t
                for t in records.fetch_all(conn, records.ObservedTicket, sql.select("*").from_("observed_tickets"))
            },
            comments=comments,
            prs={p.url: p for p in records.fetch_all(conn, records.ObservedPr, sql.select("*").from_("observed_prs"))},
            checks=checks,
            reviews=reviews,
            branches=branches,
            fresh_repos=phases.fresh_repos(conn, branches, cutoff),
            units_of=db.all_units(conn),
            derived={(d.ticket_key, d.repo): d for d in derivations},
            runs=runs,
            tracked=_tracked(ctx),
        )

    # The queries

    def query(self, kind: SourceKind) -> QueryState:
        """A query's result as the newest run of `kind`'s source that read it to the end left it.

        Returns:
            Its freshness, and the result when a run read it.
        """
        return _query_state(self.runs.get(kind), kind, tracked=self.tracked, cutoff=self.cutoff)

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
            "observed_at": seen.observed_at,
            "title": seen.title,
            "state": seen.state,
            "labels": [{"name": str(x["name"]), "added_at": x.get("added_at")} for x in labels],
            "blockers": [{"key": b, "state": self.observed[b].state} for b in phases.blockers_of(seen)],
        }
        # The repository and the slug are chosen from the body; once the ticket has a unit, its work says the rest.
        if not self.units_of.get(key):
            found["body"] = seen.body
        record = self.journal[key]
        new = past_comments(self.comments.get(key, []), record.last_comment_id)
        found["comments"] = [self._comment(c) for c in new[:MAX_NEW_ITEMS]]
        if len(new) > MAX_NEW_ITEMS:
            found["more_comments"] = len(new) - MAX_NEW_ITEMS
        derived = self.derived.get((key, None))
        if derived is not None and derived.stale is None:
            found["derived"] = json.loads(derived.phases)
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
                return f"branches of {', '.join(old)} not observed since {db.format_time(self.cutoff)}"
        return None

    def _age(self, what: str, seen: records.ObservedTicket | records.ObservedPr | None) -> str | None:
        if seen is None:
            return f"{what} never observed"
        if db.parse_time(seen.observed_at) < self.cutoff:
            return f"{what} last observed {seen.observed_at}"
        return None

    def _comment(self, c: records.ObservedComment) -> CommentState:
        found: CommentState = {
            "id": c.id,
            "author": c.author,
            "at": c.commented_at,
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
            why = f"branches of {repo} not observed since {db.format_time(self.cutoff)}"
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
            found["derived"] = json.loads(derived.phases)
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
        found = self.ctx.workspace.repo(repo)
        human = found.human_checks if found is not None else frozenset[str]()
        trusted = {t.lower() for t in self.ctx.config.trust.trusted_reviewers}
        cursor = phases.review_cursor(unit.last_review_id)
        new = [r for r in self.reviews.get(url, []) if phases.newer(r.created_at, cursor)]
        observed: UnitObservation = {
            "repo": repo,
            "observed": "fresh",
            "observed_at": pr.observed_at,
            "pr": {
                "url": url,
                "state": pr.state,
                "head": pr.head_sha,
                "base": pr.base_ref,
                "draft": pr.draft,
                "mergeable": pr.mergeable,
                "mergeable_state": pr.mergeable_state,
                "author": pr.author,
            },
            "checks": _checks([c for c in self.checks.get(url, []) if c.head_sha == pr.head_sha], human),
            "verdicts": _verdicts(self.reviews.get(url, []), trusted),
            "reviews": [self._review(r, trusted) for r in new[:MAX_NEW_ITEMS]],
        }
        if len(new) > MAX_NEW_ITEMS:
            observed["more_reviews"] = len(new) - MAX_NEW_ITEMS
        return observed

    def _review(self, r: records.ObservedReview, trusted: AbstractSet[str]) -> ReviewItemState:
        trust = self.ctx.config.trust
        found: ReviewItemState = {
            "item": r.item,
            "id": r.id,
            "author": r.author,
            "trusted": (r.author or "").lower() in trusted,
            "worker": conversation.worker_marked(r.body, trust.comment_prefix, trust.comment_suffix),
            "at": r.created_at,
            "url": r.url,
            "body": r.body,
        }
        if r.item is ReviewItem.REVIEW:
            found["state"] = r.state
        return found


def _cutoff(ctx: Context, now: datetime) -> datetime:
    # Before this, an observation is stale.
    return now - timedelta(minutes=ctx.config.connect.max_age_minutes)


def _tracked(ctx: Context) -> bool:
    return any(s.kind == SourceKind.TRACKER for s in ctx.config.connect.named().values())


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
    found: QueryState = {"observed": "fresh", "read_at": run.ended_at, "result": _result(_query_of(run, kind))}
    if db.parse_time(run.ended_at) < cutoff:
        found["observed"] = "stale"
        found["why"] = f"last read {run.ended_at}"
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
    return records.fetch_one(
        conn,
        records.ConnectorRun,
        sql.select("*")
        .from_("connector_runs")
        .where("kind = ? AND {} IS NOT NULL", kind, sql.name(column))
        .order_by("id DESC")
        .limit(1),
    )


def _query_of(run: records.ConnectorRun, kind: SourceKind) -> str | None:
    return run.query_result if kind is SourceKind.TRACKER else run.review_query_result


def _result(stored: str | None) -> list[str]:
    return [str(x) for x in json.loads(stored)] if stored is not None else []


def _after(comments: Sequence[records.ObservedComment], cursor: str | None) -> int:
    """Where the comments past `cursor` start in `comments`.

    Returns:
        The index of the first comment past it: 0 with no cursor, or one that names nothing and is not a number.
    """
    if not cursor:
        return 0
    for i, c in enumerate(comments):
        if c.id == cursor:
            return i + 1
    if not cursor.isdigit():
        return 0
    return next((i for i, c in enumerate(comments) if c.id.isdigit() and int(c.id) > int(cursor)), len(comments))


def _checks(checks: Iterable[records.ObservedCheck], human: AbstractSet[str]) -> ChecksState:
    """Summarize the checks at a PR's head as the phase table reads them (DESIGN §7): passed, pending, or failed.

    Returns:
        How many passed, the names of those pending, each failure whole, and the stale and human checks when any.
    """
    found: ChecksState = {"passed": 0, "pending": [], "failed": []}
    stale: list[str] = []
    people: list[HumanCheck] = []
    for c in checks:
        if c.name in human:
            people.append({"name": c.name, "status": c.status, "conclusion": c.conclusion})
        elif c.status is not CheckStatus.COMPLETED:
            found["pending"].append(c.name)
        elif c.conclusion in phases.PASSED:
            found["passed"] += 1
        elif c.conclusion is not None and c.conclusion in phases.FAILED:
            found["failed"].append({"name": c.name, "conclusion": c.conclusion, "run_id": c.run_id, "url": c.url})
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
