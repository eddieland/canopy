"""Shared fixtures. The fakes in tests/fakes/ are real executables; these fixtures put them on PATH."""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import time
import tomllib
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

import pytest
from click.testing import CliRunner, Result

from canopy.core import db
from canopy.infra import resources, tracing
from canopy.infra.procs import SubprocessRunner

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator, Sequence

    import click

FAKES_DIR = Path(__file__).parent / "fakes"
# Where this interpreter's scripts live, `canopy` among them. A fake agent runs `canopy` the way an overseer does.
SCRIPTS_DIR = Path(sys.executable).parent
# The prefixes tests/fakes/agent records in its log's `env`. Keep in sync with it.
RECORDED_ENV_PREFIXES = ("CANOPY_", "OPENCODE_")
# What tests/fakes/agent reads its behavior from, for each role it plays. Keep in sync with it.
FAKE_AGENT_PREFIXES = tuple(f"FAKE_{role}_" for role in ("AGENT", "OVERSEER", "WORKER", "PLANNER", "CHORE", "REVIEWER"))

# Commits made under test have a fixed author, and git reads no config of the operator's or the machine's. Nor does it
# start automatic maintenance: newer git (2.55 on CI) runs it in the background after a commit or a fetch, where it
# can prune a worktree that `git worktree add` has made but not yet locked, or leave a `maintenance.lock` a test sees.
HERMETIC_GIT = {
    "GIT_AUTHOR_NAME": "canopy test",
    "GIT_COMMITTER_NAME": "canopy test",
    "GIT_AUTHOR_EMAIL": "test@example.test",
    "GIT_COMMITTER_EMAIL": "test@example.test",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "maintenance.auto",
    "GIT_CONFIG_VALUE_0": "false",
}


@pytest.fixture(autouse=True)
def hermetic_agent_env() -> Iterator[None]:
    """Drop inherited CANOPY_*, OPENCODE_*, and trace variables, so a test's environment is only what it sets.

    The whole environment is restored when the test ends.

    Workers run this suite inside the agent runtime, which exports its own (OpenCode sets OPENCODE_PID). The fake
    agent records these prefixes and tests assert on them exactly, so an inherited one would fail them.

    Local time is UTC, so what canopy counts by local day reads alike on every machine; a test of another zone sets
    `TZ` and calls `time.tzset()` itself.
    """
    try:
        with mock.patch.dict(os.environ, {"TZ": "UTC"}):
            time.tzset()
            for name in [k for k in os.environ if k.startswith(RECORDED_ENV_PREFIXES)]:
                del os.environ[name]
            # A trace whatever runs the suite may be in, which canopy would continue once tracing is on.
            for name in (tracing.TRACEPARENT, "TRACESTATE"):
                os.environ.pop(name, None)
            yield
    finally:
        time.tzset()


@pytest.fixture(autouse=True)
def tracing_off() -> Iterator[None]:
    """Turn tracing off when the test ends: a workspace configured to trace turns it on for the whole process."""
    yield
    tracing.configure(Path(), "off")


@pytest.fixture
def fakes_on_path() -> Iterator[Path]:
    """Put tests/fakes first on PATH, so `treehouse`, `agent`, and `opencode` resolve to the fakes.

    This environment's `canopy` comes right after it.
    """
    path = os.pathsep.join([str(FAKES_DIR), str(SCRIPTS_DIR), os.environ.get("PATH", "")])
    with mock.patch.dict(os.environ, {"PATH": path}):
        yield FAKES_DIR


@pytest.fixture
def treehouse_state(fakes_on_path: Path, tmp_path: Path) -> Iterator[Path]:
    """Fake treehouse on PATH with an empty pool. Yields its state file; write it to seed the pool, read it to assert.

    The file does not exist until the first `treehouse` call. See tests/fakes/treehouse for its keys.
    """
    state = tmp_path / "treehouse.json"
    with mock.patch.dict(os.environ, {"FAKE_TREEHOUSE_STATE": str(state)}):
        os.environ.pop("TREEHOUSE_LEASE_HOLDER", None)
        yield state


