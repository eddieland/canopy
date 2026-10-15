"""The overseer's state block: the `## State` section that is each tick's whole message to it (DESIGN §6 step 4)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, NotRequired, TypedDict

from canopy.core import conversation, db
from canopy.runs import policy

if TYPE_CHECKING:
    from canopy.core import treehouse
    from canopy.core.chore_view import ChoreSummary
    from canopy.core.config import Config
    from canopy.core.notice import Notice
    from canopy.core.workspace import Workspace
    from canopy.loop.attention import OpenItem
    from canopy.reviews.view import ReviewsSection
    from canopy.runs.reconcile import Capacity


class OverseerState(TypedDict):
    """The state block's JSON: what the journal knows, the config the overseer decides by, and this tick.

    It has `chores` only when chores are configured, `reviews` only when reviews are on, and `notices` only when the
    operator set a notice lately.
    """

    repository: str
    workspace: WorkspaceState
    tracker: TrackerState
    trust: TrustState
    policy: PolicyState
    repositories: list[RepositoryState]
    tickets: list[TicketState]
    stopped: list[str]
    split_children: list[SplitChild]
    chores: NotRequired[list[ChoreSummary]]
    reviews: NotRequired[ReviewsSection]
    notices: NotRequired[list[NoticeState]]
    attention: list[OpenItem]
    capacity: CapacityState
    running_workers: list[RunningWorker]
    mirror: MirrorState
    tick_id: int
    now: str
    dry_run: bool


class TicketState(TypedDict):
    """A ticket the loop knows. `private` is a private ticket's conversation, `operator` a public one's new messages."""

    key: str
    title: str | None
    phase: str | None
    branch: str | None
    cursors: dict[str, str | int | None]
    units: list[UnitState]
    split_attempts: int
    needs_human_since: str | None
    last_seen_at: str
    last_run: RunState | None
    private: NotRequired[conversation.PrivateSection]
    operator: NotRequired[conversation.OperatorSection]


class UnitState(TypedDict):
    """One of a ticket's units: a repository's branch and PR. `granted` only when the operator granted it runs."""

    repo: str
    branch: str | None
    pr_url: str | None
    phase: str | None
    cursors: dict[str, str | int | None]
    attempts: dict[str, int]
    fix_ci_cooldown_until: str | None
    granted: NotRequired[dict[str, int]]


class RunState(TypedDict):
    """A ticket's latest run."""

    run_id: int
    kind: str
    status: str
    branch: str | None
    repos: list[RunRepo]
    started_at: str
    ended_at: str | None


class RunRepo(TypedDict):
    """A repository a run worked in, and the branch its slot was based on."""

    repo: str
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
    pr_label: str


class PolicyState(TypedDict):
    """The attempt limits and cooldowns the harness enforces."""

    max_implement_attempts: int
    max_fix_ci_attempts: int
    fix_ci_cooldown_minutes: int
    max_resume_attempts: int
    max_split_attempts: int
    stacking: str


class RepositoryState(TypedDict):
    """A repository in the workspace, and its slots leased now."""

    name: str
    path: str
    summary: str
    cloned: bool
    leased_slots: list[LeasedSlot]


class LeasedSlot(TypedDict):
    """A slot leased from a repository's pool."""

    path: str
    lease_holder: str
    leased_at: str | None


class SplitChild(TypedDict):
    """A child of a split not yet done, with its split run's end (DESIGN §18)."""

    child: str
    parent: str
    repo: str
    split_run_id: int
    split_ended_at: str | None


class CapacityState(TypedDict):
    """How many workers may run, are running, and may still start."""

    max_workers: int
    running: int
    available: int


class RunningWorker(TypedDict):
    """A worker run still running."""

    run_id: int
    ticket: str
    repos: list[str]
    kind: str
    branch: str | None
    started_at: str


class NoticeState(TypedDict):
    """An operator's notice to workers (DESIGN §8): its text, and from when until when it was or is in force."""

    text: str
    set_at: str
    until: str
    in_force: bool


class MirrorState(TypedDict):
    """How many tracker comments one tick may mirror, and the heredoc delimiter for their bodies (DESIGN §22)."""

    max_per_tick: int
    body_delimiter: str


