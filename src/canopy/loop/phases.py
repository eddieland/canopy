"""The derivation, in shadow (DESIGN §30): §7's phase table derived in code from the observations and the journal.

Each tick, after the connectors, the harness derives what the overseer derives from its live reads: for each ticket
the state block lists, and each the tracker query last returned, whether it is a candidate (§17), and every row of §7's
table that holds for it and for each of its units. §7 has no order between its rows yet, so every row that holds is
recorded. A subject that depends on an observation stale or missing is recorded as stale, naming it, and no phase is
derived for it. The rows go in `derivations`, beside `decisions`; nothing the overseer, a worker, or a guard reads
changes. When the tick closes, the phase the overseer left each subject at is recorded with them, since the journal
keeps only a ticket's latest.

Agreement is computed from those rows and the tick's decisions, never stored (`compare`): a ticket agrees when the
phase the overseer set for each subject is one of the rows that held, and its decision one those rows allow. A ticket
with a stale subject is counted apart. A fix to the comparison reads every tick already recorded.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from canopy.core import conversation, db, observe, personas, plans, records, review_runs, sql
from canopy.core import review_result as result
from canopy.core.config import CANOPY_REVIEWER
from canopy.core.vocab import (
    CheckStatus,
    ConnectorRunStatus,
    Decider,
    Phase,
    PrState,
    ReviewItem,
    ReviewRunStatus,
    ReviewState,
    RunStatus,
    SourceKind,
    TicketState,
)
from canopy.loop import attention
from canopy.reviews import start as review_start
from canopy.reviews.start import DISPATCH_ACTION as REVIEW_ACTION

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Set as AbstractSet

    from canopy.core.context import Context

_DISPATCH = "dispatch:"
_ATTENTION = attention.ACTION_PREFIX
_RESUME = f"{_DISPATCH}resume"
_FEEDBACK_PLAN = f"{_DISPATCH}feedback-plan"
_ATTEMPT_LIMIT = f"{_ATTENTION}attempt_limit"
_NEEDS_AUTHOR = f"{_ATTENTION}needs_author"
#: What the overseer may decide for a subject at each phase: §7's next action, and the attention items it records for
#: it. A dispatch at its attempt limit is an attention item instead (§8); a resume may wait on a feedback plan (§32).
ALLOWS: Mapping[Phase, AbstractSet[str]] = {
    Phase.READY: frozenset({f"{_DISPATCH}implement", f"{_DISPATCH}plan", _ATTEMPT_LIMIT}),
    Phase.PLAN_PROPOSED: frozenset({f"{_ATTENTION}plan_review", f"{_DISPATCH}plan", _ATTEMPT_LIMIT}),
    Phase.BLOCKED: frozenset({f"{_DISPATCH}implement", "wait", _ATTEMPT_LIMIT}),
    Phase.RUNNING: frozenset({"wait"}),
    Phase.PUSHED_NO_PR: frozenset({_RESUME, _ATTEMPT_LIMIT}),
    Phase.CONFLICTED: frozenset({_RESUME, _ATTEMPT_LIMIT}),
    Phase.CI_RUNNING: frozenset({"wait"}),
    Phase.CI_RED: frozenset({_RESUME, _FEEDBACK_PLAN, _ATTEMPT_LIMIT, "wait"}),
    Phase.REVIEW_PENDING: frozenset({REVIEW_ACTION, f"{_ATTENTION}review_limit"}),
    Phase.REVIEW_FINDINGS: frozenset({_RESUME, _FEEDBACK_PLAN, _ATTEMPT_LIMIT, _NEEDS_AUTHOR}),
    Phase.CHANGES_REQUESTED: frozenset({_RESUME, _FEEDBACK_PLAN, _ATTEMPT_LIMIT, _NEEDS_AUTHOR}),
    Phase.UNTRUSTED_REVIEW: frozenset({f"{_ATTENTION}untrusted_review"}),
    Phase.GREEN_UNREVIEWED: frozenset({f"{_ATTENTION}needs_reviewer"}),
    Phase.APPROVED: frozenset({f"{_ATTENTION}ready_to_merge"}),
    Phase.MERGED: frozenset({"done"}),
    Phase.NEEDS_HUMAN: frozenset({"wait"}),
    Phase.HUMAN_REPLIED: frozenset({_RESUME, _ATTEMPT_LIMIT}),
    Phase.SPLIT: frozenset(),
}
#: The phase a decision moves its ticket to within the tick that made it: a worker it dispatched is running, so the
#: overseer sets `running` at once, though the derivation, made before it decided, held the row that dispatched it.
MOVES_TO: Mapping[str, Phase] = {
    f"{_DISPATCH}implement": Phase.RUNNING,
    f"{_DISPATCH}plan": Phase.RUNNING,
    _RESUME: Phase.RUNNING,
    _FEEDBACK_PLAN: Phase.RUNNING,
}
#: What the overseer may decide for a ticket the tracker says is closed: mark it done (DESIGN §7).
CLOSED_ALLOWS: AbstractSet[str] = frozenset({"done"})
#: What it may decide for an open ticket no row holds for, such as one without a queue label.
NONE_ALLOWS: AbstractSet[str] = frozenset({"skip", "wait"})
#: An observed label: its `name`, and `added_at`, None where the tracker does not say.
type Label = dict[str, str | None]
#: How a ticket compares with the overseer in one tick.
type Verdict = Literal["agrees", "disagrees", "stale"]


@dataclass(frozen=True)
class Derived:
    """One subject a tick derived: a ticket's own phases, or one of its units'."""

    #: The ticket.
    ticket_key: str
    #: The unit's repository; None for the ticket's own.
    repo: str | None
    #: Every phase of §7's table that held, in the vocabulary's order; none when the subject is stale.
    phases: Sequence[Phase] = ()
    #: The stale or missing observation the subject depends on; None when it was derived.
    stale: str | None = None
    #: On the ticket's own, unless stale: whether it is a candidate (§17), and whether the tracker said it is closed.
    candidate: bool | None = None
    closed: bool | None = None


def derive(ctx: Context, now: datetime) -> list[Derived]:
    """Derive every ticket's and unit's phases from the observations and the journal, as they stand at `now`.

    The tickets are those the state block lists, open and not stopped, and those the tracker query last returned.

    Returns:
        Each ticket's own row, then its units', by key.
    """
    world = _World.read(ctx, now)
    found: list[Derived] = []
    for key in world.keys:
        found.append(world.ticket(key))
        found.extend(world.units(key))
    return found


def record(conn: sqlite3.Connection, tick_id: int, derived: Iterable[Derived]) -> None:
    """Record what tick `tick_id` derived, in one transaction."""
    rows = [
        (
            tick_id,
            d.ticket_key,
            d.repo,
            d.candidate,
            d.closed,
            json.dumps([str(p) for p in d.phases]),
            d.stale,
        )
        for d in derived
    ]
    columns = ("tick_id", "ticket_key", "repo", "candidate", "closed", "phases", "stale")
    with db.transaction(conn):
        sql.execute_many(conn, sql.insert_rows("derivations", columns), rows)


def recorded(conn: sqlite3.Connection, tick_id: int) -> list[Derived]:
    """What tick `tick_id` derived, read back from the journal as `derive` returned it.

    Returns:
        Each ticket's own row, then its units', by key.
    """
    rows = records.fetch_all(
        conn,
        records.Derivation,
        sql.select("*")
        .from_("derivations")
        .where("tick_id = ?", tick_id)
        .order_by("ticket_key, repo IS NOT NULL, repo"),
    )
    return [
        Derived(
            r.ticket_key,
            r.repo,
            tuple(Phase(p) for p in json.loads(r.phases)),
            stale=r.stale,
            candidate=r.candidate,
            closed=r.closed,
        )
        for r in rows
    ]


def record_overseer(conn: sqlite3.Connection, tick_id: int) -> None:
    """Record, on tick `tick_id`'s derivations, the phase the journal holds for each subject as the tick closes.

    The ticket's own phase on its row, each unit's on the unit's: what the overseer left them at.
    """
    ticket = sql.select("phase").from_("tickets").where("key = derivations.ticket_key")
    unit = (
        sql.select("phase")
        .from_("ticket_units")
        .where("ticket_key = derivations.ticket_key AND repo = derivations.repo")
    )
    sql.execute(
        conn,
        sql.update("derivations")
        .set_to("overseer_phase = CASE WHEN repo IS NULL THEN ({}) ELSE ({}) END", ticket, unit)
        .where("tick_id = ?", tick_id),
    )


@dataclass(frozen=True)
class Compared:
    """How one ticket's derivation compares with what the overseer set and decided in one tick."""

    ticket_key: str
    verdict: Verdict
    #: Why it disagrees, or what is stale; None when it agrees.
    why: str | None = None


