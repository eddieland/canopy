"""Each configured chore as the journal sees it: when it is due, its runs, and its open findings (DESIGN §19).

Only chores configured for this workspace exist here. A chore deleted from the config leaves its `chore_runs` rows as
history, and nothing about it reaches the overseer, the attention list, or notifications.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from canopy.chores import result
from canopy.core import db

if TYPE_CHECKING:
    from canopy.core.config import Chore, Config
    from canopy.core.workspace import Workspace

# Chore run statuses that raise `chore_failed`: the chore could not check, or left no usable result.
FAILED = frozenset({"failed", "unknown", "timeout", "crashed"})
FAILED_REASON = "chore_failed"
# How many of a chore's runs to read back when working out how long a finding has been open.
_HISTORY_RUNS = 200


def configured(config: Config, workspace: Workspace) -> dict[str, Chore]:
    """Return the chores this loop runs, by name: none when `capacity.max_chores` is 0 (DESIGN §19, D063).

    A chore that lists `workspaces` runs only in those, named as the workspace is (its map's name, or a workspace of
    one's repository name).
    """
    if config.capacity.max_chores == 0:
        return {}
    return {
        name: chore
        for name, chore in sorted(config.chores.items())
        if not chore.workspaces or workspace.name in chore.workspaces
    }


@dataclass(frozen=True)
class OpenFinding:
    """A finding of a chore's latest `ok` run, and when the unbroken sequence of `ok` runs reporting it started."""

    chore: str
    finding: result.Finding
    since: str


@dataclass(frozen=True)
class ChoreState:
    """One configured chore: its definition, its runs newest first, and what follows from them."""

    name: str
    chore: Chore
    runs: list[sqlite3.Row]

    @property
    def running(self) -> sqlite3.Row | None:
        """Its running run, if any."""
        return next((r for r in self.runs if r["status"] == "running"), None)

    @property
    def latest(self) -> sqlite3.Row | None:
        """Its most recent run, whatever its status."""
        return self.runs[0] if self.runs else None

    @property
    def latest_ended(self) -> sqlite3.Row | None:
        """Its most recent run that has ended."""
        return next((r for r in self.runs if r["status"] != "running"), None)

    def due_at(self) -> datetime | None:
        """The earliest time the `not_due` guard allows a new run: `every_minutes` after the latest start. None: now."""
        latest = self.latest
        if latest is None:
            return None
        return db.parse_time(str(latest["started_at"])) + timedelta(minutes=self.chore.every_minutes)

    def findings(self) -> list[OpenFinding]:
        """The findings of the latest `ok` run. A run that ended any other way leaves them standing."""
        oks = [(r, parsed) for r in self.runs if r["status"] == "ok" and (parsed := result.stored(r["result_json"]))]
        if not oks:
            return []
        found: list[OpenFinding] = []
        for finding in oks[0][1].findings:
            since = str(oks[0][0]["started_at"])
            for run, parsed in oks[1:]:
                if not any(f.id == finding.id for f in parsed.findings):
                    break
                since = str(run["started_at"])
            found.append(OpenFinding(self.name, finding, since))
        return found


def states(conn: sqlite3.Connection, config: Config, workspace: Workspace) -> list[ChoreState]:
    """Return every configured chore's state, by name."""
    return [
        ChoreState(name, chore, db.chore_runs(conn, name, _HISTORY_RUNS))
        for name, chore in configured(config, workspace).items()
    ]


def open_findings(conn: sqlite3.Connection, config: Config, workspace: Workspace) -> list[OpenFinding]:
    """Return every configured chore's open findings, by chore and then as the chore listed them."""
    return [f for state in states(conn, config, workspace) for f in state.findings()]


@dataclass(frozen=True)
class FailedItem:
    """A `chore_failed` attention item the harness raises for a chore whose latest run did not check."""

    chore: str
    detail: str


def failed_items(conn: sqlite3.Connection, config: Config, workspace: Workspace) -> list[FailedItem]:
    """Return a `chore_failed` item for each configured chore whose latest ended run did not end `ok` (D028)."""
    items: list[FailedItem] = []
    for state in states(conn, config, workspace):
        run = state.latest_ended
        if run is None or run["status"] not in FAILED:
            continue
        items.append(FailedItem(state.name, _detail(run)))
    return items


def _detail(run: sqlite3.Row) -> str:
    note = ""
    if run["result_json"]:
        try:
            stored: object = json.loads(str(run["result_json"]))
        except json.JSONDecodeError:
            stored = None
        if isinstance(stored, dict):
            harness: object = stored.get("harness")
            summary: object = stored.get("summary")
            note = str(harness or summary or "")
    text = f"chore run {run['id']} ended {run['status']}"
    if note:
        text += f": {note}"
    return f"{text}; log {run['log_path']}"[:2000]


def state_section(states_: list[ChoreState], now: datetime) -> list[dict[str, object]]:
    """Return the state block's `chores`: each configured chore, for the overseer to run or wait on (DESIGN §19)."""
    section: list[dict[str, object]] = []
    for state in states_:
        latest = state.latest
        latest_summary = None
        if latest is not None:
            stored = result.stored(latest["result_json"])
            harness = _harness(latest["result_json"])
            latest_summary = {
                "run_id": latest["id"],
                "status": latest["status"],
                "started_at": latest["started_at"],
                "ended_at": latest["ended_at"],
                "summary": harness or (stored.summary if stored is not None else None),
            }
        due = state.due_at()
        section.append(
            {
                "name": state.name,
                "every_minutes": state.chore.every_minutes,
                "when": state.chore.when or None,
                "due_at": db.format_time(due) if due is not None else None,
                "due": due is None or due <= now,
                "running": state.running is not None,
                "latest_run": latest_summary,
                "findings": [
                    {"id": f.finding.id, "title": f.finding.title, "link": f.finding.link} for f in state.findings()
                ],
            }
        )
    return section


def _harness(result_json: object) -> str | None:
    if not isinstance(result_json, str) or not result_json:
        return None
    try:
        stored: object = json.loads(result_json)
    except json.JSONDecodeError:
        return None
    if isinstance(stored, dict):
        harness: object = stored.get("harness")
        return str(harness) if harness else None
    return None