@pytest.fixture
def github_state(fakes_on_path: Path, tmp_path: Path) -> Iterator[Path]:
    """The fake GitHub programs on PATH, holding nothing until the test writes the yielded state file.

    `canopy-connect-github` reads it and `canopy-post-github` writes it; each appends what it was asked to
    `github.jsonl` beside it. See tests/fakes/github for its keys.
    """
    state = tmp_path / "github.json"
    with mock.patch.dict(
        os.environ,
        {"FAKE_GITHUB_STATE": str(state), "FAKE_GITHUB_LOG": str(tmp_path / "github.jsonl")},
    ):
        yield state


@pytest.fixture
def connector_state(fakes_on_path: Path, tmp_path: Path) -> Iterator[Path]:
    """The fake connector on PATH, configured by the yielded state file, which does not exist until the test writes it.

    Each run appends what it was asked to `connector.jsonl` beside it. See tests/fakes/connector for its keys.
    """
    state = tmp_path / "connector.json"
    with mock.patch.dict(
        os.environ,
        {"FAKE_CONNECTOR_STATE": str(state), "FAKE_CONNECTOR_LOG": str(tmp_path / "connector.jsonl")},
    ):
        yield state


@pytest.fixture
def opencode_state(fakes_on_path: Path, tmp_path: Path) -> Iterator[Path]:
    """The fake `opencode` on PATH, knowing no session until the test writes the yielded state file.

    Each run appends its argv, cwd, and OPENCODE_* variables' names to `opencode.jsonl` beside it. See
    tests/fakes/opencode for its keys.
    """
    # Not `opencode.json`, which OpenCode would read as config of a directory the workspace is in.
    state = tmp_path / "opencode-state.json"
    with mock.patch.dict(
        os.environ,
        {"FAKE_OPENCODE_STATE": str(state), "FAKE_OPENCODE_LOG": str(tmp_path / "opencode.jsonl")},
    ):
        yield state


@pytest.fixture
def agent_log(fakes_on_path: Path, tmp_path: Path) -> Iterator[Path]:
    """Fake agent on PATH with default behavior. Yields the file each run appends its argv and cwd to.

    Tests script it through the helpers in tests/canopy/helpers.py (`overseer_does`, `worker_does`, ...), which set its
    FAKE_<ROLE>_* variables for the length of a block; see tests/fakes/agent for what each one does.
    """
    log = tmp_path / "agent.jsonl"
    with mock.patch.dict(os.environ):
        for name in [k for k in os.environ if k.startswith(FAKE_AGENT_PREFIXES)]:
            del os.environ[name]
        os.environ["FAKE_AGENT_LOG"] = str(log)
        yield log


@dataclass
class Journals:
    """The journal connections a test opens, each closed when the test ends.

    A connection left to the garbage collector raises a ResourceWarning, which fails the test (pyproject.toml).
    """

    _opened: list[sqlite3.Connection] = field(default_factory=list)

    def open(self, path: Path, *, migrate: bool = True) -> sqlite3.Connection:
        """Open the journal at `path`, applying the shipped migrations unless `migrate` is False."""
        return self.open_through(path, resources.migrations_dir() if migrate else None)

    def open_through(self, path: Path, migrations: Path | None) -> sqlite3.Connection:
        """Open the journal at `path` and apply the migrations in `migrations`, if any."""
        conn = db.connect(path)
        self._opened.append(conn)
        if migrations is not None:
            db.migrate(conn, migrations)
        return conn

    def close(self) -> None:
        for conn in self._opened:
            conn.close()
        self._opened.clear()


@pytest.fixture
def journals() -> Iterator[Journals]:
    """Open journals through this, and they close when the test ends."""
    with closing(Journals()) as opened:
        yield opened