def compare(conn: sqlite3.Connection, tick_id: int) -> list[Compared]:
    """Compare tick `tick_id`'s derivation with the phases the overseer set and the decisions it recorded, by ticket.

    A ticket agrees when the phase the overseer left each subject at is one of the rows that held for it, wherever any
    did, and its decision is one those rows allow. Its decision is its dispatches, waits, skips, and done marks, or,
    with none, the attention items the overseer recorded for it; the harness's items, refusals, and mirrors are not
    the overseer's choice. A phase the ticket's own decision moved it to this tick (`MOVES_TO`), such as `running`
    after a dispatch, stands for the row that allowed the decision. A subject with no rows held is compared on the
    decision only, not its phase. A ticket with a stale subject is `stale`, never a disagreement. A ticket the harness
    decided (DESIGN §37) is not compared: the overseer decided nothing about it.

    Returns:
        One comparison per ticket the tick derived, by key.
    """
    rows = records.fetch_all(
        conn,
        records.Derivation,
        sql.select("*")
        .from_("derivations")
        .where("tick_id = ?", tick_id)
        .order_by("ticket_key, repo IS NOT NULL, repo"),
    )
    by_ticket: dict[str, list[records.Derivation]] = {}
    for row in rows:
        by_ticket.setdefault(row.ticket_key, []).append(row)
    decided: dict[str, list[str]] = {}
    by_harness: set[str] = set()
    for d in db.decisions_for_tick(conn, tick_id):
        if d.ticket_key is None:
            continue
        if d.decider is Decider.HARNESS and not d.action.startswith(_ATTENTION):
            by_harness.add(d.ticket_key)
        elif _overseers(d):
            decided.setdefault(d.ticket_key, []).append(d.action)
    return [
        _compared(key, subjects, decided.get(key, [])) for key, subjects in by_ticket.items() if key not in by_harness
    ]


