"""The attention items the harness raises from their causes (DESIGN §14, §37, ROADMAP M38).

Eight reasons the overseer once recorded every tick their cause held are the harness's (`attention.FROM_CAUSES`). Each
tick, after the derivation (§30) and before the overseer runs, the harness raises each one whose cause holds, read from
the derivation's rows and the journal, and records it marked as its own, so no item hangs on a tick recording it again:

- `needs_reviewer` and `ready_to_merge`, for a unit whose first row of §7 is `green_unreviewed` or `approved`;
  `untrusted_review` while that row holds on a unit, unless feedback plans are on, which plan untrusted feedback too
  (§32);
- `review_limit`, for a unit `review_pending` whose PR has had its review runs (§21); `review_failed`, for a PR whose
  latest review run failed, until a newer one starts or the PR is seen merged or closed;
- `attempt_limit`, for a unit, or a ticket's plan, whose next run, as the rows say, is past its limit (§8);
- `plan_review`, while a plan waits on the operator, and `plan_changed`, while an approved plan's file is no longer the
  text they approved (§25, §32).

Beside them it raises `check_stuck`, which the overseer never recorded: for a unit `ci_running` on one check alone,
still pending `STUCK_AFTER` past every other check at its head finishing, which may not be CI, until it completes, the
head moves, or its repository's map gives it a role (§30).

An item that rests on what a connector observed is kept while that observation is stale: the harness records it again
as the latest `ok` tick listed it, and it goes only once a fresh observation shows its cause gone, or its ticket is
done, stopped, or seen closed or no longer a candidate. So a tick that could not read a cause, such as an outage's,
drops nothing, and none needs telling a partial tick from a whole one.

What it cannot read unambiguously stays with the guards that refuse the overseer, which record their item as before:
`attempt_limit` for a dispatch past its limit, and `review_limit` for a review past its PR's. The overseer cannot record
one of these reasons itself (`loop.tools`).
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from canopy.core import conversation, db, observe, plans, records, review_runs, sql
from canopy.core.vocab import CheckStatus, Phase, PlanStatus, PrState, ResumeReason, ReviewRunStatus, RunKind
from canopy.core.workspace import CheckRole
from canopy.loop import attention
from canopy.reviews import grants
from canopy.reviews import view as review_view
from canopy.runs import feedback_plans, policy

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable
    from collections.abc import Set as AbstractSet
    from datetime import datetime

    from canopy.core.context import Context
    from canopy.loop.phases import Derived

NEEDS_REVIEWER = "needs_reviewer"
READY_TO_MERGE = "ready_to_merge"
UNTRUSTED_REVIEW = "untrusted_review"
ATTEMPT_LIMIT = "attempt_limit"
REVIEW_FAILED = "review_failed"
REVIEW_LIMIT = "review_limit"
PLAN_REVIEW = "plan_review"
PLAN_CHANGED = "plan_changed"
CHECK_STUCK = attention.CHECK_STUCK
#: Every reason this module raises: those of `attention.FROM_CAUSES`, and one only the harness has ever recorded.
REASONS: frozenset[str] = attention.FROM_CAUSES | {CHECK_STUCK}
#: The reasons whose cause rests on what a connector observed, so a stale observation keeps their item.
OBSERVED: frozenset[str] = frozenset(
    {NEEDS_REVIEWER, READY_TO_MERGE, UNTRUSTED_REVIEW, ATTEMPT_LIMIT, REVIEW_LIMIT, CHECK_STUCK},
)
#: How long a unit's one pending CI check stays so after the last of its other checks at the head finished before it
#: raises `check_stuck`. A merge queue's status never completes on an open PR, nor a sign-off until a person acts, so
#: any time names them; an hour names them within a working session, while CI that runs an hour past every other job
#: is rare. A constant, not a key: the item only asks, and a check the operator leaves as CI holds the PR as before.
STUCK_AFTER = timedelta(hours=1)
#: The rows of §7 whose next run is a `resume` of their unit, each with the reason it would carry.
RESUME_ROWS: Mapping[Phase, ResumeReason] = {
    Phase.PUSHED_NO_PR: ResumeReason.NO_PR,
    Phase.CONFLICTED: ResumeReason.CONFLICT,
    Phase.CI_RED: ResumeReason.CI,
    Phase.REVIEW_FINDINGS: ResumeReason.REVIEW,
    Phase.CHANGES_REQUESTED: ResumeReason.REVIEW,
}
#: How a review run ended that raises `review_failed` (DESIGN §21).
FAILED_REVIEWS: frozenset[ReviewRunStatus] = frozenset(
    {ReviewRunStatus.FAILED, ReviewRunStatus.UNKNOWN, ReviewRunStatus.TIMEOUT, ReviewRunStatus.CRASHED},
)


@dataclass(frozen=True)
class Raised:
    """An attention item the harness raises from its cause."""

    #: The ticket it is about; None for a PR no ticket owns.
    ticket_key: str | None
    reason: str
    #: What the operator needs to know: the harness's own words, never text it read.
    detail: str
    #: The repository of the ticket's unit it is about.
    repo: str | None = None
    #: The PR it is about, for an item about a review.
    pr: str | None = None


def raised(ctx: Context, derived: Sequence[Derived] | None, now: datetime) -> list[Raised]:
    """Each item of `REASONS` whose cause holds at `now`, or rests on what could not be read fresh.

    `derived` is the tick's derivation, None when it raised: every item that rests on an observation is then kept.

    Returns:
        The items, each once: those whose cause holds, then those kept.
    """
    subjects = _Subjects.of(ctx.conn, derived)
    limits = _Limits.read(ctx)
    found: dict[tuple[str, str, str | None], Raised] = {}
    for item in (
        *_from_rows(ctx, subjects, limits, now),
        *_from_journal(ctx, subjects, now),
        *_kept(ctx, subjects, limits),
    ):
        found.setdefault((item.ticket_key or f"{attention.PR_PREFIX}{item.pr}", item.reason, item.repo), item)
    return list(found.values())


def kept(conn: sqlite3.Connection) -> list[Raised]:
    """Every open item of `REASONS`, as the latest `ok` tick listed it.

    What a tick keeps when it could read no cause at all.

    Returns:
        The items about a ticket or a PR.
    """
    return [_raised(i) for i in attention.current(conn) if i.reason in REASONS and _about_work(i)]


@dataclass(frozen=True)
class _Subjects:
    """The tickets whose items may hold this tick, and what the derivation read of each."""

    #: Each ticket's own row, by key; None when the derivation raised.
    own: Mapping[str, Derived] | None
    #: Each ticket's units' rows, by key.
    units: Mapping[str, Sequence[Derived]]
    #: The open tickets canopy holds, not stopped, and not seen fresh to be closed or no candidate (§17).
    keys: AbstractSet[str]

    @classmethod
    def of(cls, conn: sqlite3.Connection, derived: Sequence[Derived] | None) -> _Subjects:
        journal = {t.key for t in db.open_tickets(conn)} - set(conversation.stopped(conn))
        if derived is None:
            return cls(None, {}, frozenset(journal))
        own = {d.ticket_key: d for d in derived if d.repo is None}
        units: dict[str, list[Derived]] = {}
        for d in derived:
            if d.repo is not None:
                units.setdefault(d.ticket_key, []).append(d)
        left = {key for key, d in own.items() if d.stale is None and (d.closed or not d.candidate)}
        return cls(own, units, frozenset(journal & set(own) - left))

    def unread(self, key: str, repo: str | None, reason: str, *, pr: bool) -> bool:
        """Whether what an item of `reason` about ticket `key`, or its unit in `repo`, rests on was not read fresh.

        `pr` says whether that unit has a PR, whose rows are its own; a unit without one waits on its ticket's rows.

        Returns:
            True for an item about a ticket still held that rests on an observation the derivation found stale, or on
            any when it raised.
        """
        if reason not in OBSERVED or key not in self.keys:
            return False
        if self.own is None:
            return True
        if any(u.repo == repo and u.stale is not None for u in self.units.get(key, ())):
            return True
        # What a ticket's own rows want: its plan, or the run of a unit with no PR.
        return (repo is None or (reason == ATTEMPT_LIMIT and not pr)) and self.own[key].stale is not None


def _from_rows(ctx: Context, subjects: _Subjects, limits: _Limits, now: datetime) -> Iterator[Raised]:
    """The items the derivation's rows raise: each unit's, and each ticket's `attempt_limit`.

    Yields:
        Each, by ticket.
    """
    if subjects.own is None:
        return
    observed = records.select(records.ObservedPr).all(ctx.conn)
    heads = {p.url: p.head_sha for p in observed}
    for key in sorted(subjects.keys):
        units = subjects.units.get(key, ())
        for unit in units:
            url = limits.pr_of(key, unit.repo)
            if unit.stale is None and unit.phases and url is not None:
                yield from _of_unit(ctx, key, unit, url, heads.get(url), now=now)
        yield from _attempt_limits(ctx, key, subjects.own[key], units, limits)


def _of_unit(
    ctx: Context,
    key: str,
    unit: Derived,
    url: str,
    head: str | None,
    *,
    now: datetime,
) -> Iterator[Raised]:
    """The items a unit's rows raise, from its PR at `url`, observed at `head`, at `now` (DESIGN §7, §21, §30).

    Yields:
        Each.
    """
    repo = unit.repo
    if Phase.UNTRUSTED_REVIEW in unit.phases and ctx.config.policy.feedback_plan != "approve":
        why = f"{url} has feedback from a reviewer `trust.trusted_reviewers` does not list"
        yield Raised(key, UNTRUSTED_REVIEW, f"{why}: say what to do about it with `canopy reply {key}`", repo)
    phase: Phase | None = unit.phases[0]
    if phase is Phase.CI_RUNNING and head is not None and repo is not None:
        stuck = _stuck_check(ctx, repo, url, head, now)
        if stuck is not None:
            yield Raised(key, CHECK_STUCK, stuck, repo)
    if phase is Phase.REVIEW_PENDING:
        limited = _review_limit(ctx, key, url, head)
        if limited is None:
            return
        yield Raised(key, REVIEW_LIMIT, limited, repo, pr=url)
        # At its limit, the unit is the next row's (DESIGN §21).
        phase = unit.phases[1] if len(unit.phases) > 1 else None
    if phase is Phase.GREEN_UNREVIEWED:
        yield Raised(key, NEEDS_REVIEWER, f"{url} passes its checks and no person has approved it", repo)
    elif phase is Phase.APPROVED:
        yield Raised(key, READY_TO_MERGE, f"{url} is approved by a person and waits to be merged", repo)


def _stuck_check(ctx: Context, repo: str, url: str, head: str, now: datetime) -> str | None:
    """Name the one CI check of the PR at `url` in `repo` pending at `head` `STUCK_AFTER` past its others finishing.

    Every other CI check there has completed and none failed; the time runs from when a source first saw the last of
    their runs completed. A commit status has no run whose time the journal keeps, so it counts as finished but sets
    no time. Two pending, no run to time, or one failed, which a worker's `resume` answers, raise nothing: none of
    those tells a check that never completes from a slow build (§30).

    Returns:
        The item's detail, naming the check and the map's key that gives it a role, or None.
    """
    roles = ctx.workspace.check_roles(repo)
    query = records.select(records.ObservedCheck).where("pr_url = ? AND head_sha = ?", url, head)
    checks = query.all(ctx.conn)
    ci = [c for c in checks if roles.get(c.name, CheckRole.CI) is CheckRole.CI]
    pending = [c.name for c in ci if c.status is not CheckStatus.COMPLETED]
    finished = [c for c in ci if c.status is CheckStatus.COMPLETED]
    if len(pending) != 1 or any(c.conclusion in observe.FAILED for c in finished):
        return None
    last = _finished_at(ctx.conn, url, [c.run_id for c in finished if c.run_id is not None])
    if last is None or now - last < STUCK_AFTER:
        return None
    [name] = pending
    # The name as a TOML key, quoted and escaped, so the line the item suggests is one the map accepts as written.
    key = json.dumps(name)
    return (
        f"`{name}` is still pending on {url} at {head[:12]}, over {STUCK_AFTER // timedelta(minutes=1)} minutes after "
        f"its other checks finished, holding it at ci_running; if it is not CI, give it a role in "
        f'`[repos.{repo}.checks]`: `{key} = "merge"` for a merge queue, `"human"` for a sign-off, or `"ignore"`'
    )


def _finished_at(conn: sqlite3.Connection, url: str, run_ids: Iterable[int]) -> datetime | None:
    """When a source first saw the last of the PR at `url`'s check runs `run_ids` completed.

    Returns:
        The time, or None for no run the journal kept.
    """
    query = sql.select("MAX(observed_at)").from_("observed_check_runs").where("pr_url = ?", url)
    found = sql.execute(conn, query.where_in("run_id", list(run_ids))).fetchone()
    return None if found is None or found[0] is None else db.parse_time(str(found[0]))


def _review_limit(ctx: Context, key: str, url: str, head: str | None) -> str | None:
    """Why the PR at `url`, `review_pending` at `head`, gets no review: it has had its review runs.

    Returns:
        The item's detail, or None when the PR may have another review, or one of `head` is running.
    """
    runs = review_runs.review_runs_of(ctx.conn, url)
    limit = grants.limit(ctx.conn, ctx.config, url)
    if len(runs) < limit or any(r.sha == head and r.status is ReviewRunStatus.RUNNING for r in runs):
        return None
    at = f" {head[:12]}" if head else ""
    return f"{key}'s {url} at{at} has no review, and has had {len(runs)} review runs, its limit; {grants.hint(url)}"


@dataclass(frozen=True)
class _Limits:
    """What the journal holds of each ticket's runs and limits (DESIGN §8, §22).

    Its units' PRs, what runs, the runs each unit and ticket has had, and those the operator granted past the policy.
    """

    ctx: Context
    #: Each unit's PR, by ticket and repository.
    prs: Mapping[tuple[str, str], str]
    #: The tickets a worker of which is running.
    running: AbstractSet[str]
    counts: Mapping[policy.Unit, Mapping[str, int]]
    granted: Mapping[policy.Unit, Mapping[str, int]]
    feedback_plans: Mapping[policy.Unit, int]
    plans: Mapping[str, int]

    @classmethod
    def read(cls, ctx: Context) -> _Limits:
        units = db.all_units(ctx.conn).values()
        return cls(
            ctx,
            {(u.ticket_key, u.repo): u.pr_url for found in units for u in found if u.repo and u.pr_url},
            frozenset(str(r["ticket_key"]) for r in db.running_runs(ctx.conn, "runs")),
            policy.attempts(ctx.conn),
            policy.grants(ctx.conn),
            policy.feedback_plan_attempts(ctx.conn),
            policy.ticket_attempts(ctx.conn, policy.PLAN),
        )

    def pr_of(self, key: str, repo: str | None) -> str | None:
        """The PR of `key`'s unit in `repo`.

        Returns:
            Its URL, or None for a unit with none.
        """
        return None if repo is None else self.prs.get((key, repo))

    def reached(self, key: str, repo: str | None) -> bool:
        """Whether no worker of `key` runs, and its unit in `repo`, or with None its plan, is at a limit still.

        Returns:
            True while a kind of run the item may be about is at its limit: a grant past it ends the item.
        """
        if key in self.running:
            return False
        if repo is None:
            return self.plan(key) is not None
        kinds = (RunKind.IMPLEMENT, RunKind.RESUME, policy.FEEDBACK_PLAN)
        return any(self.unit(key, repo, kind) is not None for kind in kinds)

    def unit(self, key: str, repo: str, kind: str) -> str | None:
        """Whether `key`'s unit in `repo` has had its runs of `kind`, `implement`, `resume`, or `feedback-plan`.

        Returns:
            The item's detail, or None while it may have another.
        """
        name = policy.unit(key, repo)
        granted = self.granted.get(name, {})
        if kind == policy.FEEDBACK_PLAN:
            done, limit = self.feedback_plans.get(name, 0), policy.feedback_plan_limit(self.ctx.config, granted)
        else:
            done = self.counts.get(name, {}).get(kind, 0)
            limit = policy.unit_limits(self.ctx.config, granted)[kind]
        if done < limit:
            return None
        return (
            f"{key} in {repo} has had {done} {kind} runs and the limit is {limit}; "
            f"`canopy grant {key} {kind} --repo {repo}` allows another"
        )

    def plan(self, key: str) -> str | None:
        """Whether ticket `key` has had its plan runs, which count per ticket.

        Returns:
            The item's detail, or None while it may have another.
        """
        done = self.plans.get(key, 0)
        limit = policy.ticket_limit(self.ctx.conn, self.ctx.config, key, policy.PLAN)
        if done < limit:
            return None
        return f"{key} has had {done} plan runs and the limit is {limit}; `canopy grant {key} plan` allows another"


def _attempt_limits(
    ctx: Context,
    key: str,
    own: Derived,
    units: Sequence[Derived],
    limits: _Limits,
) -> Iterator[Raised]:
    """The `attempt_limit` items of a ticket whose next run, as its rows say, is past its limit (DESIGN §8).

    A unit's `resume` rows want a `resume` of it, or first a feedback plan where one is needed and the ticket has none
    (§32); `ready` wants the ticket's plan where one is needed and none is approved or waits (§25), and otherwise an
    `implement` in each repository it has had one in, or the workspace's one; `human_replied` on a ticket with a branch
    wants a `resume` of each unit. Whether a `blocked` ticket is stacked is judgment, and a running one wants no run.

    Yields:
        Each, about the unit at its limit, or the ticket for its plan.
    """
    if key in limits.running:
        return
    if Phase.READY in own.phases and Phase.PLAN_PROPOSED not in own.phases:
        yield from _ready(ctx, key, units, limits)
    for repo, reasons in sorted(_resumes(own, units).items()):
        detail = limits.unit(key, repo, RunKind.RESUME)
        if detail is None and feedback_plans.needed(ctx.config.policy, reasons) and not _planned(ctx.conn, key):
            detail = limits.unit(key, repo, policy.FEEDBACK_PLAN)
        if detail is not None:
            yield Raised(key, ATTEMPT_LIMIT, detail, repo)


def _resumes(own: Derived, units: Sequence[Derived]) -> dict[str, set[ResumeReason]]:
    """The units a ticket's rows want resumed, each with the reasons its `resume` would carry (DESIGN §7, §8).

    Returns:
        By repository: a fresh unit's `resume` rows', and every unit's `reply` for `human_replied` on a ticket with a
        branch, which neither `ready` nor `blocked` has.
    """
    wanted: dict[str, set[ResumeReason]] = {}
    for unit in units:
        reasons = {RESUME_ROWS[p] for p in unit.phases if p in RESUME_ROWS}
        if reasons and unit.stale is None and unit.repo is not None:
            wanted.setdefault(unit.repo, set()).update(reasons)
    if Phase.HUMAN_REPLIED in own.phases and not {Phase.READY, Phase.BLOCKED} & set(own.phases):
        for unit in units:
            if unit.repo is not None:
                wanted.setdefault(unit.repo, set()).add(ResumeReason.REPLY)
    return wanted


def _ready(ctx: Context, key: str, units: Sequence[Derived], limits: _Limits) -> Iterator[Raised]:
    """The `attempt_limit` of a `ready` ticket: its plan's, or its `implement`'s in each repository it may take.

    Yields:
        Each.
    """
    ticket = db.get_ticket(ctx.conn, key)
    setting = None if ticket is None else ticket.plan_setting
    if plans.needed(ctx.config.policy.plan, setting) and plans.approved_of(ctx.conn, key) is None:
        detail = limits.plan(key)
        if detail is not None:
            yield Raised(key, ATTEMPT_LIMIT, detail)
        return
    repos = [str(u.repo) for u in units if u.repo is not None]
    if not repos and len(ctx.workspace.repos) == 1:
        repos = [ctx.workspace.repos[0].name]
    for repo in repos:
        detail = limits.unit(key, repo, RunKind.IMPLEMENT)
        if detail is not None:
            yield Raised(key, ATTEMPT_LIMIT, detail, repo)


def _planned(conn: sqlite3.Connection, key: str) -> bool:
    """Whether ticket `key` has a feedback plan no `resume` has spent, so its next run is no feedback plan (§32).

    Returns:
        True when one waits on the operator, or for the `resume` that follows it.
    """
    plan = feedback_plans.current(conn, key)
    return plan is not None and plan.status is not PlanStatus.SUPERSEDED and plan.spent_run_id is None


def _from_journal(ctx: Context, subjects: _Subjects, now: datetime) -> Iterator[Raised]:
    """The items the journal alone raises: each ticket's plans', and each PR's failed review.

    Yields:
        Each.
    """
    for key in sorted(subjects.keys):
        ticket = db.get_ticket(ctx.conn, key)
        if ticket is not None:
            yield from _plans(ctx, ticket)
    yield from _review_failures(ctx, subjects.keys, now)


def _plans(ctx: Context, ticket: records.Ticket) -> Iterator[Raised]:
    """A ticket's `plan_review` and `plan_changed`: its plan, or its feedback plan, waiting or changed (§25, §32).

    Yields:
        Each.
    """
    key, conn, state_dir = ticket.key, ctx.conn, ctx.state_dir
    plan = plans.current(conn, key)
    if plan is not None and plans.waits(conn, ticket) and plans.question(conn, key) is None:
        detail = f"plan {plan.id} waits: canopy show {key}, then canopy plan {key} --approve or canopy reply {key}"
        yield Raised(key, PLAN_REVIEW, detail)
    elif plan is not None and plan.status is PlanStatus.APPROVED and plans.approved_text(state_dir, plan) is None:
        path = plans.path_for(state_dir, key, plan.run_id)
        detail = f"plan {plan.id} of {key}, {path}, is no longer the text you approved: approve it again, or skip it"
        yield Raised(key, PLAN_CHANGED, detail)
    if ctx.config.policy.feedback_plan != "approve":
        return
    found = feedback_plans.current(conn, key)
    if found is None or found.spent_run_id is not None:
        return
    if found.status is PlanStatus.PROPOSED and _feedback_waits(conn, ticket):
        detail = f"feedback plan {found.id} waits: canopy plan {key} --approve or canopy reply {key}"
        yield Raised(key, PLAN_REVIEW, detail)
    elif found.status is PlanStatus.APPROVED and feedback_plans.approved_text(state_dir, found) is None:
        path = plans.path_for(state_dir, key, found.run_id)
        detail = f"feedback plan {found.id} of {key}, {path}, is no longer the text you approved: approve it again"
        yield Raised(key, PLAN_CHANGED, detail)


def _feedback_waits(conn: sqlite3.Connection, ticket: records.Ticket) -> bool:
    """Whether a ticket's proposed feedback plan waits on the operator: no planner at work, and no change asked.

    Returns:
        True while it waits on their word.
    """
    running = db.running_run_of(conn, ticket.key)
    if running is not None and running.kind == RunKind.FEEDBACK_PLAN:
        return False
    return feedback_plans.changes_asked(conn, ticket) is None


def _review_failures(ctx: Context, keys: AbstractSet[str], now: datetime) -> Iterator[Raised]:
    """`review_failed` for each PR whose latest review run, in the window the state block shows (§21), failed.

    One of the loop's own PRs raises it about its ticket's unit, while the ticket is held; another PR about itself. It
    goes when a newer run starts, the run leaves the window, or a fresh read shows the PR merged or closed.

    Yields:
        Each, by PR.
    """
    since = db.format_time(now - review_view.RECENT)
    latest: dict[str, records.ReviewRun] = {}
    for run in review_runs.review_runs_since(ctx.conn, since, revisions=True):
        latest.setdefault(run.pr_url, run)
    cutoff = db.format_time(now - timedelta(minutes=ctx.config.connect.max_age_minutes))
    closed = _closed_prs(ctx.conn, cutoff, [url for url, run in latest.items() if run.status in FAILED_REVIEWS])
    units = {(u.ticket_key, u.pr_url): u.repo for found in db.all_units(ctx.conn).values() for u in found}
    for url, run in sorted(latest.items()):
        if run.status not in FAILED_REVIEWS or url in closed:
            continue
        what = "revision run" if run.revises is not None else "review run"
        detail = f"{what} {run.id} of {url} at {run.sha[:12]} ended {run.status}; log {run.log_path}"
        key = run.ticket_key
        if key is None:
            yield Raised(None, REVIEW_FAILED, detail, pr=url)
        elif key in keys and (key, url) in units:
            yield Raised(key, REVIEW_FAILED, detail, units[key, url], pr=url)


def _closed_prs(conn: sqlite3.Connection, cutoff: str, urls: Iterable[str]) -> set[str]:
    """Which of the PRs at `urls` a read since `cutoff` saw merged or closed.

    Returns:
        Their URLs.
    """
    query = (
        sql.select("url")
        .from_("observed_prs")
        .where_in("url", list(urls))
        .where("state != ? AND observed_at >= ?", PrState.OPEN, cutoff)
    )
    return {str(r[0]) for r in sql.execute(conn, query)}


def _kept(ctx: Context, subjects: _Subjects, limits: _Limits) -> Iterator[Raised]:
    """The open items whose cause rests on an observation not read fresh: each as the latest `ok` tick listed it.

    An item about a limit goes all the same once the journal shows the limit lifted, by a grant or a newer run.

    Yields:
        Each.
    """
    for item in attention.current(ctx.conn):
        key, repo, reason = item.ticket_key, item.repo, item.reason
        if reason not in REASONS or key is None:
            continue
        url = limits.pr_of(key, repo)
        if not subjects.unread(key, repo, reason, pr=url is not None):
            continue
        if reason == ATTEMPT_LIMIT and not limits.reached(key, repo):
            continue
        if reason == REVIEW_LIMIT and (url is None or _review_limit(ctx, key, url, None) is None):
            continue
        yield _raised(item)


def _about_work(item: attention.Item) -> bool:
    """Whether an item is about a ticket or a PR, not a chore or a one-off task.

    Returns:
        True for a ticket's or a PR's.
    """
    key = item.ticket_key
    return key is not None and not key.startswith((attention.CHORE_PREFIX, attention.TASK_PREFIX))


def _raised(item: attention.Item) -> Raised:
    """An open item, raised again as it was listed.

    Returns:
        The item about its ticket, or its PR when it has none.
    """
    key = str(item.ticket_key)
    if key.startswith(attention.PR_PREFIX):
        return Raised(None, item.reason, item.detail, item.repo, pr=key.removeprefix(attention.PR_PREFIX))
    return Raised(key, item.reason, item.detail, item.repo)
