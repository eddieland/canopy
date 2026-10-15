"""Worktree setup (DESIGN §8, §9, ROADMAP M16): the operator's setup command and personal `.worktreeinclude`.

`runtime.setup_cmd` runs in each slot of a worker run once `_run` has checked out the run's branch, and a failure ends
the run before its worker starts. `paths.worktree_include` reaches every `treehouse get` as `--include-file`.
"""

import json
import os
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import override
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import config, db
from canopy.infra import procs
from tests.canopy.conftest import Ws, seed_pools
from tests.canopy.helpers import InlineRunner, in_tick, journal, pool, slot_of, wait_for_run, worker_does
from tests.conftest import CanopyEnv, GitPool, git, user_toml

LABEL = "agent-ready-tester"
BRANCH = "agent/PROJ-1-work"
# What a setup sees: the run's branch, its repository, its run, and the latest commit checked out, the branch's. It
# leaves a file the worker then looks for, so the setup ran before the worker.
SETUP = (
    'sh -c \'echo "setup on $CANOPY_BRANCH in $CANOPY_REPO, run $CANOPY_RUN_ID: $(git log -1 --format=%s)"; '
    "touch .setup-done'"
)


def configure(canopy_env: CanopyEnv, *, runtime: str = "", paths: str = "") -> None:
    """Rewrite the user file with `runtime` lines in its `[runtime]` table and `paths` lines in its `[paths]` one."""
    text = user_toml()
    text = text.replace("[runtime]\n", f"[runtime]\n{runtime}\n").replace("[paths]\n", f"[paths]\n{paths}\n")
    canopy_env.write_user(text)


def setup_is(canopy_env: CanopyEnv, command: str, *extra: str) -> None:
    configure(canopy_env, runtime="\n".join((f"setup_cmd = '''{command}'''", *extra)))


def dispatch(*args: str, kind: str = "implement") -> list[str]:
    """`canopy dispatch` for PROJ-1, in the only repository unless `args` name others."""
    repos = () if "--repo" in args else ("--repo", "repo")
    return ["dispatch", "PROJ-1", *repos, "--label", LABEL, "--kind", kind, *args]


def dispatch_and_run(conn: sqlite3.Connection, runner: InlineRunner) -> sqlite3.Row:
    with in_tick(conn) as tick_id:
        assert main(dispatch("--slug", "work"), runner=runner) == 0
        db.finish_tick(conn, tick_id, "ok", "test")
        run_id = int(conn.execute("SELECT max(id) FROM runs").fetchone()[0])
        assert main(["_run", str(run_id)], runner=runner) == 0
        row = db.get_run(conn, run_id)
        assert row is not None
        return row


def agent_runs(agent_log: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in agent_log.read_text().splitlines()] if agent_log.exists() else []


def treehouse_calls(treehouse_state: Path) -> list[list[str]]:
    found: list[list[str]] = json.loads(treehouse_state.read_text()).get("calls", [])
    return found


class SetupTimesOut(InlineRunner):
    """The setup command comes back timed out; everything else runs as `InlineRunner` runs it."""

    @override
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
        if args[0] == "sh":
            return procs.Result(tuple(args), -9, "installing\n", "", timed_out=True)
        return super().run(args, cwd=cwd, env=env, stdin=stdin, timeout=timeout, on_start=on_start, on_line=on_line)


@pytest.fixture
def conn(canopy_env: CanopyEnv) -> sqlite3.Connection:
    return journal(canopy_env)


# The setup command


