"""Helpers shared by the dispatch, worker, and reconcile tests."""

import json
import os
import sqlite3
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from unittest import mock

from canopy.core import db
from canopy.infra import procs, resources
from tests.conftest import CanopyEnv, Journals

WORKER_DONE = json.dumps(
    {"status": "done", "branch": "agent/PROJ-1-work", "pr": "https://example.test/pr/1", "summary": "did it"}
)


def journal(env: CanopyEnv) -> sqlite3.Connection:
    return env.journal()


def shipped_through(dest: Path, version: int) -> Path:
    """Copy the shipped migrations through `version` into `dest`, the directory an older canopy shipped."""
    dest.mkdir(parents=True, exist_ok=True)
    for m in db.discover(resources.migrations_dir())[:version]:
        (dest / m.path.name).write_text(m.path.read_text())
    return dest


def journal_at(journals: Journals, tmp_path: Path, version: int) -> sqlite3.Connection:
    """A journal migrated through `version`, as an older canopy left it, for a test of what later migrations do."""
    return journals.open_through(tmp_path / "canopy.db", shipped_through(tmp_path / "migrations", version))


def versions_after(version: int) -> list[int]:
    """The shipped migrations after `version`: what upgrading a journal at `version` applies."""
    return [m.version for m in db.discover(resources.migrations_dir()) if m.version > version]


@contextmanager
def in_tick(conn: sqlite3.Connection, *, dry_run: bool = False) -> Iterator[int]:
    """Start a tick and act inside it, as the overseer does: CANOPY_TICK_ID names it until the block ends."""
    tick_id = db.start_tick(conn, dry_run=dry_run)
    with mock.patch.dict(os.environ, {"CANOPY_TICK_ID": str(tick_id)}):
        yield tick_id


def slot_of(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row:
    """The one slot a run in one repository leased."""
    [row] = db.run_slots(conn, run_id)
    return row


def unit_of(conn: sqlite3.Connection, key: str) -> sqlite3.Row:
    """The one unit of a ticket in one repository."""
    [row] = db.units(conn, key)
    return row


@contextmanager
def worker_does(*commands: list[str], result: str = WORKER_DONE) -> Iterator[None]:
    """Until the block ends, the fake worker runs `commands` and then prints `result`."""
    with mock.patch.dict(
        os.environ, {"FAKE_WORKER_COMMANDS": json.dumps(list(commands)), "FAKE_WORKER_RESULT": result}
    ):
        yield


def commit_and_push(branch: str, message: str = "PROJ-1: the change") -> list[list[str]]:
    return [
        ["git", "commit", "--quiet", "--allow-empty", "-m", message],
        ["git", "push", "--quiet", "origin", f"HEAD:refs/heads/{branch}"],
    ]


def pool(treehouse_state: Path) -> list[dict[str, object]]:
    """Every slot the fake treehouse holds: the pool it uses without TREEHOUSE_ROOT, then each repository's."""
    state = json.loads(treehouse_state.read_text())
    slots: list[dict[str, object]] = [
        *state.get("slots", []),
        *(s for p in state.get("pools", {}).values() for s in p.get("slots", [])),
    ]
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


def lifelock_left(row: sqlite3.Row, timeout: float = 30) -> bool:
    """Whether the lifelock file of a closed run is still there once its process has exited.

    The process closes its row, then removes the file, then exits, so the file is looked for only after the exit.
    """
    deadline = time.monotonic() + timeout
    while procs.alive(int(row["pid"])) and time.monotonic() < deadline:
        time.sleep(0.05)
    return procs.lifelock(Path(row["log_path"])).exists()


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
        on_line: Callable[[str], None] | None = None,
    ) -> procs.Result:
        if self.timeout_agent and "agent" in args[:3]:
            return procs.Result(tuple(args), -9, self.timeout_stdout, "", timed_out=True)
        return procs.SubprocessRunner().run(
            args, cwd=cwd, env=env, stdin=stdin, timeout=timeout, on_start=on_start, on_line=on_line
        )

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:  # noqa: ARG002  (starts nothing)
        if self.spawn_error is not None:
            raise self.spawn_error
        self.spawned.append(tuple(args))
        return os.getpid()