def tally(conn: sqlite3.Connection, tick_id: int) -> Counter[Verdict]:
    """Count tick `tick_id`'s tickets by how their derivation compares with the overseer.

    Returns:
        How many agree, disagree, and are stale; empty when the tick derived nothing.
    """
    return Counter(c.verdict for c in compare(conn, tick_id))


def describe(counts: Counter[Verdict]) -> str:
    """Say how a tick's derivation compared, for the loop's per-tick block.

    Returns:
        Such as `derived 3 agree, 1 disagree, 2 stale`, or an empty string when the tick derived nothing.
    """
    if not counts:
        return ""
    return f"derived {counts['agrees']} agree, {counts['disagrees']} disagree, {counts['stale']} stale"


def fresh_repos(
    conn: sqlite3.Connection,
    branches: Mapping[str, Sequence[records.ObservedBranch]],
    cutoff: datetime,
) -> frozenset[str]:
    """The repositories whose branches were read whole since `cutoff`.

    One with a branch observed since then was; so was every repository a `vcs` run read everything of, since a
    repository with no branch under the prefix has no row to date.

    Returns:
        Their names.
    """
    fresh = {repo for repo, found in branches.items() if any(db.parse_time(b.observed_at) >= cutoff for b in found)}
    runs = records.fetch_all(
        conn,
        records.ConnectorRun,
        sql.select("*")
        .from_("connector_runs")
        .where(
            "kind = ? AND status = ? AND ended_at >= ?",
            SourceKind.VCS,
            ConnectorRunStatus.OK,
            db.format_time(cutoff),
        ),
    )
    for run in runs:
        asked = json.loads(run.request)
        for repo in asked.get("repositories", []) if isinstance(asked, dict) else []:
            if isinstance(repo, dict) and isinstance(repo.get("name"), str):
                fresh.add(repo["name"])
    return frozenset(fresh)


def labels_of(seen: records.ObservedTicket) -> list[Label]:
    """A ticket's observed labels, each a `{"name", "added_at"}`, `added_at` None where the tracker does not say.

    Returns:
        The labels, less any entry that names none.
    """
    found = json.loads(seen.labels)
    return [x for x in found if isinstance(x, dict) and isinstance(x.get("name"), str)]


def blockers_of(seen: records.ObservedTicket) -> list[str]:
    """The keys an observed ticket names as blocking it.

    Returns:
        The keys, in the tracker's order.
    """
    return [str(b) for b in json.loads(seen.blockers)]