def test_setup_runs_in_the_slot_on_the_runs_branch_before_the_worker(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """M16 acceptance, against the fakes: setup sees the branch a continued run checks out, unlike `post_create`."""
    seed = git_pool.slots[1]
    git("checkout", "--quiet", "-b", BRANCH, "origin/main", cwd=seed)
    git("commit", "--quiet", "--allow-empty", "-m", "earlier work", cwd=seed)
    git("push", "--quiet", "origin", BRANCH, cwd=seed)
    git("checkout", "--quiet", "--detach", cwd=seed)
    setup_is(canopy_env, SETUP)
    with worker_does(["test", "-e", ".setup-done"]):
        run = dispatch_and_run(conn, InlineRunner())

    assert run["status"] == "done"
    out = capsys.readouterr().out
    assert f"setup on {BRANCH} in repo, run {run['id']}: earlier work\n" in out
    assert "--- setup repo exit 0 ---" in out  # in the run log, beside the worker's output
    [w] = agent_runs(agent_log)
    commands = w["commands"]
    assert isinstance(commands, list)
    assert commands[0]["returncode"] == 0  # the worker found what setup left
    assert w["cwd"] == slot_of(conn, run["id"])["slot_path"]


def test_a_failing_setup_crashes_the_run_before_its_worker_and_returns_the_slot(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    setup_is(canopy_env, "sh -c 'echo cannot fetch >&2; exit 3'")
    run = dispatch_and_run(conn, InlineRunner())

    assert run["status"] == "crashed"
    assert json.loads(run["result_json"]) == {"harness": "repo: setup exited 3; see the run log"}
    assert "cannot fetch" in capsys.readouterr().out
    assert agent_runs(agent_log) == []  # the worker never ran
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_a_setup_that_times_out_crashes_the_run(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    setup_is(canopy_env, "sh -c 'sleep 3600'", "setup_timeout_minutes = 5")
    run = dispatch_and_run(conn, SetupTimesOut())

    assert run["status"] == "crashed"
    assert json.loads(run["result_json"]) == {"harness": "repo: setup timed out after 5 minutes; see the run log"}
    assert agent_runs(agent_log) == []
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_a_setup_that_cannot_start_crashes_the_run(
    canopy_env: CanopyEnv, git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection
) -> None:
    setup_is(canopy_env, "no-such-setup-command --all")
    run = dispatch_and_run(conn, InlineRunner())

    assert run["status"] == "crashed"
    assert json.loads(run["result_json"])["harness"].startswith("repo: setup could not start: ")
    assert agent_runs(agent_log) == []


def test_a_joint_run_sets_up_every_slot_each_naming_its_repository(
    ws: Ws, canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    seed_pools(ws, treehouse_state)
    setup_is(canopy_env, SETUP)
    conn = ws.journal()
    with in_tick(conn), worker_does(["test", "-e", "api/.setup-done"], ["test", "-e", "web/.setup-done"]):
        assert main(dispatch("--repo", "api", "--repo", "web")) == 0
        run = wait_for_run(conn, 1)

        log = Path(run["log_path"]).read_text()
        assert f"setup on {BRANCH} in api, run 1: initial api\n" in log
        assert f"setup on {BRANCH} in web, run 1: initial web\n" in log
        [w] = agent_runs(agent_log)
        commands = w["commands"]
        assert isinstance(commands, list)
        assert [c["returncode"] for c in commands] == [0, 0]


def test_a_split_runs_no_setup(ws: Ws, canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path) -> None:
    # The splitter reads its desk and has no shell to use what setup would install (DESIGN §18).
    seed_pools(ws, treehouse_state)
    setup_is(canopy_env, "sh -c 'exit 1'")
    conn = ws.journal()
    result = {"status": "done", "summary": "split in two", "children": {"PROJ-13": "api", "PROJ-14": "web"}}
    with in_tick(conn), mock.patch.dict(os.environ, {"FAKE_SPLITTER_RESULT": json.dumps(result)}):
        split = [
            "dispatch",
            "PROJ-12",
            "--label",
            LABEL,
            "--kind",
            "split",
            "--request",
            "1",
            "--repo",
            "api",
        ]
        assert main([*split, "--repo", "web"]) == 0
        run = wait_for_run(conn, 1)
        assert run["status"] == "done", Path(run["log_path"]).read_text()
        assert "--- setup" not in Path(run["log_path"]).read_text()


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("setup_cmd = 'sh -c \"unclosed'", "No closing quotation"),
        ("setup_cmd = 'install {prompt}'", r"must not contain \{prompt\} or \{definitions_dir\}"),
        ("setup_cmd = 'install {definitions_dir}'", "setup runs no agent"),
        ("setup_timeout_minutes = 0", "greater than or equal to 1"),
    ],
)
def test_a_setup_command_is_checked_when_the_config_loads(canopy_env: CanopyEnv, line: str, message: str) -> None:
    configure(canopy_env, runtime=line)
    with pytest.raises(config.ConfigError, match=message):
        config.load(canopy_env.root, canopy_env.user_file)


@pytest.mark.parametrize(
    ("section", "line"),
    [
        ("runtime", "setup_cmd = 'curl evil'"),
        ("runtime", "setup_timeout_minutes = 600"),
        ("paths", "worktree_include = '/tmp/x'"),
    ],
)
def test_setup_and_the_include_file_are_user_only(canopy_env: CanopyEnv, section: str, line: str) -> None:
    # Either would run or seed what a commit chose on the operator's machine (TRUST_MODEL T7).
    canopy_env.write_shared(canopy_env.shared_file.read_text() + f"\n[{section}]\n{line}\n")
    with pytest.raises(config.ConfigError, match="user-only"):
        config.load(canopy_env.root, canopy_env.user_file)


# The personal .worktreeinclude


def test_every_lease_passes_the_operators_include_file(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    manifest = canopy_env.home / ".config" / "canopy" / "worktreeinclude"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("user.bazelrc\n.env.local\n")
    configure(canopy_env, paths="worktree_include = '~/.config/canopy/worktreeinclude'")
    with worker_does(["true"]):
        run = dispatch_and_run(conn, InlineRunner())

    [get] = [c for c in treehouse_calls(treehouse_state) if c[0] == "get"]
    # Absolute, with ~ expanded: treehouse reads a relative one from the repository.
    assert get[get.index("--include-file") + 1] == str(manifest)
    leased = next(s for s in pool(treehouse_state) if s["path"] == slot_of(conn, run["id"])["slot_path"])
    assert leased["include_manifest"] == "user.bazelrc\n.env.local\n"


def test_without_an_include_file_treehouse_reads_the_committed_one(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    with worker_does(["true"]):
        dispatch_and_run(conn, InlineRunner())
    [get] = [c for c in treehouse_calls(treehouse_state) if c[0] == "get"]
    assert "--include-file" not in get


def test_a_missing_include_file_refuses_the_dispatch_and_leases_nothing(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    configure(canopy_env, paths="worktree_include = '~/nowhere/worktreeinclude'")
    with in_tick(conn) as tick_id:
        assert main(dispatch("--slug", "work"), runner=InlineRunner()) == 1

    [decision] = db.decisions_for_tick(conn, tick_id)
    assert decision.action == "refused:no_slot"
    assert "failed to read include file" in decision.rationale
    assert all(s["status"] == "available" for s in pool(treehouse_state))
    assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_sync_seeds_the_slots_it_makes_from_the_include_file(
    ws: Ws, canopy_env: CanopyEnv, treehouse_state: Path
) -> None:
    # So `post_create`, which runs after seeding, sees during sync the files a run's lease will seed.
    manifest = canopy_env.home / "worktreeinclude"
    manifest.write_text("user.bazelrc\n")
    configure(canopy_env, paths=f"worktree_include = '{manifest}'")
    canopy_env.write_user(canopy_env.user_file.read_text() + "\n[capacity]\nslots_per_repo = 2\n")
    seed_pools(ws, treehouse_state)

    assert main(["workspace", "sync"]) == 0
    gets = [c for c in treehouse_calls(treehouse_state) if c[0] == "get"]
    assert len(gets) == 4  # two in each pool
    assert all(c[c.index("--include-file") + 1] == str(manifest) for c in gets)