@dataclass(frozen=True)
class CanopyEnv:
    """A workspace of one repository, `repo`, and an operator, all in tmp_path. The process cwd is the workspace root.

    `repo` is the repository's primary clone, `repos/repo`: just a `.git` directory. `shared_file` is the workspace
    file, whose `[tracker]` table comes last so that a test can append tracker keys to it; the user file ends with an
    empty `[paths]` table, for paths keys.
    """

    root: Path
    repo: Path
    home: Path
    user_file: Path
    shared_file: Path
    journals: Journals

    @property
    def state_dir(self) -> Path:
        return self.root / ".canopy"

    def journal(self, *, migrate: bool = True) -> sqlite3.Connection:
        """Open this workspace's journal, closed when the test ends."""
        return self.journals.open(self.state_dir / db.DB_FILE_NAME, migrate=migrate)

    def write_user(self, text: str) -> None:
        self.user_file.parent.mkdir(parents=True, exist_ok=True)
        self.user_file.write_text(text)

    def write_shared(self, text: str) -> None:
        self.shared_file.write_text(text)

    def append_user(self, text: str) -> None:
        """Add `text` to the end of the user file, as a test adds a table or a key to the config it starts with."""
        self.write_user(self.user_file.read_text() + text)

    def append_shared(self, text: str) -> None:
        """Add `text` to the end of the workspace file, after its `[tracker]` table."""
        self.write_shared(self.shared_file.read_text() + text)

    @property
    def private_file(self) -> Path:
        """The workspace's private config file, which no test writes unless it calls `write_private`."""
        return self.state_dir / "config.toml"

    def write_private(self, text: str) -> None:
        self.private_file.write_text(text)

    def configure(self, file: Path, tables: Mapping[str, object]) -> list[str]:
        """Merge `tables` into `file`, one of this workspace's config files.

        A key `tables` sets takes the place of the one there, a key it sets to None is dropped, and a table it names
        keeps the keys it does not set.

        The file is written whole again, so what it held stays, but not its comments or its quoting.

        Returns:
            Each key set, dotted from its table, as `name = value` in TOML, and each dropped as `no name`.
        """
        merged = _merged(tomllib.loads(file.read_text()) if file.exists() else {}, tables)
        text = "\n".join(_toml_lines(merged))
        assert tomllib.loads(text) == merged, text
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)
        return _settings(tables)


#: A key TOML writes bare; any other it quotes.
_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")


def _merged(old: Mapping[str, object], new: Mapping[str, object]) -> dict[str, object]:
    merged = dict(old)
    for key, value in new.items():
        before = merged.get(key)
        if value is None:
            merged.pop(key, None)
        elif isinstance(value, Mapping):
            merged[key] = _merged(before if isinstance(before, dict) else {}, value)
        else:
            merged[key] = value
    return merged


def _toml_lines(table: Mapping[str, object], path: Sequence[str] = ()) -> list[str]:
    # A table's own keys under its header, then each table inside it, so that no key lands in the table above it.
    keys = [f"{_toml_key(k)} = {_toml_value(v)}" for k, v in table.items() if not isinstance(v, Mapping)]
    lines = [f"[{'.'.join(map(_toml_key, path))}]", *keys, ""] if path else [*keys, ""]
    for key, value in table.items():
        if isinstance(value, Mapping):
            lines += _toml_lines(value, [*path, key])
    return lines


def _settings(tables: Mapping[str, object], prefix: str = "") -> list[str]:
    settings: list[str] = []
    for key, value in tables.items():
        name = f"{prefix}{_toml_key(key)}"
        if value is None:
            settings.append(f"no {name}")
        elif isinstance(value, Mapping):
            settings += _settings(value, f"{name}.")
        else:
            settings.append(f"{name} = {_toml_value(value)}")
    return settings


def _toml_key(key: str) -> str:
    return key if _BARE_KEY.fullmatch(key) else json.dumps(key, ensure_ascii=False)


