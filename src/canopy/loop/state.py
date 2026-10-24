"""The overseer's state block: the `## State` section that is each tick's whole message to it (DESIGN §6 step 4)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, NotRequired, TypedDict

from canopy.core import contract, conversation, db, feedback_plans, item_numbers, plans, pools, tasks
from canopy.core.vocab import ResumeReason
from canopy.runs import policy

if TYPE_CHECKING:
    from canopy.core import records
    from canopy.core.chore_view import ChoreSummary
    from canopy.core.config import Config
    from canopy.core.notice import Notice
    from canopy.core.workspace import Workspace
    from canopy.loop.attention import OpenItem
    from canopy.loop.harness import Decided
    from canopy.loop.harness_dispatches import ToCome
    from canopy.loop.observations import ObservationsState
    from canopy.reviews.view import ReviewsSection
    from canopy.runs.reconcile import Capacity


class OverseerState(TypedDict):
    """The state block's JSON: what the journal knows, the config the overseer decides by, and this tick.

    It has `chores` only when chores are configured, `reviews` only when reviews are on, `notices` only when the
    operator set a notice lately, `harness` only when the harness decided a ticket this tick, and `dispatches_to_come`
    only when it dispatches after the overseer (DESIGN §37).
    `observations` is the world as the connectors last read it (DESIGN §35).
    """

    repository: str
    workspace: WorkspaceState
    tracker: TrackerState
    trust: TrustState
    policy: PolicyState
    repositories: list[RepositoryState]
    tickets: list[TicketState]
    stopped: list[str]
    recently_done: list[str]
    harness: NotRequired[list[Decided]]
    dispatches_to_come: NotRequired[ToCome]
    chores: NotRequired[list[ChoreSummary]]
    reviews: NotRequired[ReviewsSection]
    notices: NotRequired[list[NoticeState]]
    attention: list[OpenItem]
    observations: ObservationsState
    capacity: CapacityState
    running_workers: list[RunningWorker]
    query_due: bool
    tick_id: int
    now: str
    dry_run: bool


class TicketState(TypedDict):
    """A ticket the loop knows. `private` is a private ticket's conversation, `operator` a public one's new messages.

    `cursor_items` says what each cursor that is a journal number names, only when one does (DESIGN §35).
    """

    key: str
    title: str | None
    phase: str | None
    branch: str | None
    cursors: dict[str, str | int | None]
    cursor_items: NotRequired[dict[str, str]]
    units: list[UnitState]
    needs_human_since: str | None
    last_seen_at: str
    last_run: RunState | None
    private: NotRequired[conversation.PrivateSection]
    operator: NotRequired[conversation.OperatorSection]
    plan: NotRequired[plans.PlanState]
    feedback_plan: NotRequired[feedback_plans.FeedbackPlanState]


class UnitState(TypedDict):
    """One of a ticket's units: a repository's branch and PR. `granted` only when the operator granted it runs.

    `cursor_items` says what each cursor names, only when one does (DESIGN §35).
    """

    repo: str
    branch: str | None
    pr_url: str | None
    phase: str | None
    cursors: dict[str, str | int | None]
    cursor_items: NotRequired[dict[str, str]]
    attempts: dict[str, int]
    ci_cooldown_until: str | None
    granted: NotRequired[dict[str, int]]
    operator_sent: NotRequired[SentState]


class SentState(TypedDict):
    """What the operator sent through canopy on a unit's PR, by GitHub's ids (DESIGN §29): never review feedback."""

    comments: list[int]
    reviews: list[int]


class RunState(TypedDict):
    """A ticket's latest run. `reasons` only for a `resume` that named them (DESIGN §8)."""

    run_id: int
    kind: str
    reasons: NotRequired[list[str]]
    status: str
    #: Present, and true, only when the worker left a failed check as not the change's (DESIGN §23): one bit of its
    #: result, never its text (TRUST_MODEL T1).
    flaky: NotRequired[bool]
    branch: str | None
    repos: list[RunRepo]
    started_at: str
    ended_at: str | None