def state_block(
    config: Config,
    repo_root: Path,
    *,
    tick_id: int,
    dry_run: bool,
    capacity: Capacity,
    workspace: Workspace,
    leased: Mapping[str, list[treehouse.Slot]],
    running: list[sqlite3.Row],
    tickets: list[sqlite3.Row],
    stopped: Sequence[str],
    units: Mapping[str, list[sqlite3.Row]],
    last_runs: Mapping[str, sqlite3.Row],
    run_slots: Mapping[int, list[sqlite3.Row]],
    attempts: Mapping[policy.Unit, Mapping[str, int]],
    grants: Mapping[policy.Unit, Mapping[str, int]],
    fix_ci_cooldowns: Mapping[policy.Unit, datetime],
    now: datetime,
    split_attempts: Mapping[str, int],
    split_children: list[sqlite3.Row],
    chores: list[ChoreSummary],
    reviews: ReviewsSection | None,
    notices: Sequence[Notice] = (),
    private: Mapping[str, conversation.PrivateSection] | None = None,
    operator: Mapping[str, conversation.OperatorSection] | None = None,
    mirror_delimiter: str,
    attention: list[OpenItem] | None = None,
) -> str:
    """Render the `## State` section the harness sends the overseer as its message, after its prompt.

    `tickets` leave out the tickets the operator stopped, which `stopped` names by key (DESIGN §22). `units` are each
    ticket's units and `run_slots` each running or latest run's slots, by run id. `attempts`, `grants`, and
    `fix_ci_cooldowns` are per unit (`policy.unit`); a unit the operator granted no runs has no `granted` key (DESIGN
    §22). `split_attempts` are per ticket, and `split_children` are the children of splits not yet done, with their
    split run's end (DESIGN §18). `chores` are the configured chores (DESIGN §19); with none, the block has no `chores`
    key, exactly as before chores existed. `notices` are the operator's notices in force or ended lately
    (`notice.recent`), newest first; with none, the block has no `notices` key. `private` holds each private ticket's
    conversation state, by key (DESIGN §22); a public ticket has no `private` key. `operator` holds a public ticket's
    operator messages newer than its message cursor, by key; a ticket without any has no `operator` key (DESIGN §7,
    D089). `mirror_delimiter` ends the heredoc the overseer passes each mirrored comment's body in: the tick's own, so
    no comment can predict it. `attention` is the open items the overseer recorded (`attention.for_overseer`), so it
    sees what leaving one out drops (ROADMAP M28).

    Returns:
        The section as Markdown: its heading, whether the tick is a dry run, and the state as a fenced JSON block.
    """
    private = private or {}
    operator = operator or {}
    no_attempts = dict.fromkeys(policy.KINDS, 0)

    def unit_summary(key: str, u: sqlite3.Row) -> UnitState:
        name = str(u["repo"])
        unit = policy.unit(key, name)
        summary: UnitState = {
            "repo": name,
            "branch": u["branch"],
            "pr_url": u["pr_url"],
            "phase": u["phase"],
            "cursors": {cursor: u[column] for cursor, column in db.UNIT_CURSORS.items()},
            "attempts": dict(attempts.get(unit, no_attempts)),
            "fix_ci_cooldown_until": _stamp(fix_ci_cooldowns.get(unit)),
        }
        if unit in grants:
            summary["granted"] = dict(grants[unit])
        return summary

    def run_summary(run: sqlite3.Row | None) -> RunState | None:
        if run is None:
            return None
        return {
            "run_id": run["id"],
            "kind": run["kind"],
            "status": run["status"],
            "branch": run["branch"],
            "repos": [{"repo": s["repo"], "base": s["base_branch"]} for s in run_slots.get(int(run["id"]), [])],
            "started_at": run["started_at"],
            "ended_at": run["ended_at"],
        }

    def ticket_summary(t: sqlite3.Row) -> TicketState:
        key = str(t["key"])
        summary: TicketState = {
            "key": key,
            "title": t["title"],
            "phase": t["phase"],
            "branch": t["branch"],
            # The mirror cursor is moved by `canopy mirror` itself, never by `--cursor` (DESIGN §22).
            "cursors": {
                **{name: t[column] for name, column in db.TICKET_CURSORS.items()},
                "mirror": t["last_mirrored_id"],
            },
            "units": [unit_summary(key, u) for u in units.get(key, [])],
            "split_attempts": split_attempts.get(key, 0),
            "needs_human_since": t["needs_human_since"],
            "last_seen_at": t["last_seen_at"],
            "last_run": run_summary(last_runs.get(key)),
        }
        # A private ticket's conversation state, or a public one's new operator messages, each only when it has one.
        if key in private:
            summary["private"] = private[key]
        if key in operator:
            summary["operator"] = operator[key]
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
            "pr_label": config.trust.pr_label,
        },
        "policy": {
            "max_implement_attempts": config.policy.max_implement_attempts,
            "max_fix_ci_attempts": config.policy.max_fix_ci_attempts,
            "fix_ci_cooldown_minutes": config.policy.fix_ci_cooldown_minutes,
            "max_resume_attempts": config.policy.max_resume_attempts,
            "max_split_attempts": config.policy.max_split_attempts,
            "stacking": config.policy.stacking,
        },
        # The overseer runs at the workspace root, which is not a repository: each repository's leased slots stand in
        # for its own `treehouse status` (DESIGN §18).
        "repositories": [
            {
                "name": r.name,
                "path": str(r.path),
                "summary": r.summary,
                "cloned": r.cloned,
                "leased_slots": [
                    {"path": str(s.path), "lease_holder": s.lease_holder, "leased_at": s.leased_at}
                    for s in leased.get(r.name, [])
                ],
            }
            for r in workspace.repos
        ],
        "tickets": [ticket_summary(t) for t in tickets],
        # Tickets the operator stopped: not candidates, whatever their labels, and owed no decision (DESIGN §22).
        "stopped": list(stopped),
        # A child is a candidate only with a queue label added after its split run ended (DESIGN §18).
        "split_children": [
            {
                "child": c["child_key"],
                "parent": c["parent_key"],
                "repo": c["repo"],
                "split_run_id": c["run_id"],
                "split_ended_at": c["ended_at"],
            }
            for c in split_children
        ],
        **({"chores": chores} if chores else {}),
        # With reviews off, nothing about them reaches the overseer (DESIGN §21).
        **({"reviews": reviews} if reviews is not None else {}),
        # The operator's notices, in force or lately ended: a failed check that ran while one was in force, and that it
        # explains, is held, not fixed (DESIGN §7).
        **({"notices": [_notice(n, now) for n in notices]} if notices else {}),
        # What the overseer keeps on the attention list by recording it again: leaving one out resolves it (§14).
        "attention": attention or [],
        # What changes every tick comes last, after what changes rarely, for a runtime that caches part of a message
        # (DESIGN §6).
        "capacity": {
            "max_workers": capacity.max_workers,
            "running": capacity.running,
            "available": capacity.available,
        },
        "running_workers": [
            {
                "run_id": r["id"],
                "ticket": r["ticket_key"],
                "repos": [s["repo"] for s in run_slots.get(int(r["id"]), [])],
                "kind": r["kind"],
                "branch": r["branch"],
                "started_at": r["started_at"],
            }
            for r in running
        ],
        # Tracker comments the overseer copies into the journal (DESIGN §22).
        "mirror": {"max_per_tick": conversation.MIRRORS_PER_TICK, "body_delimiter": mirror_delimiter},
        "tick_id": tick_id,
        "now": db.format_time(now),
        "dry_run": dry_run,
    }
    if dry_run:
        mode = (
            "This is a dry run. `canopy dispatch` checks its guards and records what it would have done, or the "
            "refusal, and starts nothing. `canopy ticket set` records phases but neither advances cursors nor marks "
            "tickets done. `canopy mirror` records comments but moves no mirror cursor. Decide exactly as you would "
            "otherwise."
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
            json.dumps(state, indent=2),
            "```",
            "",
        ]
    )


def _notice(held: Notice, now: datetime) -> NoticeState:
    return {"text": held.text, "set_at": held.set_at, "until": held.until, "in_force": held.in_force(now)}


def _stamp(moment: datetime | None) -> str | None:
    return db.format_time(moment) if moment is not None else None
