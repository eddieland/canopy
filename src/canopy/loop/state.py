"""The overseer's state block: the `## State` section that is each tick's whole message to it (DESIGN §6 step 4)."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, NotRequired, TypedDict, cast

from canopy.core import contract, conversation, db, item_numbers, plans, pools
from canopy.core.vocab import FlakyCause, ResumeReason
from canopy.loop.observations import rendered as rendered_observations
from canopy.reviews import view as review_view
from canopy.runs import feedback_plans, policy, tasks

if TYPE_CHECKING:
    from canopy.core import records
    from canopy.core.chore_view import ChoreSummary
    from canopy.core.config import Config
    from canopy.core.notice import Notice
    from canopy.core.workspace import Workspace
    from canopy.loop.attention import OpenItem
    from canopy.loop.harness import Decided
    from canopy.loop.harness_dispatches import ToCome
    from canopy.loop.observations import ObservationsState, UnitObservation
    from canopy.reviews.view import ReviewsSection
    from canopy.runs.reconcile import Capacity

#: A time as the journal writes it (`db.format_time`): a value that is one, and nothing else, shows its minute.
_JOURNAL_TIME = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}):[0-9]{2}\.[0-9]{3}Z")


class OverseerState(TypedDict):
    """The state block's JSON: what the journal knows, the config the overseer decides by, and this tick.

    It has `chores` only when chores are configured, `reviews` only when reviews are on, `notices` only when the
    operator set a notice lately, `harness` only when the harness decided a ticket this tick, and `dispatches_to_come`
    only when it dispatches after the overseer (DESIGN §37).
    `observations` is the world as the connectors last read it (DESIGN §35). As rendered, `tickets` leave out every
    key, at any depth, whose value is null or an empty list or object, as the overseer's prompt says once.
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
    #: The ticket's branch only when none of its units carries it: a unit's `branch` says it once.
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
    """A ticket's latest run. `reasons` only for a `resume` that named them (DESIGN §8).

    Its branch is the ticket's, on its units, and when it started is not read: neither is repeated here.
    """

    run_id: int
    kind: str
    reasons: NotRequired[list[str]]
    status: str
    #: Present, and true, only when the worker left a failed check as not the change's (DESIGN §23): one bit of its
    #: result, never its text (TRUST_MODEL T1).
    flaky: NotRequired[bool]
    #: Present only with `flaky`, when the worker named where the check failed (DESIGN §23): `test`, `runner`, or
    #: `service`, a word of a closed vocabulary, never its text or its `flaky_detail`.
    flaky_cause: NotRequired[FlakyCause]
    #: Present only when the harness pushed the branch again to rerun the checks the worker left as flaky (DESIGN §23):
    #: the repositories it pushed, whose checks run again on the new head. A unit not named was not kicked.
    kicked: NotRequired[list[str]]
    #: Present only when the run was stacked, some repository's base another ticket's branch (DESIGN §10): the base
    #: each repository started from. An unstacked run's base is its repository's own, which no decision reads.
    repos: NotRequired[list[RunRepo]]
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
    first; the block keeps an ended one only while a check it may hold could stand (`_notices`), and with none, has no
    `notices` key. `private` holds each private ticket's conversation state, by
    key (DESIGN §22); a public ticket has no `private` key. `operator` holds a public ticket's operator messages
    newer than its message cursor, by key; a ticket without any has no `operator` key (DESIGN §7, D089). `planned`
    holds a ticket's plan, by key: whether it needs one, its plan attempts and limit, and its newest plan's id,
    status, and time, never its text (DESIGN §25); a ticket plans do not touch has no `plan` key. `feedback_planned`
    holds a ticket's feedback plan, by key, likewise; a ticket feedback plans do not touch has no `feedback_plan` key
    (DESIGN §32). `attention` is the open items the overseer recorded (`attention.for_overseer`), so it sees what
    leaving one out drops (ROADMAP M28). `operator_sent` holds, by PR, the comments
    and reviews the operator sent through canopy (`drafts.sent_by_pr`); a unit whose PR has none has no
    `operator_sent` key (DESIGN §29). `observations` is what the connectors last read of every ticket the block lists
    or the query returned, each subject fresh, stale, or unobserved (`observations.section`, DESIGN §35). `numbered`
    holds the items the cursors name, by journal number.

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
        its_units = units.get(key, [])
        summary: TicketState = {
            "key": key,
            "title": t.title,
            "phase": t.phase,
            "branch": None if any(u.branch == t.branch for u in its_units) else t.branch,
            "cursors": {name: getattr(t, column) for name, column in db.TICKET_CURSORS.items()},
            "units": [unit_summary(key, u) for u in its_units],
            "needs_human_since": t.needs_human_since,
            "last_seen_at": t.last_seen_at,
            "last_run": _run_summary(last_runs.get(key), run_slots, run_reasons, config.trust.branch_prefix),
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

    listed = [ticket_summary(t) for t in tickets]
    shown = _notices(notices, now, listed, observations)
    # A listed ticket's title, which its observation then leaves out where the tracker's is the same.
    titles = {t["key"]: t["title"] for t in listed}
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
        "tickets": _name_cursors(listed, numbered or {}),
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
        **({"reviews": _scoped(reviews, listed, observations)} if reviews is not None else {}),
        # The operator's notices, in force or lately ended: a failed check that ran while one was in force, and that it
        # explains, is held, not fixed (DESIGN §7).
        **({"notices": shown} if shown else {}),
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
            json.dumps(
                _to_the_minute(
                    {
                        **state,
                        "tickets": _compact(state["tickets"]),
                        **({"chores": _compact(state["chores"])} if "chores" in state else {}),
                        **({"reviews": _by_unit(state["reviews"], state["tickets"])} if "reviews" in state else {}),
                        "observations": rendered_observations(state["observations"], titles),
                    },
                ),
                separators=(",", ":"),
            ),
            "```",
            "",
        ],
    )