def _toml_value(value: object) -> str:
    # JSON's string escapes are TOML's too, and a list of these is an array; a table in one is an inline table.
    match value:
        case bool():
            return "true" if value else "false"
        case int() | float() | str():
            return json.dumps(value, ensure_ascii=False)
        case list():
            return f"[{', '.join(map(_toml_value, value))}]"
        case Mapping():
            return "{" + ", ".join(_settings(value)) + "}"
        case _:
            raise TypeError(f"no TOML for {value!r} in a test's config")


REPO_NAME = "repo"
SHARED_TOML = f"""\
[workspace]
name = "acme"

[repos.{REPO_NAME}]
url = "https://example.test/acme/{REPO_NAME}.git"
summary = "The only repository."

[tracker]
provider = "jira"
query = "project = PROJ"
"""


#: The name of the tests' `tracker` source, which config requires (DESIGN §30).
TRACKER_SOURCE = "jira"
#: Its command: the fake connector, holding every ticket it is asked open and labeled with the tests' queue label. A
#: test that scripts its tracker sets the source's `cmd` to `connector jira` and plays it.
TRACKER_CMD = f"connector {TRACKER_SOURCE} --labeled agent-ready-tester"
#: Its table in the user file.
TRACKER_TOML = f'[connect.sources.{TRACKER_SOURCE}]\nkind = "tracker"\ncmd = "{TRACKER_CMD}"\n'


def user_toml() -> str:
    return f"""\
[tracker]
labels = ["agent-ready-tester"]

[runtime]
overseer_cmd = 'env OPENCODE_CONFIG_DIR={{definitions_dir}} agent run --agent canopy-overseer {{prompt}}'
worker_cmd = 'env OPENCODE_CONFIG_DIR={{definitions_dir}} agent run --agent canopy-worker {{prompt}}'
private_worker_cmd = 'env OPENCODE_CONFIG_DIR={{definitions_dir}} agent run --agent canopy-worker-private {{prompt}}'
plan_cmd = 'env OPENCODE_CONFIG_DIR={{definitions_dir}} agent run --agent canopy-planner --format json {{prompt}}'

{TRACKER_TOML}
[paths]
"""


@pytest.fixture
def canopy_env(tmp_path: Path, journals: Journals) -> Iterator[CanopyEnv]:
    """A workspace of one repository with its workspace file, and a user config that runs the fake agent.

    The user config's runtime commands run the fake agent. HOME, XDG_CONFIG_HOME, and XDG_DATA_HOME point into tmp_path
    too, so nothing reads or writes the real operator's files. CANOPY_TICK_ID is cleared.
    """
    home = tmp_path / "home"
    root = tmp_path / "ws"
    repo = root / "repos" / REPO_NAME
    (repo / ".git").mkdir(parents=True)
    home.mkdir()
    env = CanopyEnv(
        root=root,
        repo=repo,
        home=home,
        user_file=home / ".config" / "canopy" / "config.toml",
        shared_file=root / "canopy-workspace.toml",
        journals=journals,
    )
    env.write_shared(SHARED_TOML)
    env.write_user(user_toml())
    # As canopy creates it, so a journal a test opens first is in a directory canopy accepts as the operator's own.
    env.state_dir.mkdir(mode=0o700)
    variables = {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "USER": "tester",
    }
    with mock.patch.dict(os.environ, variables), contextlib.chdir(root):
        os.environ.pop("CANOPY_TICK_ID", None)
        yield env


def pool_state(repo: Path, slots: Sequence[Mapping[str, object]], max_trees: int | None = None) -> str:
    """The fake treehouse's state with `slots` as the pool of the repository whose primary clone is `repo`."""
    pool: dict[str, object] = {"slots": list(slots)}
    if max_trees is not None:
        pool["max_trees"] = max_trees
    return json.dumps({"pools": {str(repo): pool}})


def git(*args: str, cwd: Path) -> str:
    """Run git through the procs boundary (D015) and return its stripped stdout; fail the test if it fails."""
    result = SubprocessRunner().run(["git", *args], cwd=cwd)
    assert result.ok, f"git {' '.join(args)}: {result.stderr}"
    return result.stdout.strip()


