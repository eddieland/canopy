"""Each configured chore as the journal sees it: when it is due, its runs, and its open findings (DESIGN §19).

Only chores configured for this workspace exist here. A chore deleted from the config leaves its `chore_runs` rows as
history, and nothing about it reaches the overseer, the attention list, or notifications.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from canopy.core import chore_result as result
from canopy.core import chore_window as window
from canopy.core import db

if TYPE_CHECKING:
    from canopy.core.config import Chore, Config
    from canopy.core.workspace import Workspace

# Chore run statuses that raise `chore_failed`: the chore could not check, or left no usable result.
FAILED = frozenset({"failed", "unknown", "timeout", "crashed"})
FAILED_REASON = "chore_failed"
# How many of a chore's runs to read back at a time. A finding open longer than that reads further back.
_HISTORY_RUNS = 200


def configured(config: Config, workspace: Workspace) -> dict[str, Chore]:
    """Return the chores this loop runs, by name: none when `capacity.max_chores` is 0 (DESIGN §19, D063)."""
    if config.capacity.max_chores == 0:
        return {}
    return defined(config, workspace)


def defined(config: Config, workspace: Workspace) -> dict[str, Chore]:
    """Return the chores the user config defines for this workspace, by name, even when `max_chores` is 0.

    A chore that lists `workspaces` runs only in those, named as the workspace is (its map's name, or a workspace of
    one's repository name).
    """
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
    """One configured chore: its definition, its newest runs first, and what follows from them.

    `older` returns the page of runs before a run id, newest first, for a finding open longer than `runs` reaches.
    """

    name: str
    chore: Chore
    runs: list[sqlite3.Row]
    older: Callable[[int], list[sqlite3.Row]]

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

    def earliest(self) -> datetime | None:
        """The earliest time the `not_due` guard allows a new run: `every_minutes` after the latest start. None: now."""
        latest = self.latest
        if latest is None:
            return None
        return db.parse_time(str(latest["started_at"])) + timedelta(minutes=self.chore.every_minutes)

    def due_at(self, now: datetime) -> datetime | None:
        """The earliest time every guard on time allows a new run: `earliest`, moved to when its window next opens.

        None, or a time not after `now`, means it may run now.
        """
        earliest = self.earliest()
        if not window.limited(self.chore):
            return earliest
        after = now if earliest is None or earliest < now else earliest
        opens = window.next_open(self.chore, after)
        return earliest if opens <= after else opens

    def findings(self) -> list[OpenFinding]:
        """The findings of the latest `ok` run. A run that ended any other way leaves them standing."""
        oks = _oks(self.runs)
        if not oks:
            return []
        return [OpenFinding(self.name, f, self._since(f.id, oks)) for f in oks[0][1].findings]

    def _since(self, finding_id: str, oks: list[tuple[sqlite3.Row, result.ChoreResult]]) -> str:
        """When the unbroken sequence of `ok` runs reporting `finding_id` started, reading back page by page."""
        since = str(oks[0][0]["started_at"])
        page, rest = self.runs, oks[1:]
        while True:
            for run, parsed in rest:
                if not any(f.id == finding_id for f in parsed.findings):
                    return since
                since = str(run["started_at"])
            if len(page) < _HISTORY_RUNS:
                return since
            page = self.older(int(page[-1]["id"]))
            rest = _oks(page)


def _oks(runs: list[sqlite3.Row]) -> list[tuple[sqlite3.Row, result.ChoreResult]]:
    return [(r, parsed) for r in runs if r["status"] == "ok" and (parsed := result.stored(r["result_json"]))]


def states(conn: sqlite3.Connection, config: Config, workspace: Workspace) -> list[ChoreState]:
    """Return every configured chore's state, by name."""
    return [state_of(conn, name, chore) for name, chore in configured(config, workspace).items()]


def state_of(conn: sqlite3.Connection, name: str, chore: Chore) -> ChoreState:
    """Return chore `name`'s state as the journal sees it."""

    def older(before: int) -> list[sqlite3.Row]:
        return db.chore_runs(conn, name, _HISTORY_RUNS, before=before)

    return ChoreState(name, chore, db.chore_runs(conn, name, _HISTORY_RUNS), older)


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
        due = state.due_at(now)
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
