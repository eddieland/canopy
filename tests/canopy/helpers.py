"""Helpers shared by the dispatch, worker, and reconcile tests."""

import json
import os
import sqlite3
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from canopy.core import db
from canopy.infra import procs, resources
from tests.conftest import CanopyEnv

WORKER_DONE = json.dumps(
    {"status": "done", "branch": "agent/PROJ-1-work", "pr": "https://example.test/pr/1", "summary": "did it"}
)


def journal(env: CanopyEnv) -> sqlite3.Connection:
    conn = db.connect(env.state_dir / "canopy.db")
    db.migrate(conn, resources.migrations_dir())
    return conn


def in_tick(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, *, dry_run: bool = False) -> int:
    tick_id = db.start_tick(conn, dry_run=dry_run)
    monkeypatch.setenv("CANOPY_TICK_ID", str(tick_id))
    return tick_id


def slot_of(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row:
    """The one slot a run in one repository leased."""
    [row] = db.run_slots(conn, run_id)
    return row


def unit_of(conn: sqlite3.Connection, key: str) -> sqlite3.Row:
    """The one unit of a ticket in one repository."""
    [row] = db.units(conn, key)
    return row


def worker_does(monkeypatch: pytest.MonkeyPatch, *commands: list[str], result: str = WORKER_DONE) -> None:
    monkeypatch.setenv("FAKE_WORKER_COMMANDS", json.dumps(list(commands)))
    monkeypatch.setenv("FAKE_WORKER_RESULT", result)


def commit_and_push(branch: str, message: str = "PROJ-1: the change") -> list[list[str]]:
    return [
        ["git", "commit", "--quiet", "--allow-empty", "-m", message],
        ["git", "push", "--quiet", "origin", f"HEAD:refs/heads/{branch}"],
    ]


def pool(treehouse_state: Path) -> list[dict[str, object]]:
    slots: list[dict[str, object]] = json.loads(treehouse_state.read_text())["slots"]
    return slots


def wait_for_run(conn: sqlite3.Connection, run_id: int, timeout: float = 30) -> sqlite3.Row:
    """Wait for a detached run to close its row."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = db.get_run(conn, run_id)
        assert row is not None
        if row["status"] != "running":
            return row
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} still running after {timeout}s")


@dataclass
class InlineRunner:
    """Runs processes for real, but `spawn` starts nothing and returns this process's pid.

    A test then runs `canopy _run <id>` in-process with `main`, which claims the run with that same pid. `timeout_agent`
    makes the worker's run come back timed out, having printed `timeout_stdout`.
    """

    spawned: list[tuple[str, ...]] = field(default_factory=list)
    spawn_error: procs.ProcError | None = None
    timeout_agent: bool = False
    timeout_stdout: str = "fake agent: starting\n"

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        timeout: float | None = None,
        on_start: Callable[[int], None] | None = None,
    ) -> procs.Result:
        if self.timeout_agent and "agent" in args[:3]:
            return procs.Result(tuple(args), -9, self.timeout_stdout, "", timed_out=True)
        return procs.SubprocessRunner().run(args, cwd=cwd, env=env, stdin=stdin, timeout=timeout, on_start=on_start)

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:  # noqa: ARG002  (starts nothing)
        if self.spawn_error is not None:
            raise self.spawn_error
        self.spawned.append(tuple(args))
        return os.getpid()
