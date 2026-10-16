"""Each configured chore as the journal sees it: when it is due, its runs, and its open findings (DESIGN §19).

Only chores configured for this workspace exist here. A chore deleted from the config leaves its `chore_runs` rows as
history, and nothing about it reaches the overseer, the attention list, or notifications.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, TypedDict

from canopy.core import chore_result as result
from canopy.core import chore_window as window
from canopy.core import db
from canopy.core.vocab import ChoreRunStatus

if TYPE_CHECKING:
    from canopy.core.config import Chore, Config
    from canopy.core.workspace import Workspace

# Chore run statuses that raise `chore_failed`: the chore could not check, or left no usable result.
FAILED = frozenset({ChoreRunStatus.FAILED, ChoreRunStatus.UNKNOWN, ChoreRunStatus.TIMEOUT, ChoreRunStatus.CRASHED})
FAILED_REASON = "chore_failed"
# How many of a chore's runs to read back at a time. A finding open longer than that reads further back.
_HISTORY_RUNS = 200


def configured(config: Config, workspace: Workspace) -> dict[str, Chore]:
    """Return the chores this loop runs, by name: none when `capacity.max_chores` is 0 (DESIGN §19)."""
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
    """A finding of a chore's latest `ok` run, and when the unbroken sequence of `ok` runs reporting it started.

    `dismissed` is whether the operator dismissed it since then, which keeps it off the attention list until it clears.
    """

    chore: str
    finding: result.Finding
    since: str
    dismissed: bool = False


@dataclass(frozen=True)
class ChoreState:
    """One configured chore: its definition, its newest runs first, and what follows from them.

    `older` returns the page of runs before a run id, newest first, for a finding open longer than `runs` reaches.
    `dismissals` is when the operator last dismissed each finding id it dismissed. `starts`, when given, remembers
    when its findings started from one read to the next.
    """

    name: str
    chore: Chore
    runs: list[sqlite3.Row]
    older: Callable[[int], list[sqlite3.Row]]
    dismissals: Mapping[str, str]
    starts: FindingStarts | None = None

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
        """The earliest time the `not_due` guard allows a new run: `every_minutes` after the latest start. None: now.

        Returns:
            The latest run's start plus `every_minutes`, or None when the chore has never run.
        """
        latest = self.latest
        if latest is None:
            return None
        return db.parse_time(str(latest["started_at"])) + timedelta(minutes=self.chore.every_minutes)

    def due_at(self, now: datetime) -> datetime | None:
        """The earliest time every guard on time allows a new run: `earliest`, moved to when its window next opens.

        None, or a time not after `now`, means it may run now.

        Returns:
            `earliest` when the chore has no window, or its window is open at the later of `earliest` and `now`;
            else when the window next opens after that.
        """
        earliest = self.earliest()
        if not window.limited(self.chore):
            return earliest
        after = now if earliest is None or earliest < now else earliest
        opens = window.next_open(self.chore, after)
        return earliest if opens <= after else opens

    def findings(self) -> list[OpenFinding]:
        """The findings of the latest `ok` run. A run that ended any other way leaves them standing.

        A finding is dismissed when the operator dismissed it after that sequence started: one that clears and comes
        back starts a new sequence, which an earlier dismissal does not cover.

        Returns:
            Each finding, with when the unbroken sequence of `ok` runs reporting it started, and whether it is
            dismissed; none before an `ok` run.
        """
        latest = next(
            ((r, parsed) for r in self.runs if r["status"] == "ok" and (parsed := result.stored(r["result_json"]))),
            None,
        )
        if latest is None:
            return []
        run, parsed = latest
        since = self._since(run, parsed)
        found: list[OpenFinding] = []
        for f in parsed.findings:
            at = self.dismissals.get(f.id)
            dismissed = at is not None and db.parse_time(at) >= db.parse_time(since[f.id])
            found.append(OpenFinding(self.name, f, since[f.id], dismissed=dismissed))
        return found

    def _since(self, latest: sqlite3.Row, parsed: result.ChoreResult) -> dict[str, str]:
        """When the unbroken sequence of `ok` runs reporting each of the latest `ok` run's findings started.

        One walk back serves every finding, and stops once each one's sequence has, or at the run `starts` remembers
        from an earlier read: a chore's findings are read on every journal commit the web UI's event stream sees
        (DESIGN §22), and a finding open for a year would otherwise read a year of runs each time.

        Returns:
            Each finding's id, and the start time, in the journal's format, of the oldest `ok` run in its sequence.
        """
        start = str(latest["started_at"])
        since = {f.id: start for f in parsed.findings}
        open_ids = set(since)
        known = self.starts.of(self.name) if self.starts is not None else None
        if known is not None and known.run == int(latest["id"]):
            return dict(known.since)
        if open_ids:
            for run in self._older_oks(int(latest["id"])):
                if known is not None and int(run["id"]) == known.run:
                    # That run reported exactly what `known` holds: a finding it did not report ended its sequence.
                    since.update((i, known.since[i]) for i in open_ids if i in known.since)
                    break
                found = result.stored(run["result_json"])
                if found is None:
                    continue
                open_ids &= {f.id for f in found.findings}
                if not open_ids:
                    break
                for finding_id in open_ids:
                    since[finding_id] = str(run["started_at"])
        if self.starts is not None:
            self.starts.keep(self.name, Started(int(latest["id"]), since))
        return since

    def _older_oks(self, before: int) -> Iterator[sqlite3.Row]:
        """Its `ok` runs before run id `before`, newest first, reading back page by page.

        Yields:
            Each run with status `ok`, its result not yet read.
        """
        page = self.runs
        while True:
            yield from (r for r in page if r["status"] == "ok" and int(r["id"]) < before)
            if len(page) < _HISTORY_RUNS:
                return
            page = self.older(int(page[-1]["id"]))


@dataclass(frozen=True)
class Started:
    """A chore's latest `ok` run, and when the unbroken sequence of `ok` runs reporting each of its findings started."""

    run: int
    since: Mapping[str, str]