def _to_the_minute(value: object) -> object:
    """`value` as the state block renders its times: each value that is a journal time, to the minute, as `...T09:40Z`.

    The seconds are dropped, never rounded up. A string with a time among other text, such as a comment's body, a
    `why`, or a cursor item's description, stays as it is; no tool takes a time back, so none is compared with the
    journal's.

    Returns:
        A copy of `value` with those times shortened.
    """
    if isinstance(value, str):
        time = _JOURNAL_TIME.fullmatch(value)
        return f"{time[1]}Z" if time is not None else value
    if isinstance(value, Mapping):
        return {str(k): _to_the_minute(v) for k, v in cast("Mapping[object, object]", value).items()}
    # A string is taken above: any other sequence is a JSON array.
    if isinstance(value, Sequence):
        return [_to_the_minute(v) for v in cast("Sequence[object]", value)]
    return value


def _name_cursors(tickets: list[TicketState], numbered: Mapping[int, records.ItemNumber]) -> list[TicketState]:
    """Say, in each ticket's and unit's `cursor_items`, what each of its cursors that is a journal number names.

    The message cursor is a message's id, whose message the conversation holds, so it is not named (DESIGN §35).

    Returns:
        `tickets`, each given its key only where a cursor names an item.
    """

    def items(cursors: Mapping[str, str | int | None], names: Iterable[str]) -> dict[str, str]:
        found = {name: numbered.get(value) for name in names if isinstance(value := cursors[name], int)}
        return {name: item_numbers.describe(item) for name, item in found.items() if item is not None}

    for ticket in tickets:
        if named := items(ticket["cursors"], ["comment"]):
            ticket["cursor_items"] = named
        for unit in ticket["units"]:
            if named := items(unit["cursors"], db.UNIT_CURSORS):
                unit["cursor_items"] = named
    return tickets


def _run_summary(
    run: records.Run | None,
    run_slots: Mapping[int, Sequence[records.RunSlot]],
    run_reasons: Mapping[int, Sequence[str]],
    branch_prefix: str,
) -> RunState | None:
    if run is None:
        return None
    summary: RunState = {"run_id": run.id, "kind": run.kind, "status": run.status, "ended_at": run.ended_at}
    slots = run_slots.get(run.id, [])
    # A stacked base is always under the prefix, as the dispatch guard checks (DESIGN §10); a repository's own is not.
    if any(_under(branch_prefix, s.base_branch) for s in slots):
        summary["repos"] = [{"repo": s.repo, "base": s.base_branch} for s in slots]
    if run.id in run_reasons:
        summary["reasons"] = list(run_reasons[run.id])
    # Only a `resume` for `ci` is asked whether a failure was the change's: from any other run the bit means nothing.
    stored = contract.stored_object(run.result_json)
    if ResumeReason.CI in summary.get("reasons", ()) and stored.get("flaky") is True:
        summary["flaky"] = True
        cause = stored.get("flaky_cause")
        if isinstance(cause, str) and cause in FlakyCause:
            summary["flaky_cause"] = FlakyCause(cause)
        # Written by the harness alone: a worker's result keeps only the contract's fields.
        kicked = stored.get("kicked")
        if isinstance(kicked, list) and kicked:
            summary["kicked"] = [str(repo) for repo in kicked]
    return summary


