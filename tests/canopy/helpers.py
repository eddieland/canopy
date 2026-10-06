"""Helpers shared by the dispatch, worker, and reconcile tests."""

import json
import os
import sqlite3
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from canopy.core import config, db
from canopy.infra import procs, resources
from tests.conftest import CanopyEnv, git

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
    makes the worker's run come back timed out.
    """

    spawned: list[tuple[str, ...]] = field(default_factory=list)
    spawn_error: procs.ProcError | None = None
    timeout_agent: bool = False

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
            return procs.Result(tuple(args), -9, "fake agent: starting\n", "", timed_out=True)
        return procs.SubprocessRunner().run(args, cwd=cwd, env=env, stdin=stdin, timeout=timeout, on_start=on_start)

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:  # noqa: ARG002  (starts nothing)
        if self.spawn_error is not None:
            raise self.spawn_error
        self.spawned.append(tuple(args))
        return os.getpid()


def map_text(*repos: tuple[str, str], extra: str = "") -> str:
    tables = "".join(f'\n[repos.{name}]\nurl = "{url}"\nsummary = "The {name} repository."\n' for name, url in repos)
    return f"""\
[workspace]
name = "acme"
{tables}
[tracker]
provider = "github"
query = "is:issue is:open"
{extra}"""


@dataclass(frozen=True)
class Ws:
    """A workspace of two repositories, `api` and `web`, each cloned from a bare origin under tmp_path."""

    root: Path
    origins: dict[str, Path]
    state_dir: Path

    def journal(self) -> sqlite3.Connection:
        self.state_dir.mkdir(mode=0o700, exist_ok=True)  # as canopy creates it; anything wider is refused
        conn = db.connect(self.state_dir / "canopy.db")
        db.migrate(conn, resources.migrations_dir())
        return conn

    def clone(self, name: str) -> Path:
        return self.root / "repos" / name

    def remote_head(self, name: str, branch: str) -> str | None:
        out = git("for-each-ref", "--format=%(objectname)", f"refs/heads/{branch}", cwd=self.origins[name])
        return out or None


def bare_origin(path: Path, tmp_path: Path) -> Path:
    path.mkdir(parents=True)
    git("init", "--quiet", "--bare", "--initial-branch=main", cwd=path)
    seed = tmp_path / f"seed-{path.stem}"
    seed.mkdir()
    git("init", "--quiet", "--initial-branch=main", cwd=seed)
    git("commit", "--quiet", "--allow-empty", "-m", f"initial {path.stem}", cwd=seed)
    git("push", "--quiet", str(path), "main", cwd=seed)
    return path


def make_ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Ws:
    """Make the workspace `Ws` describes and run from its root. `canopy_env` supplies the user file."""
    for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(var, "canopy test")
    for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(var, "test@example.test")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")

    root = tmp_path / "acme"
    root.mkdir()
    origins = {name: bare_origin(tmp_path / "origins" / f"{name}.git", tmp_path) for name in ("api", "web")}
    for name, origin in origins.items():
        git("clone", "--quiet", str(origin), str(root / "repos" / name), cwd=tmp_path)
    (root / config.WORKSPACE_FILE_NAME).write_text(map_text(*((n, str(o)) for n, o in origins.items())))
    monkeypatch.chdir(root)
    return Ws(root, origins, root / ".canopy")