class FindingStarts:
    """When each chore's open findings started, as a read last found them, so a later one reads back only to there.

    An ended run's result never changes and no run is deleted, so what holds at a run holds for as long as the journal
    does: a read that walks back to the run remembered takes its starts and reads no further. The web UI's server keeps
    one for its journal and hands it to every Context it opens (DESIGN §22), from threads of its own, so it locks.
    """

    def __init__(self) -> None:
        """Remember nothing yet."""
        self._lock = threading.Lock()
        self._started: dict[str, Started] = {}

    def of(self, chore: str) -> Started | None:
        """What a read last found for `chore`, or None.

        Returns:
            Its latest `ok` run then, with each of its findings' starts.
        """
        with self._lock:
            return self._started.get(chore)

    def keep(self, chore: str, started: Started) -> None:
        """Remember what a read found for `chore`, in place of what it found before."""
        with self._lock:
            self._started[chore] = started


def states(
    conn: sqlite3.Connection, config: Config, workspace: Workspace, *, starts: FindingStarts | None = None
) -> list[ChoreState]:
    """Return every configured chore's state, by name, remembering its findings' starts in `starts` if given."""
    return [state_of(conn, name, chore, starts=starts) for name, chore in configured(config, workspace).items()]


def state_of(conn: sqlite3.Connection, name: str, chore: Chore, *, starts: FindingStarts | None = None) -> ChoreState:
    """Return chore `name`'s state as the journal sees it, remembering its findings' starts in `starts` if given."""

    def older(before: int) -> list[sqlite3.Row]:
        return db.chore_runs(conn, name, _HISTORY_RUNS, before=before)

    runs = db.chore_runs(conn, name, _HISTORY_RUNS)
    return ChoreState(name, chore, runs, older, db.dismissals(conn, name), starts)


def open_findings(
    conn: sqlite3.Connection, config: Config, workspace: Workspace, *, starts: FindingStarts | None = None
) -> list[OpenFinding]:
    """Return every configured chore's open findings, by chore and then as the chore listed them, dismissed or not.

    `starts`, when given, remembers when they started from one call to the next.
    """
    return [f for state in states(conn, config, workspace, starts=starts) for f in state.findings()]


@dataclass(frozen=True)
class FailedItem:
    """A `chore_failed` attention item the harness raises for a chore whose latest run did not check."""

    chore: str
    detail: str


def failed_items(conn: sqlite3.Connection, config: Config, workspace: Workspace) -> list[FailedItem]:
    """Return a `chore_failed` item for each configured chore whose latest ended run did not end `ok`."""
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


class LatestRun(TypedDict):
    """A chore's latest run, as the state block's `chores` carries it."""

    run_id: int
    status: str
    started_at: str
    ended_at: str | None
    # The harness's note on the run, or else the chore's own summary.
    summary: str | None


class FindingRef(TypedDict):
    """An open finding, named by its id and title, with its link if it has one."""

    id: str
    title: str
    link: str | None


class ChoreSummary(TypedDict):
    """One configured chore in the state block's `chores` (DESIGN §19)."""

    name: str
    every_minutes: int
    when: str | None
    due_at: str | None
    due: bool
    running: bool
    latest_run: LatestRun | None
    findings: list[FindingRef]


def state_section(states_: list[ChoreState], now: datetime) -> list[ChoreSummary]:
    """Return the state block's `chores`: each configured chore, for the overseer to run or wait on (DESIGN §19)."""
    section: list[ChoreSummary] = []
    for state in states_:
        latest = state.latest
        latest_summary: LatestRun | None = None
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