def _under(prefix: str, branch: str | None) -> bool:
    return branch is not None and branch.removeprefix(prefix) != branch


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


# The reviews of the PRs the overseer may act on this tick: its listed tickets' and the review query's (DESIGN §21). A
# query not read fresh finds none: the overseer reads no GitHub (§39), so it waits for the `vcs` source's next read.
def _scoped(reviews: ReviewsSection, listed: Sequence[TicketState], observations: ObservationsState) -> ReviewsSection:
    query = observations.get("review_query")
    fresh = query is not None and query["observed"] == "fresh"
    return review_view.scoped(
        reviews,
        tickets={t["key"] for t in listed},
        prs={u["pr_url"] for t in listed for u in t["units"] if u["pr_url"] is not None},
        found=frozenset(query.get("result", [])) if query is not None and fresh else frozenset(),
    )


def _by_unit(reviews: ReviewsSection, tickets: Sequence[TicketState]) -> object:
    """`reviews` as the state block renders them: empty values left out, as in `tickets`, and each URL said once.

    A reviewed PR of a listed ticket's unit is named by its `ticket` and `repo`, its URL being that unit's `pr_url`;
    any other keeps its `url`.

    Returns:
        A copy of `reviews` so cut.
    """
    repos = {(t["key"], u["pr_url"]): u["repo"] for t in tickets for u in t["units"] if u["pr_url"] is not None}
    prs: list[object] = []
    for pr in reviews["prs"]:
        repo = repos.get((pr["ticket"], pr["url"])) if pr["ticket"] is not None else None
        rest = {k: v for k, v in pr.items() if k not in {"url", "ticket"}}
        prs.append(pr if repo is None else {"ticket": pr["ticket"], "repo": repo, **rest})
    return _compact({**reviews, "prs": prs})


def _notices(
    notices: Iterable[Notice],
    now: datetime,
    listed: Sequence[TicketState],
    observations: ObservationsState,
) -> list[NoticeState]:
    """The notices the overseer reads: each in force, and each ended while a check it may hold is in front of it.

    A check a notice held stays held after the notice ends, until a newer run of it exists (DESIGN §8), so an ended
    notice matters while some unit observed fresh shows a failed check at its head newer than the unit's `ci` cursor:
    a held check leaves the cursor short of it, and one at or behind the cursor is a `resume`'s already. A unit not
    observed fresh shows the overseer no checks, and a dispatch resting on it is refused `stale`; the block keeps the
    notice again on the tick a fresh read shows such a check.

    Returns:
        Those notices, newest first, as the state block carries them.
    """
    cursors = {(t["key"], u["repo"]): u["cursors"].get("ci") for t in listed for u in t["units"]}
    held = any(
        _may_hold(u, cursors.get((t["key"], u["repo"]))) for t in observations["tickets"] for u in t.get("units", [])
    )
    return [_notice(n, now) for n in notices if held or n.in_force(now)]


def _may_hold(unit: UnitObservation, cursor: str | int | None) -> bool:
    # A unit the block does not list has no cursor here, so any failed check of it may be held.
    checks = unit.get("checks")
    if unit["observed"] != "fresh" or checks is None:
        return False
    at = cursor if isinstance(cursor, int) else None
    return any(item_numbers.newer(c["number"], at) for c in checks["failed"])


def _notice(held: Notice, now: datetime) -> NoticeState:
    return {"text": held.text, "set_at": held.set_at, "until": held.until, "in_force": held.in_force(now)}


def _compact(value: object) -> object:
    """`value` as the state block renders a ticket, a chore, or `reviews`: every key, at any depth, left out if empty.

    Empty is null, or an empty list or object, so a cursor not yet set, a plan with no `newest`, a private ticket's
    `new_operator_messages` with none new, and a chore's `latest_run` before its first run are absent rather than
    spelled out. False and zero stay: a plan's and a
    feedback plan's flags are read as false as often as true, and an attempt count is compared with its limit.

    Returns:
        A copy of `value` without those keys.
    """
    if isinstance(value, Mapping):
        kept = {str(k): _compact(v) for k, v in cast("Mapping[object, object]", value).items()}
        return {k: v for k, v in kept.items() if not _empty(v)}
    if isinstance(value, list):
        return [_compact(v) for v in cast("list[object]", value)]
    return value


def _empty(value: object) -> bool:
    # Neither `False` nor `0` equals `[]` or `{}`, so both stay.
    return value is None or value in ([], {})


def _stamp(moment: datetime | None) -> str | None:
    return db.format_time(moment) if moment is not None else None