class RunRepo(TypedDict):
    """A repository a run worked in, and the branch its slot was based on."""

    repo: str | None
    base: str | None


class WorkspaceState(TypedDict):
    """The workspace's name, and its map's prose file if it has one."""

    name: str
    map: str | None


class TrackerState(TypedDict):
    """The tracker settings the overseer queries and labels by."""

    provider: str
    query: str
    labels: list[str]
    needs_human_label: str


class TrustState(TypedDict):
    """Whom the overseer trusts, and how canopy's own comments, branches, and PRs are marked."""

    authorized_repliers: list[str]
    trusted_reviewers: list[str]
    comment_prefix: str
    comment_suffix: str
    branch_prefix: str


class PolicyState(TypedDict):
    """The attempt limits and cooldowns the harness enforces."""

    max_implement_attempts: int
    max_resume_attempts: int
    ci_cooldown_minutes: int
    stacking: str


class RepositoryState(TypedDict):
    """A repository in the workspace, and its slots leased now."""

    name: str
    path: str
    # The map's clone URL, None when the map gives none: how a PR's URL is matched to its repository.
    url: str | None
    summary: str
    cloned: bool
    leased_slots: list[LeasedSlot]


class LeasedSlot(TypedDict):
    """A slot leased from a repository's pool."""

    path: str
    lease_holder: str
    leased_at: str | None


class CapacityState(TypedDict):
    """How many workers may run, are running, and may still start."""

    max_workers: int
    running: int
    available: int


class RunningWorker(TypedDict):
    """A worker run still running. `reasons` only for a `resume` that named them (DESIGN §8)."""

    run_id: int
    ticket: str
    repos: list[str | None]
    kind: str
    reasons: NotRequired[list[str]]
    branch: str | None
    started_at: str


class NoticeState(TypedDict):
    """An operator's notice to workers (DESIGN §8): its text, and from when until when it was or is in force."""

    text: str
    set_at: str
    until: str
    in_force: bool