def branch_of(branches: Iterable[records.ObservedBranch], prefix: str, key: str, branch: str | None) -> str | None:
    """A ticket's branch among a repository's observed `branches`: `branch`, as recorded, or one named for it.

    `prefix` is `trust.branch_prefix`: a branch named for the ticket is `<prefix><key>`, or that and a slug.

    Returns:
        The branch's name, or None.
    """
    named = f"{prefix}{key}"
    for b in branches:
        if (branch is not None and b.name == branch) or b.name == named or b.name.startswith(f"{named}-"):
            return b.name
    return None


def review_cursor(value: str | None) -> datetime | None:
    """Read a `review` cursor, a UTC time (DESIGN §7).

    Returns:
        The time; None when it is empty or not a time, as one an earlier canopy wrote.
    """
    try:
        return datetime.fromisoformat(value).astimezone(UTC) if value else None
    except ValueError:
        return None


def newer(stamp: str | None, cursor: datetime | None) -> bool:
    """Whether an item at `stamp` is newer than `cursor`: one at the cursor's own second is handled (DESIGN §7).

    Returns:
        True when there is no cursor, or the item's second is after it; False for an item with no time.
    """
    if cursor is None:
        return True
    if stamp is None:
        return False
    return db.parse_time(stamp).replace(microsecond=0) > cursor.replace(microsecond=0)


def is_feedback(review: records.ObservedReview) -> bool:
    """Whether an observed review or review comment is feedback (DESIGN §7).

    Returns:
        True for a review comment, a change request, and a review with something to say; False for an approval, a
        dismissal, and an empty review.
    """
    if review.item is ReviewItem.COMMENT:
        return True
    return review.state is ReviewState.CHANGES_REQUESTED or (
        review.state is ReviewState.COMMENTED and bool(review.body.strip())
    )


def _overseers(decision: records.Decision) -> bool:
    """Whether `decision` is the overseer's own choice about a ticket, not the harness's or a guard's.

    Returns:
        False for one the harness recorded, a harness's attention item from before the journal said who recorded it,
        a refusal, or an older tick's mirror.
    """
    action = decision.action
    if decision.decider is Decider.HARNESS or action.startswith("refused:") or action == conversation.MIRROR_ACTION:
        return False
    return not (action.startswith(_ATTENTION) and action.removeprefix(_ATTENTION) in attention.HARNESS_REASONS)


def _compared(key: str, subjects: Sequence[records.Derivation], actions: Sequence[str]) -> Compared:
    stale = [f"{_subject(s)}: {s.stale}" for s in subjects if s.stale is not None]
    if stale:
        return Compared(key, "stale", "; ".join(stale))
    chosen = [a for a in actions if not a.startswith(_ATTENTION)] or list(actions)
    allowed: set[str] = set()
    wrong: list[str] = []
    for s in subjects:
        held = [Phase(p) for p in json.loads(s.phases)]
        if s.closed:
            allowed |= CLOSED_ALLOWS
        if not held:
            continue
        # The overseer sets the phase its own decision leads to: a ticket derived `ready` it dispatched closes the tick
        # `running`. That phase stands for the row whose decision led there.
        led = [p for p in held if any(a in ALLOWS[p] and MOVES_TO.get(a) == s.overseer_phase for a in chosen)]
        if s.overseer_phase in held:
            allowed |= ALLOWS[s.overseer_phase]
        elif led:
            allowed.update(*(ALLOWS[p] for p in led))
        else:
            wrong.append(f"{_subject(s)} set {s.overseer_phase or 'no phase'}, held {', '.join(held)}")
    if not allowed and not wrong:
        allowed |= NONE_ALLOWS
    if not any(a in allowed for a in chosen):
        wrong.append(f"decided {', '.join(chosen) or 'nothing'}, allowed {', '.join(sorted(allowed)) or 'nothing'}")
    return Compared(key, "disagrees", "; ".join(wrong)) if wrong else Compared(key, "agrees")


def _subject(row: records.Derivation) -> str:
    return row.ticket_key if row.repo is None else attention.subject(row.ticket_key, row.repo)


# `phases` once each, in the vocabulary's order, so a recorded list reads the same whatever derived it first.
def _in_order(phases: Iterable[Phase]) -> tuple[Phase, ...]:
    order = list(Phase)
    return tuple(sorted(set(phases), key=order.index))