def executable(path: Path, text: str) -> Path:
    """Write `text` to `path` as a script anyone may run, and return `path`."""
    path.write_text(text)
    path.chmod(0o755)
    return path


def invoke(command: click.Command, args: Sequence[str] = (), *, stdin: str = "", obj: object = None) -> Result:
    """Run one of the programs canopy ships as its console script would, with `args` and `stdin`.

    `obj` stands in for what the program would reach outside the process, such as a server's address. An exception
    the program does not handle fails the test, rather than becoming the result's.

    Returns:
        What it printed, on stdout and on stderr apart, and its exit code.
    """
    return CliRunner().invoke(command, list(args), input=stdin, obj=obj, catch_exceptions=False)


@dataclass(frozen=True)
class GitPool:
    """A bare `origin` with one commit on `main`, and treehouse slots that are clones of it."""

    origin: Path
    slots: tuple[Path, ...]

    def remote_head(self, branch: str) -> str | None:
        """The commit `branch` points to on origin, or None."""
        out = git("for-each-ref", "--format=%(objectname)", f"refs/heads/{branch}", cwd=self.origin)
        return out or None

    def reject_pushes(self) -> None:
        """Make origin refuse every push, the way a protected branch or a lost network does."""
        hook = self.origin / "hooks" / "pre-receive"
        executable(hook, "#!/bin/sh\necho 'push refused by test hook' >&2\nexit 1\n")


@pytest.fixture
def git_pool(canopy_env: CanopyEnv, treehouse_state: Path, tmp_path: Path) -> Iterator[GitPool]:
    """Real git behind the fake treehouse: `treehouse get` leases one of two clones of a bare origin, as `repo`'s pool.

    Real treehouse slots are worktrees of one repository; clones behave the same for what canopy runs in a slot.
    """
    with mock.patch.dict(os.environ, HERMETIC_GIT):
        yield seed_git_pool(canopy_env, treehouse_state, tmp_path)


@pytest.fixture
def worktree_pool(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    tmp_path: Path,
) -> tuple[Path, list[Path]]:
    """The primary clone and two worktree slots of it, which the fake treehouse leases instead of `git_pool`'s."""
    primary = tmp_path / "primary"
    git("clone", "--quiet", str(git_pool.origin), str(primary), cwd=tmp_path)
    slots = [tmp_path / "wpool" / name / "repo" for name in ("1", "2")]
    for slot in slots:
        git("worktree", "add", "--quiet", "--detach", str(slot), cwd=primary)
    state = [{"name": str(i), "path": str(p), "status": "available"} for i, p in enumerate(slots, 1)]
    treehouse_state.write_text(pool_state(canopy_env.repo, state, max_trees=len(slots)))
    return primary, slots


def seed_git_pool(canopy_env: CanopyEnv, treehouse_state: Path, tmp_path: Path) -> GitPool:
    origin = tmp_path / "origin.git"
    origin.mkdir()
    git("init", "--quiet", "--bare", "--initial-branch=main", cwd=origin)
    seed = tmp_path / "seed"
    seed.mkdir()
    git("init", "--quiet", "--initial-branch=main", cwd=seed)
    git("commit", "--quiet", "--allow-empty", "-m", "initial", cwd=seed)
    git("push", "--quiet", str(origin), "main", cwd=seed)

    slots: list[Path] = []
    for name in ("1", "2"):
        slot = tmp_path / "pool" / name / "repo"
        slot.parent.mkdir(parents=True)
        git("clone", "--quiet", str(origin), str(slot), cwd=tmp_path)
        git("checkout", "--quiet", "--detach", cwd=slot)
        slots.append(slot)
    pool = [{"name": str(i), "path": str(p), "status": "available"} for i, p in enumerate(slots, 1)]
    treehouse_state.write_text(pool_state(canopy_env.repo, pool, max_trees=len(slots)))
    return GitPool(origin, tuple(slots))