def state_block(
    config: Config,
    repo_root: Path,
    *,
    tick_id: int,
    dry_run: bool,
    capacity: Capacity,
    workspace: Workspace,
    leased: Mapping[str, Sequence[pools.Slot]],
    running: Iterable[sqlite3.Row],
    tickets: Iterable[records.Ticket],
    stopped: Sequence[str],
    recently_done: Sequence[sqlite3.Row] = (),
    harness: Sequence[Decided] = (),
    dispatches_to_come: ToCome | None = None,
    units: Mapping[str, Sequence[records.TicketUnit]],
    last_runs: Mapping[str, records.Run],
    run_slots: Mapping[int, Sequence[records.RunSlot]],
    run_reasons: Mapping[int, Sequence[str]] | None = None,
    attempts: Mapping[policy.Unit, Mapping[str, int]],
    grants: Mapping[policy.Unit, Mapping[str, int]],
    ci_cooldowns: Mapping[policy.Unit, datetime],
    now: datetime,
    chores: list[ChoreSummary],
    reviews: ReviewsSection | None,
    notices: Sequence[Notice] = (),
    private: Mapping[str, conversation.PrivateSection] | None = None,
    operator: Mapping[str, conversation.OperatorSection] | None = None,
    planned: Mapping[str, plans.PlanState] | None = None,
    feedback_planned: Mapping[str, feedback_plans.FeedbackPlanState] | None = None,
    attention: list[OpenItem] | None = None,
    query_due: bool,
    operator_sent: Mapping[str, Mapping[str, Sequence[int]]] | None = None,
    observations: ObservationsState,
    numbered: Mapping[int, records.ItemNumber] | None = None,
) -> str:
    """Render the `## State` section the harness sends the overseer as its message, after its prompt.

    `tickets` leave out the tickets the operator stopped, which `stopped` names by key (DESIGN §22), and the tickets
    marked done; `recently_done` names by key those marked done lately, so the overseer leaves out one the
    tracker still shows open (DESIGN §7). `harness` names the tickets the harness decided this tick, each with its
    decision, which `tickets` and `observations` leave out; with none, the block has no `harness` key (DESIGN §37).
    `dispatches_to_come` are the harness's after the overseer, and the workers they hold; their tickets are left out
    too. `units` are each ticket's units, and `run_slots` and `run_reasons` each running or latest run's slots and,
    for a `resume`, its reasons, by run id (DESIGN §8). `attempts`, `grants`, and `ci_cooldowns` are per unit
    (`policy.unit`); a unit the operator granted no runs has no `granted` key (DESIGN §22). An old `fix-ci` run counts
    in a unit's `resume` attempts, and its kind is in none; an old `split` run counts nowhere. `chores` are the
    configured chores with a `when` (DESIGN §19, §37); with none, the block has no `chores` key, exactly as before
    chores existed. `notices` are the operator's notices in force or ended lately (`notice.recent`), newest
    first; with none, the block has no `notices` key. `private` holds each private ticket's conversation state, by
    key (DESIGN §22); a public ticket has no `private` key. `operator` holds a public ticket's operator messages
    newer than its message cursor, by key; a ticket without any has no `operator` key (DESIGN §7, D089). `planned`
    holds a ticket's plan, by key: whether it needs one, its plan attempts and limit, and its newest plan's id,
    status, and time, never its text (DESIGN §25); a ticket plans do not touch has no `plan` key. `feedback_planned`
    holds a ticket's feedback plan, by key, likewise; a ticket feedback plans do not touch has no `feedback_plan` key
    (DESIGN §32). `attention` is the open items the overseer recorded (`attention.for_overseer`), so it sees what
    leaving one out drops (ROADMAP M28). `query_due` says whether the overseer runs the tracker query this tick or
    works the tickets the block lists alone (DESIGN §7, Spacing the query). `operator_sent` holds, by PR, the comments
    and reviews the operator sent through canopy (`drafts.sent_by_pr`); a unit whose PR has none has no
    `operator_sent` key (DESIGN §29). `observations` is what the connectors last read of every ticket the block lists
    or the query returned, each subject fresh, stale, or unobserved (`observations.section`, DESIGN §35). `numbered`
    holds the items the cursors name, by journal number, so a live read of a stale subject can tell what they passed.

    Returns:
        The section as Markdown: its heading, whether the tick is a dry run, and the state as a fenced JSON block.
    """
    private = private or {}
    operator = operator or {}
    planned = planned or {}
    feedback_planned = feedback_planned or {}
    run_reasons = run_reasons or {}
    operator_sent = operator_sent or {}
    no_attempts = dict.fromkeys(policy.KINDS, 0)
    tracked = config.connect.observes_tickets()

    def unit_summary(key: str, u: records.TicketUnit) -> UnitState:
        name = str(u.repo)
        unit = policy.unit(key, name)
        summary: UnitState = {
            "repo": name,
            "branch": u.branch,
            "pr_url": u.pr_url,
            "phase": u.phase,
            "cursors": {cursor: getattr(u, column) for cursor, column in db.UNIT_CURSORS.items()},
            "attempts": dict(attempts.get(unit, no_attempts)),
            "ci_cooldown_until": _stamp(ci_cooldowns.get(unit)),
        }
        if unit in grants:
            summary["granted"] = dict(grants[unit])
        sent = operator_sent.get(u.pr_url) if u.pr_url else None
        if sent is not None:
            summary["operator_sent"] = {"comments": list(sent["comments"]), "reviews": list(sent["reviews"])}
        return summary

    def ticket_summary(t: records.Ticket) -> TicketState:
        key = t.key
        summary: TicketState = {
            "key": key,
            "title": t.title,
            "phase": t.phase,
            "branch": t.branch,
            "cursors": {name: getattr(t, db.ticket_cursor(name, tracked=tracked)) for name in db.TICKET_CURSORS},
            "units": [unit_summary(key, u) for u in units.get(key, [])],
            "needs_human_since": t.needs_human_since,
            "last_seen_at": t.last_seen_at,
            "last_run": _run_summary(last_runs.get(key), run_slots, run_reasons),
        }
        # A private ticket's conversation state, or a public one's new operator messages, each only when it has one.
        if key in private:
            summary["private"] = private[key]
        if key in operator:
            summary["operator"] = operator[key]
        if key in planned:
            summary["plan"] = planned[key]
        if key in feedback_planned:
            summary["feedback_plan"] = feedback_planned[key]
        return summary

    state: OverseerState = {
        "repository": str(repo_root),
        "workspace": {
            "name": workspace.name,
            "map": str(workspace.map_prose) if workspace.map_prose is not None else None,
        },
        "tracker": {
            "provider": config.tracker.provider,
            "query": config.tracker.query,
            "labels": list(config.tracker.labels),
            "needs_human_label": config.tracker.needs_human_label,
        },
        "trust": {
            "authorized_repliers": list(config.trust.authorized_repliers),
            "trusted_reviewers": list(config.trust.trusted_reviewers),
            "comment_prefix": config.trust.comment_prefix,
            "comment_suffix": config.trust.comment_suffix,
            "branch_prefix": config.trust.branch_prefix,
        },
        "policy": {
            "max_implement_attempts": config.policy.max_implement_attempts,
            "max_resume_attempts": config.policy.max_resume_attempts,
            "ci_cooldown_minutes": config.policy.ci_cooldown_minutes,
            "stacking": config.policy.stacking,
        },
        # The overseer runs at the workspace root, which is not a repository: each repository's leased slots stand in
        # for its own `treehouse status` (DESIGN §18). A task's slot is left out: the overseer sees nothing of a task
        # but the capacity its run holds (DESIGN §36).
        "repositories": [
            {
                "name": r.name,
                "path": str(r.path),
                "url": r.url,
                "summary": r.summary,
                "cloned": r.cloned,
                "leased_slots": [
                    {"path": str(s.path), "lease_holder": s.lease_holder, "leased_at": s.leased_at}
                    for s in leased.get(r.name, [])
                    if not tasks.held_by_task(s.lease_holder)
                ],
            }
            for r in workspace.repos
        ],
        "tickets": _name_cursors([ticket_summary(t) for t in tickets], numbered or {}, tracked=tracked),
        # Tickets the operator stopped: not candidates, whatever their labels, and owed no decision (DESIGN §22).
        "stopped": list(stopped),
        # Tickets marked done lately that the query still finds: owed no decision while the tracker shows them open
        # (DESIGN §7). Keys alone, since the overseer only leaves them out.
        "recently_done": [str(t["key"]) for t in recently_done],
        # Tickets the harness decided this tick, in code: the overseer records nothing about one (DESIGN §37).
        **({"harness": list(harness)} if harness else {}),
        # What the harness starts after the overseer, and the workers it holds for them (DESIGN §37).
        **({"dispatches_to_come": dispatches_to_come} if dispatches_to_come is not None else {}),
        **({"chores": chores} if chores else {}),
        # With reviews off, nothing about them reaches the overseer (DESIGN §21).
        **({"reviews": reviews} if reviews is not None else {}),
        # The operator's notices, in force or lately ended: a failed check that ran while one was in force, and that it
        # explains, is held, not fixed (DESIGN §7).
        **({"notices": [_notice(n, now) for n in notices]} if notices else {}),
        # What the overseer keeps on the attention list by recording it again: leaving one out resolves it (§14).
        "attention": attention or [],
        # What changes every tick comes last, after what changes rarely, for a runtime that caches part of a message
        # (DESIGN §6): the observations first, which change with the world and age every tick (DESIGN §35).
        "observations": observations,
        "capacity": {
            "max_workers": capacity.max_workers,
            "running": capacity.running,
            "available": capacity.available,
        },
        "running_workers": [_running_summary(r, run_slots, run_reasons) for r in running],
        # Whether this tick runs the tracker query, or works the tickets above alone (DESIGN §7, Spacing the query).
        "query_due": query_due,
        "tick_id": tick_id,
        "now": db.format_time(now),
        "dry_run": dry_run,
    }
    if dry_run:
        mode = (
            "This is a dry run. `canopy_dispatch` checks its guards and records what it would have done, or the "
            "refusal, and starts nothing. `canopy_ticket-set` records phases but neither advances cursors nor marks "
            "tickets done. Decide exactly as you would otherwise."
        )
    else:
        mode = "This is a live tick."
    return "\n".join(
        [
            "## State",
            "",
            "Generated by the harness for this tick. It is the journal's view of what the loop did,",
            "not what is true now.",
            "",
            mode,
            "",
            "```json",
            # Compact: every step of the tick re-reads the block, and it is about 29% fewer tokens than indented.
            json.dumps(state, separators=(",", ":")),
            "```",
            "",
        ],
    )