@dataclass
class _World:
    """What one derivation reads: the observations and the journal, once, as they stand at `now`."""

    ctx: Context
    now: datetime
    #: Before this, an observation is stale (`connect.max_age_minutes`).
    cutoff: datetime
    keys: Sequence[str]
    tickets: Mapping[str, records.Ticket]
    observed: Mapping[str, records.ObservedTicket]
    comments: Mapping[str, Sequence[records.ObservedComment]]
    prs: Mapping[str, records.ObservedPr]
    checks: Mapping[str, Sequence[records.ObservedCheck]]
    reviews: Mapping[str, Sequence[records.ObservedReview]]
    branches: Mapping[str, Sequence[records.ObservedBranch]]
    #: The repositories whose branches were read whole since the cutoff.
    fresh_repos: AbstractSet[str]
    units_of: Mapping[str, Sequence[records.TicketUnit]]
    running: AbstractSet[str]
    latest_runs: Mapping[str, records.Run]
    #: Whether a `tracker` source observes tickets at all.
    tracked: bool
    _review_runs: dict[str, list[records.ReviewRun]] = field(default_factory=dict[str, list[records.ReviewRun]])

    @classmethod
    def read(cls, ctx: Context, now: datetime) -> _World:
        conn, config = ctx.conn, ctx.config
        cutoff = now - timedelta(minutes=config.connect.max_age_minutes)
        stopped = set(conversation.stopped(conn))
        tickets = {t.key: t for t in db.open_tickets(conn) if t.key not in stopped}
        keys = sorted(set(tickets) | (set(_query_result(conn)) - stopped - _done(conn)))
        comments: dict[str, list[records.ObservedComment]] = {}
        query = sql.select("*").from_("observed_comments").where_in("ticket", keys).order_by("commented_at, id")
        for c in records.fetch_all(conn, records.ObservedComment, query):
            comments.setdefault(c.ticket, []).append(c)
        checks: dict[str, list[records.ObservedCheck]] = {}
        for c in records.fetch_all(conn, records.ObservedCheck, sql.select("*").from_("observed_checks")):
            checks.setdefault(c.pr_url, []).append(c)
        reviews: dict[str, list[records.ObservedReview]] = {}
        query = sql.select("*").from_("observed_reviews").order_by("pr_url, created_at, id")
        for r in records.fetch_all(conn, records.ObservedReview, query):
            reviews.setdefault(r.pr_url, []).append(r)
        branches: dict[str, list[records.ObservedBranch]] = {}
        for b in records.fetch_all(conn, records.ObservedBranch, sql.select("*").from_("observed_branches")):
            branches.setdefault(b.repository, []).append(b)
        running = {str(r["ticket_key"]) for r in db.running_runs(conn, "runs")}
        return cls(
            ctx=ctx,
            now=now,
            cutoff=cutoff,
            keys=keys,
            tickets=tickets,
            observed={
                t.key: t
                for t in records.fetch_all(conn, records.ObservedTicket, sql.select("*").from_("observed_tickets"))
            },
            comments=comments,
            prs={p.url: p for p in records.fetch_all(conn, records.ObservedPr, sql.select("*").from_("observed_prs"))},
            checks=checks,
            reviews=reviews,
            branches=branches,
            fresh_repos=fresh_repos(conn, branches, cutoff),
            units_of=db.all_units(conn),
            running=running,
            latest_runs=db.latest_runs(conn),
            tracked=any(s.kind == SourceKind.TRACKER for s in config.connect.named().values()),
        )

    # A ticket's own row

    def ticket(self, key: str) -> Derived:
        """Derive a ticket's own row: a private one's from the journal, a public one's from its observation too.

        Returns:
            The row.
        """
        journal = self.tickets.get(key)
        private = conversation.is_started(conversation.start_of(self.ctx.conn, key))
        if private:
            candidate, closed, blockers_open = True, False, False
        else:
            stale = self._ticket_stale(key)
            if stale is not None:
                return Derived(key, None, stale=stale)
            seen = self.observed[key]
            closed = seen.state is TicketState.CLOSED
            labels = {label["name"] for label in labels_of(seen)}
            candidate = not closed and bool(labels & set(self.ctx.config.tracker.labels))
            blockers_open = any(self.observed[b].state is TicketState.OPEN for b in blockers_of(seen))
        if closed:
            return Derived(key, None, candidate=False, closed=True)
        phases: list[Phase] = []
        running = key in self.running
        if running:
            phases.append(Phase.RUNNING)
        if journal is not None and plans.waits(self.ctx.conn, journal):
            phases.append(Phase.PLAN_PROPOSED)
        phases.extend(self._needs_human(key, journal, private=private))
        if candidate and not running:
            branch = self._has_branch(key, journal)
            if branch is None:
                return Derived(key, None, stale=self._branches_stale())
            if not branch:
                phases.append(Phase.BLOCKED if blockers_open else Phase.READY)
        return Derived(key, None, _in_order(phases), candidate=candidate, closed=False)

    def _ticket_stale(self, key: str) -> str | None:
        """Say what a public ticket's row depends on that is stale or missing: its observation, or a blocker's.

        Returns:
            What, or None when everything it depends on is fresh.
        """
        if not self.tracked:
            return "no tracker source observes tickets"
        seen = self.observed.get(key)
        stale = self._age(key, seen)
        if stale is not None or seen is None:
            return stale
        for blocker in blockers_of(seen):
            stale = self._age(f"blocker {blocker}", self.observed.get(blocker))
            if stale is not None:
                return stale
        return None

    def _age(self, what: str, seen: records.ObservedTicket | records.ObservedPr | None) -> str | None:
        if seen is None:
            return f"{what} never observed"
        if db.parse_time(seen.observed_at) < self.cutoff:
            return f"{what} last observed {seen.observed_at}"
        return None

    def _needs_human(self, key: str, record: records.Ticket | None, *, private: bool) -> list[Phase]:
        """Derive `needs_human` and `human_replied` (DESIGN §7): a private ticket's from the journal alone (§22).

        Returns:
            The two phases' rows that hold.
        """
        cursor = 0 if record is None else max(record.last_message_id or 0, record.forgotten_message_id or 0)
        operator: list[records.Message] = (
            conversation.operator_messages_after(self.ctx.conn, key, cursor) if record is not None else []
        )
        found: list[Phase] = []
        if private:
            latest = self.latest_runs.get(key)
            if latest is not None and latest.status is RunStatus.BLOCKED:
                ended = latest.ended_at or latest.started_at
                if not any(m.at > ended and conversation.answers_questions(m) for m in operator):
                    found.append(Phase.NEEDS_HUMAN)
            if operator:
                found.append(Phase.HUMAN_REPLIED)
            return found
        seen = self.observed[key]
        label = next((x for x in labels_of(seen) if x["name"] == self.ctx.config.tracker.needs_human_label), None)
        replied = False
        if label is not None:
            # Without label history, the worker's question comment is the reference point (DESIGN §17).
            comments = self.comments.get(key, [])
            since = label.get("added_at") or next(
                (c.commented_at for c in reversed(comments) if c.source == "worker"),
                None,
            )
            repliers = set(self.ctx.config.trust.authorized_repliers)
            replied = since is not None and any(
                c.source == "tracker" and c.author in repliers and c.commented_at > since for c in comments
            )
            if not replied:
                found.append(Phase.NEEDS_HUMAN)
        if replied or operator:
            found.append(Phase.HUMAN_REPLIED)
        return found

    def _has_branch(self, key: str, record: records.Ticket | None) -> bool | None:
        """Whether the ticket has a branch: a unit's PR, or one observed under the branch prefix in any repository.

        Returns:
            True or False, or None when a repository's branches are stale and the ticket has no PR to say so.
        """
        if any(u.pr_url for u in self.units_of.get(key, [])):
            return True
        if any(self._branch_in(repo.name, key, record) for repo in self.ctx.workspace.repos):
            return True
        return None if self._branches_stale() else False

    def _branches_stale(self) -> str | None:
        stale = sorted(r.name for r in self.ctx.workspace.repos if r.name not in self.fresh_repos)
        return f"branches of {', '.join(stale)} not observed since {db.format_time(self.cutoff)}" if stale else None

    def _branch_in(self, repo: str, key: str, record: records.Ticket | None) -> str | None:
        """The ticket's branch observed in `repo`: its recorded branch, or one named for it under the prefix.

        Returns:
            The branch's name, or None.
        """
        branch = None if record is None else record.branch
        return branch_of(self.branches.get(repo, []), self.ctx.config.trust.branch_prefix, key, branch)

    # A unit's rows

    def units(self, key: str) -> list[Derived]:
        """Derive each of a ticket's units: those the journal has, and a branch observed in a repository with none.

        Returns:
            One row per unit, by repository.
        """
        record = self.tickets.get(key)
        # A unit with no repository is from before the workspace map named one (D058): no subject to compare.
        units = {u.repo: u for u in self.units_of.get(key, []) if u.repo is not None}
        found: list[Derived] = []
        for repo in sorted(
            {*units, *(r.name for r in self.ctx.workspace.repos if self._branch_in(r.name, key, record))},
        ):
            unit = units.get(repo)
            if unit is not None and unit.pr_url is not None:
                found.append(self._pr_unit(key, repo, unit, unit.pr_url))
            elif repo not in self.fresh_repos:
                found.append(
                    Derived(key, repo, stale=f"branches of {repo} not observed since {db.format_time(self.cutoff)}"),
                )
            else:
                branch = self._branch_in(repo, key, record)
                found.append(Derived(key, repo, (Phase.PUSHED_NO_PR,) if branch is not None else ()))
        return found

    def _pr_unit(self, key: str, repo: str, unit: records.TicketUnit, url: str) -> Derived:
        """Derive a unit with a PR from its observation: its state, mergeability, checks at its head, and reviews.

        Returns:
            The unit's row.
        """
        if not observe.is_pr_url(url):
            return Derived(key, repo, stale=f"{url} is not a PR's URL, so it is not observed")
        pr = self.prs.get(url)
        stale = self._age(url, pr)
        if stale is not None or pr is None:
            return Derived(key, repo, stale=stale)
        if pr.state is PrState.MERGED:
            return Derived(key, repo, (Phase.MERGED,))
        if pr.state is not PrState.OPEN:
            return Derived(key, repo)
        phases: list[Phase] = []
        if observe.conflicts(pr):
            phases.append(Phase.CONFLICTED)
        ci, passed = self._ci(repo, pr, unit)
        phases.extend(ci)
        approved = _approved(self.reviews.get(url, []))
        phases.extend(self._feedback(key, pr, unit))
        if passed and not approved:
            phases.append(Phase.GREEN_UNREVIEWED)
            if self.ctx.config.review.agent_prs and not self._reviewed(key, url, pr.head_sha):
                phases.append(Phase.REVIEW_PENDING)
        if approved:
            phases.append(Phase.APPROVED)
        return Derived(key, repo, _in_order(phases))

    def _ci(self, repo: str, pr: records.ObservedPr, unit: records.TicketUnit) -> tuple[list[Phase], bool]:
        """Derive the CI rows from the PR's checks at its head, less those the repository names `human_checks` (§30).

        A failure is new when its check run is newer than the unit's `ci` cursor; a commit status, which has no run,
        only while the cursor is empty.

        Returns:
            The rows that hold of `ci_running` and `ci_red`, and whether every check passed, as none at all do.
        """
        found = self.ctx.workspace.repo(repo)
        human = found.human_checks if found is not None else frozenset[str]()
        ci = [c for c in self.checks.get(pr.url, []) if c.head_sha == pr.head_sha and c.name not in human]
        pending = any(c.status is not CheckStatus.COMPLETED for c in ci)
        failed = [c for c in ci if c.status is CheckStatus.COMPLETED and c.conclusion in observe.FAILED]
        phases = [Phase.CI_RUNNING] if pending else []
        cursor = ci_cursor(unit.last_ci_run_id)
        if any(cursor is None or (c.run_id is not None and c.run_id > cursor) for c in failed):
            phases.append(Phase.CI_RED)
        return phases, not pending and all(c.conclusion in observe.PASSED for c in ci)

    def _feedback(self, key: str, pr: records.ObservedPr, unit: records.TicketUnit) -> list[Phase]:
        """Derive the review rows (DESIGN §7, D089): feedback newer than the unit's `review` cursor, by whom it is from.

        Feedback is a review that says something, or a review comment; an approval is not feedback. What the PR's own
        author writes is not either: canopy's workers post as the operator, who opens the PR.

        Returns:
            The rows that hold of `review_findings`, `changes_requested`, and `untrusted_review`.
        """
        cursor = review_cursor(unit.last_review_id)
        trusted = {t.lower() for t in self.ctx.config.trust.trusted_reviewers}
        found: list[Phase] = []
        new = [
            r
            for r in self.reviews.get(pr.url, [])
            if is_feedback(r)
            and (pr.author is None or (r.author or "").lower() != pr.author.lower())
            and newer(r.created_at, cursor)
        ]
        if any((r.author or "").lower() in trusted for r in new):
            found.append(Phase.CHANGES_REQUESTED)
        operator = self._operator_times(key)
        untrusted = [r for r in new if (r.author or "").lower() not in trusted]
        if any(not any(at > (r.created_at or "") for at in operator) for r in untrusted):
            found.append(Phase.UNTRUSTED_REVIEW)
        if self.ctx.config.review.agent_prs and CANOPY_REVIEWER in trusted and self._findings(pr, cursor):
            found.append(Phase.REVIEW_FINDINGS)
        return found

    def _operator_times(self, key: str) -> list[str]:
        record = self.tickets.get(key)
        if record is None:
            return []
        # A verb's instruction, such as a feedback plan's approval, is not the operator speaking to the feedback.
        return [
            m.at
            for m in conversation.operator_messages_after(self.ctx.conn, key, record.forgotten_message_id or 0)
            if conversation.answers_questions(m)
        ]

    def _runs_of(self, url: str) -> list[records.ReviewRun]:
        if url not in self._review_runs:
            self._review_runs[url] = review_runs.review_runs_of(self.ctx.conn, url)
        return self._review_runs[url]

    # Whether canopy's reviewer reviewed the PR's head commit: a run on it that ended `done` (DESIGN §21), in each
    # persona of `[personas] reviewers` when it names any (§31).
    def _reviewed(self, key: str, url: str, sha: str | None) -> bool:
        runs = self._runs_of(url)
        chosen = personas.reviewers_of(self.ctx.conn, self.ctx.config, key)
        if chosen:
            return sha is not None and not review_start.owed_by(runs, sha, chosen)
        return any(r.sha == sha and r.status is ReviewRunStatus.DONE for r in runs)

    # Whether a review of the head has findings the operator did not dismiss, and ended after the `review` cursor: its
    # latest, or each persona's when several review it (§31).
    def _findings(self, pr: records.ObservedPr, cursor: datetime | None) -> bool:
        done = [r for r in self._runs_of(pr.url) if r.sha == pr.head_sha and r.status is ReviewRunStatus.DONE]
        latest = {r.persona: r for r in reversed(done)}.values()
        return any(self._kept_findings(r) and newer(r.ended_at, cursor) for r in latest)

    def _kept_findings(self, run: records.ReviewRun) -> bool:
        stored = result.stored(run.result_json)
        if stored is None:
            return False
        withheld = review_runs.withheld(self.ctx.conn, run.id)
        return any(i not in withheld for i in range(1, len(stored.findings) + 1))


