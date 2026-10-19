"""Fixtures for the tests of canopy: the workspace's journal and context, scenarios played in it, the web UI's mock
backend, notification commands that record what they are sent, Markdown snapshots, workspaces of several repositories
(DESIGN §18)."""

import contextlib
import json
import os
import sqlite3
from collections.abc import Generator, Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from unittest import mock

import pytest
from syrupy.assertion import SnapshotAssertion
from syrupy.extensions.single_file import SingleFileSnapshotExtension, WriteMode

from canopy.core import config, db
from canopy.core.context import Context
from canopy.infra import resources
from canopy.serve import mock as serve_mock
from canopy.serve.backend import Backend
from tests.canopy.helpers import context, titled_workers
from tests.canopy.scenario_helpers import Scenario
from tests.conftest import HERMETIC_GIT, CanopyEnv, Journals, executable, git


@pytest.fixture
def conn(canopy_env: CanopyEnv) -> sqlite3.Connection:
    """The workspace's journal, migrated."""
    return canopy_env.journal()


@pytest.fixture
def ctx(canopy_env: CanopyEnv) -> Context:
    """The context `canopy` builds in the workspace, over its journal, migrated."""
    found = context(canopy_env)
    db.migrate(found.conn, resources.migrations_dir())
    return found


@pytest.fixture
def scenario(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, conn: sqlite3.Connection, tmp_path: Path
) -> Iterator[Scenario]:
    """The workspace, with the fake treehouse and agents on PATH, where a test tells a ticket's story
    (`scenario_helpers.py`). A test whose workers push asks for `git_pool` too. Its workers are titled, as the default
    templates title them, so each knows the ticket it runs for.

    Yields:
        The scenario, whose runs still held at work are stopped once the test ends.
    """
    titled_workers(canopy_env)
    told = Scenario(canopy_env, conn, agent_log, tmp_path / "gates")
    try:
        yield told
    finally:
        told.close()


@pytest.fixture
def ws_scenario(
    ws: "Ws", canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, tmp_path: Path
) -> Iterator[Scenario]:
    """The scenario told in `ws`, the workspace of two repositories, `api` and `web`, each pool a slot of its own
    (`seed_pools`), for a story of a joint run, a split, or a ticket in each repository. The test names the
    repositories each dispatch works in.

    Yields:
        The scenario, whose runs still held at work are stopped once the test ends.
    """
    seed_pools(ws, treehouse_state)
    env = replace(canopy_env, root=ws.root, repo=ws.clone("api"), shared_file=ws.root / config.WORKSPACE_FILE_NAME)
    titled_workers(env)
    told = Scenario(env, ws.journal(), agent_log, tmp_path / "gates")
    try:
        yield told
    finally:
        told.close()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """A failed scenario test's report carries the story as it played, in a section of its own (`scenario_helpers.py`).

    Yields:
        Nothing: pytest makes the report meanwhile.

    Returns:
        The report pytest made.
    """
    report = yield
    funcargs: dict[str, object] = item.funcargs if isinstance(item, pytest.Function) else {}
    # The call's report: the journal is still open, since fixtures are torn down after it.
    if report.when == "call" and report.failed:
        for name in ("scenario", "ws_scenario"):
            if isinstance(told := funcargs.get(name), Scenario):
                report.sections.append((name, told.told()))
    return report


@pytest.fixture
def backend(tmp_path: Path) -> Backend:
    """The web UI's mock journal, as `canopy serve --mock` serves it."""
    return serve_mock.seed(tmp_path / "mock")


@pytest.fixture
def sink_script(tmp_path: Path) -> Path:
    """A sink command: `sink OUT [EXIT_FILE]` appends what it reads on stdin, then a separator, to OUT, and exits with
    the number in EXIT_FILE if there is one. `messages(OUT)` reads back what it was sent."""
    return executable(
        tmp_path / "sink",
        '#!/bin/sh\ncat >> "$1"\necho "--" >> "$1"\n'
        'if [ -n "$2" ] && [ -f "$2" ]; then echo "sink down" >&2; exit "$(cat "$2")"; fi\n',
    )


@pytest.fixture
def notified(canopy_env: CanopyEnv, tmp_path: Path) -> Path:
    """Set notify.cmd to a script that appends what it reads, then a separator, to the returned file; `messages` reads
    it back. The script exits with $NOTIFY_EXIT, 0 if unset."""
    out = tmp_path / "notified.txt"
    script = executable(tmp_path / "notify", '#!/bin/sh\ncat >> "$1"\necho "--" >> "$1"\nexit "${NOTIFY_EXIT:-0}"\n')
    canopy_env.append_user(f"\n[notify]\ncmd = '{script} {out}'\n")
    return out


class MarkdownSnapshot(SingleFileSnapshotExtension):
    """A snapshot as a Markdown file of its own, as an agent reads what canopy renders for it."""

    file_extension = "md"
    _write_mode = WriteMode.TEXT


@pytest.fixture
def markdown_snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """The test's snapshot, recorded as a Markdown file in its `__snapshots__/` directory."""
    return snapshot.use_extension(MarkdownSnapshot)


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
    origins: Mapping[str, Path]
    state_dir: Path
    journals: Journals

    def journal(self) -> sqlite3.Connection:
        """Open this workspace's journal, closed when the test ends."""
        self.state_dir.mkdir(mode=0o700, exist_ok=True)  # as canopy creates it; anything wider is refused
        return self.journals.open(self.state_dir / db.DB_FILE_NAME)

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


@pytest.fixture
def ws(canopy_env: CanopyEnv, treehouse_state: Path, tmp_path: Path) -> Iterator[Ws]:
    with mock.patch.dict(os.environ, HERMETIC_GIT):
        root = tmp_path / "acme"
        root.mkdir()
        origins = {name: bare_origin(tmp_path / "origins" / f"{name}.git", tmp_path) for name in ("api", "web")}
        for name, origin in origins.items():
            git("clone", "--quiet", str(origin), str(root / "repos" / name), cwd=tmp_path)
        (root / config.WORKSPACE_FILE_NAME).write_text(map_text(*((n, str(o)) for n, o in origins.items())))
        with contextlib.chdir(root):
            yield Ws(root, origins, root / ".canopy", canopy_env.journals)


def seed_pools(ws: Ws, treehouse_state: Path) -> None:
    """Give each repository's pool one slot, a clone of its origin, where canopy's pinned layout puts it."""
    pools: dict[str, object] = {}
    for name, origin in ws.origins.items():
        slot = ws.root / ".treehouse" / f"{name}-fake" / "1" / name
        slot.parent.mkdir(parents=True)
        git("clone", "--quiet", str(origin), str(slot), cwd=ws.root)
        git("checkout", "--quiet", "--detach", cwd=slot)
        pools[str(ws.clone(name))] = {"slots": [{"name": "1", "path": str(slot), "status": "available"}]}
    treehouse_state.write_text(json.dumps({"pools": pools}))


def th(treehouse_state: Path) -> dict[str, list[object]]:
    state: dict[str, list[object]] = json.loads(treehouse_state.read_text())
    return state