def _name_cursors(
    tickets: list[TicketState],
    numbered: Mapping[int, records.ItemNumber],
    *,
    tracked: bool,
) -> list[TicketState]:
    """Say, in each ticket's and unit's `cursor_items`, what each of its cursors that is a journal number names.

    A live read of a stale subject has no numbers, so it compares what it reads with these (DESIGN §35). The message
    cursor is a message's id, whose message the conversation holds, and the comment cursor of a ticket no tracker source
    observes the tracker's own id.

    Returns:
        `tickets`, each given its key only where a cursor names an item.
    """

    def items(cursors: Mapping[str, str | int | None], names: Iterable[str]) -> dict[str, str]:
        found = {name: numbered.get(value) for name in names if isinstance(value := cursors[name], int)}
        return {name: item_numbers.describe(item) for name, item in found.items() if item is not None}

    for ticket in tickets:
        if named := items(ticket["cursors"], ["comment"] if tracked else []):
            ticket["cursor_items"] = named
        for unit in ticket["units"]:
            if named := items(unit["cursors"], db.UNIT_CURSORS):
                unit["cursor_items"] = named
    return tickets


def _run_summary(
    run: records.Run | None,
    run_slots: Mapping[int, Sequence[records.RunSlot]],
    run_reasons: Mapping[int, Sequence[str]],
) -> RunState | None:
    if run is None:
        return None
    summary: RunState = {
        "run_id": run.id,
        "kind": run.kind,
        "status": run.status,
        "branch": run.branch,
        "repos": [{"repo": s.repo, "base": s.base_branch} for s in run_slots.get(run.id, [])],
        "started_at": run.started_at,
        "ended_at": run.ended_at,
    }
    if run.id in run_reasons:
        summary["reasons"] = list(run_reasons[run.id])
    # Only a `resume` for `ci` is asked whether a failure was the change's: from any other run the bit means nothing.
    if ResumeReason.CI in summary.get("reasons", ()) and contract.stored_object(run.result_json).get("flaky") is True:
        summary["flaky"] = True
    return summary


def _running_summary(
    run: sqlite3.Row,
    run_slots: Mapping[int, Sequence[records.RunSlot]],
    run_reasons: Mapping[int, Sequence[str]],
) -> RunningWorker:
    summary: RunningWorker = {
        "run_id": run["id"],
        "ticket": run["ticket_key"],
        "repos": [s.repo for s in run_slots.get(int(run["id"]), [])],
        "kind": run["kind"],
        "branch": run["branch"],
        "started_at": run["started_at"],
    }
    if int(run["id"]) in run_reasons:
        summary["reasons"] = list(run_reasons[int(run["id"])])
    return summary


def _notice(held: Notice, now: datetime) -> NoticeState:
    return {"text": held.text, "set_at": held.set_at, "until": held.until, "in_force": held.in_force(now)}


def _stamp(moment: datetime | None) -> str | None:
    return db.format_time(moment) if moment is not None else None