def _query_result(conn: sqlite3.Connection) -> list[str]:
    """The keys the tracker query returned on the newest run that read it to the end.

    Returns:
        The keys; none when no run has.
    """
    row = sql.execute(
        conn,
        sql.select("query_result")
        .from_("connector_runs")
        .where("query_result IS NOT NULL")
        .order_by("id DESC")
        .limit(1),
    ).fetchone()
    return [str(k) for k in json.loads(str(row[0]))] if row is not None else []


def _done(conn: sqlite3.Connection) -> set[str]:
    return {str(r[0]) for r in sql.execute(conn, sql.select("key").from_("tickets").where("done = 1"))}


def _approved(reviews: Collection[records.ObservedReview]) -> bool:
    """Whether a person approved the PR: an author's latest approval or change request is an approval.

    A bot's approval is not approval (DESIGN §7), and a dismissed review leaves its author with none.

    Returns:
        True if some person's latest verdict approves.
    """
    latest: dict[str, ReviewState] = {}
    verdicts = {ReviewState.APPROVED, ReviewState.CHANGES_REQUESTED, ReviewState.DISMISSED}
    for r in reviews:
        if r.item is ReviewItem.REVIEW and not r.bot and r.author is not None and r.state in verdicts:
            latest[r.author.lower()] = r.state
    return any(state is ReviewState.APPROVED for state in latest.values())


def ci_cursor(value: str | None) -> int | None:
    """Read a unit's `ci` cursor, a check run's id.

    Returns:
        The id; None when it is empty or not a number, so every failure is new.
    """
    try:
        return int(value) if value else None
    except ValueError:
        return None
