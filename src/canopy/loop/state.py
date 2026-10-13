"""The overseer's state block: the `## State` section the harness appends to its prompt (DESIGN §6 step 4)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import conversation, db
from canopy.runs import policy

if TYPE_CHECKING:
    from canopy.core import treehouse
    from canopy.core.config import Config
    from canopy.core.workspace import Workspace
    from canopy.runs.reconcile import Capacity


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
    units: Mapping[str, list[sqlite3.Row]],
    last_runs: Mapping[str, sqlite3.Row],
    run_slots: Mapping[int, list[sqlite3.Row]],
    attempts: Mapping[policy.Unit, Mapping[str, int]],
    fix_ci_cooldowns: Mapping[policy.Unit, datetime],
    now: datetime,
    split_attempts: Mapping[str, int],
    split_children: list[sqlite3.Row],
    chores: list[dict[str, object]],
    reviews: dict[str, object] | None,
    private: Mapping[str, dict[str, object]] | None = None,
    operator: Mapping[str, dict[str, object]] | None = None,
    mirror_delimiter: str,
) -> str:
    """Render the `## State` section the harness appends to the overseer prompt.

    `units` are each ticket's units and `run_slots` each running or latest run's slots, by run id. `attempts` and
    `fix_ci_cooldowns` are per unit (`policy.unit`). `split_attempts` are per ticket, and `split_children` are the
    children of splits not yet done, with their split run's end (DESIGN §18). `chores` are the configured chores
    (DESIGN §19); with none, the block has no `chores` key, exactly as before chores existed. `private` holds each
    private ticket's conversation state, by key (DESIGN §22); a public ticket has no `private` key. `operator` holds a
    public ticket's operator messages newer than its message cursor, by key; a ticket without any has no `operator`
    key (DESIGN §7, D089). `mirror_delimiter` ends the heredoc the overseer passes each mirrored comment's body in: the
    tick's own, so no comment can predict it.
    """
    private = private or {}
    operator = operator or {}
    no_attempts = dict.fromkeys(policy.KINDS, 0)

    def unit_summary(key: str, u: sqlite3.Row) -> dict[str, object]:
        name = str(u["repo"])
        unit = policy.unit(key, name)
        return {
            "repo": name,
            "branch": u["branch"],
            "pr_url": u["pr_url"],
            "phase": u["phase"],
            "cursors": {cursor: u[column] for cursor, column in db.UNIT_CURSORS.items()},
            "attempts": dict(attempts.get(unit, no_attempts)),
            "fix_ci_cooldown_until": _stamp(fix_ci_cooldowns.get(unit)),
        }

    def run_summary(run: sqlite3.Row | None) -> dict[str, object] | None:
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

    def ticket_summary(t: sqlite3.Row) -> dict[str, object]:
        key = str(t["key"])
        summary: dict[str, object] = {
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
        summary.update(
            {name: found[key] for name, found in (("private", private), ("operator", operator)) if key in found}
        )
        return summary

    state: dict[str, object] = {
        "tick_id": tick_id,
        "now": db.format_time(now),
        "dry_run": dry_run,
        "repository": str(repo_root),
        # The overseer runs at the workspace root, which is not a repository: each repository's leased slots stand in
        # for its own `treehouse status` (DESIGN §18).
        "workspace": {
            "name": workspace.name,
            "map": str(workspace.map_prose) if workspace.map_prose is not None else None,
        },
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
        "capacity": {
            "max_workers": capacity.max_workers,
            "running": capacity.running,
            "available": capacity.available,
        },
        "policy": {
            "max_implement_attempts": config.policy.max_implement_attempts,
            "max_fix_ci_attempts": config.policy.max_fix_ci_attempts,
            "fix_ci_cooldown_minutes": config.policy.fix_ci_cooldown_minutes,
            "max_resume_attempts": config.policy.max_resume_attempts,
            "max_split_attempts": config.policy.max_split_attempts,
            "stacking": config.policy.stacking,
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
        "tickets": [ticket_summary(t) for t in tickets],
        # Tracker comments the overseer copies into the journal (DESIGN §22).
        "mirror": {"max_per_tick": conversation.MIRRORS_PER_TICK, "body_delimiter": mirror_delimiter},
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
    }
    if chores:
        state["chores"] = chores
    # With reviews off, nothing about them reaches the overseer (DESIGN §21).
    if reviews is not None:
        state["reviews"] = reviews
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


def _stamp(moment: datetime | None) -> str | None:
    return db.format_time(moment) if moment is not None else None
