"""Worktree setup (DESIGN §8, §9, ROADMAP M16): the operator's setup command and personal `.worktreeinclude`.

`runtime.setup_cmd` runs in each slot of a worker run once `_run` has checked out the run's branch, and a failure ends
the run before its worker starts. `paths.worktree_include` reaches every `treehouse get` as `--include-file`.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import override

import pytest

from canopy.core import config
from canopy.infra import procs
from tests.canopy.helpers import (
    BRANCH,
    InlineRunner,
    agent_runs,
    pool,
    slot_of,
    worker_does,
)
from tests.canopy.scenario_helpers import Scenario, dispatches
from tests.conftest import CanopyEnv, GitPool, git, user_toml

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


# The setup command


def test_setup_runs_in_the_slot_on_the_runs_branch_before_the_worker(scenario: Scenario, git_pool: GitPool) -> None:
    """M16 acceptance, against the fakes: setup sees the branch a continued run checks out, unlike `post_create`."""
    seed = git_pool.slots[1]
    git("checkout", "--quiet", "-b", BRANCH, "origin/main", cwd=seed)
    git("commit", "--quiet", "--allow-empty", "-m", "earlier work", cwd=seed)
    git("push", "--quiet", "origin", BRANCH, cwd=seed)
    git("checkout", "--quiet", "--detach", cwd=seed)
    scenario.configures(runtime={"setup_cmd": SETUP})
    run = scenario.run(dispatches(slug="work"), worker=worker_does(["test", "-e", ".setup-done"]))

    assert run.status == "done"
    out = run.printed.out
    assert f"setup on {BRANCH} in repo, run {run.id}: earlier work\n" in out
    assert "--- setup repo exit 0 ---" in out  # in the run log, beside the worker's output
    [w] = agent_runs(scenario.agent_log)
    commands = w["commands"]
    assert isinstance(commands, list)
    assert commands[0]["returncode"] == 0  # the worker found what setup left
    assert w["cwd"] == slot_of(scenario.conn, run.id)["slot_path"]


def test_a_failing_setup_crashes_the_run_before_its_worker_and_returns_the_slot(
    scenario: Scenario, git_pool: GitPool, treehouse_state: Path
) -> None:
    scenario.configures(runtime={"setup_cmd": "sh -c 'echo cannot fetch >&2; exit 3'"})
    run = scenario.run(dispatches(slug="work"))

    assert run.status == "crashed"
    assert json.loads(run.row["result_json"]) == {"harness": "repo: setup exited 3; see the run log"}
    assert "cannot fetch" in run.printed.out
    assert agent_runs(scenario.agent_log) == []  # the worker never ran
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_a_setup_that_times_out_crashes_the_run(scenario: Scenario, git_pool: GitPool, treehouse_state: Path) -> None:
    scenario.configures(runtime={"setup_cmd": "sh -c 'sleep 3600'", "setup_timeout_minutes": 5})
    run = scenario.run(dispatches(slug="work"), runner=SetupTimesOut())

    assert run.status == "crashed"
    assert json.loads(run.row["result_json"]) == {"harness": "repo: setup timed out after 5 minutes; see the run log"}
    assert agent_runs(scenario.agent_log) == []
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_a_setup_that_cannot_start_crashes_the_run(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures(runtime={"setup_cmd": "no-such-setup-command --all"})
    run = scenario.run(dispatches(slug="work"))

    assert run.status == "crashed"
    assert json.loads(run.row["result_json"])["harness"].startswith("repo: setup could not start: ")
    assert agent_runs(scenario.agent_log) == []


def test_a_joint_run_sets_up_every_slot_each_naming_its_repository(ws_scenario: Scenario) -> None:
    ws_scenario.configures(runtime={"setup_cmd": SETUP})
    worker = worker_does(["test", "-e", "api/.setup-done"], ["test", "-e", "web/.setup-done"])
    run = ws_scenario.run(dispatches(repo=("api", "web")), worker=worker)

    log = run.printed.out
    assert f"setup on {BRANCH} in api, run 1: initial api\n" in log
    assert f"setup on {BRANCH} in web, run 1: initial web\n" in log
    [w] = agent_runs(ws_scenario.agent_log)
    commands = w["commands"]
    assert isinstance(commands, list)
    assert [c["returncode"] for c in commands] == [0, 0]


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
    canopy_env.append_shared(f"\n[{section}]\n{line}\n")
    with pytest.raises(config.ConfigError, match="is private"):
        config.load(canopy_env.root, canopy_env.user_file)


# The personal .worktreeinclude


def test_every_lease_passes_the_operators_include_file(
    scenario: Scenario, git_pool: GitPool, treehouse_state: Path
) -> None:
    manifest = scenario.env.home / ".config" / "canopy" / "worktreeinclude"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("user.bazelrc\n.env.local\n")
    scenario.configures(paths={"worktree_include": "~/.config/canopy/worktreeinclude"})
    run = scenario.run(dispatches(slug="work"), worker=worker_does(["true"]))

    [get] = [c for c in treehouse_calls(treehouse_state) if c[0] == "get"]
    # Absolute, with ~ expanded: treehouse reads a relative one from the repository.
    assert get[get.index("--include-file") + 1] == str(manifest)
    leased = next(s for s in pool(treehouse_state) if s["path"] == slot_of(scenario.conn, run.id)["slot_path"])
    assert leased["include_manifest"] == "user.bazelrc\n.env.local\n"


def test_without_an_include_file_treehouse_reads_the_committed_one(
    scenario: Scenario, git_pool: GitPool, treehouse_state: Path
) -> None:
    scenario.run(dispatches(slug="work"), worker=worker_does(["true"]))
    [get] = [c for c in treehouse_calls(treehouse_state) if c[0] == "get"]
    assert "--include-file" not in get


def test_a_missing_include_file_refuses_the_dispatch_and_leases_nothing(
    scenario: Scenario, git_pool: GitPool, treehouse_state: Path
) -> None:
    scenario.configures(paths={"worktree_include": "~/nowhere/worktreeinclude"})
    [(action, rationale)] = scenario.refuses(dispatches(slug="work"))

    assert action == "refused:no_slot"
    assert "failed to read include file" in rationale
    assert all(s["status"] == "available" for s in pool(treehouse_state))
    assert scenario.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_sync_seeds_the_slots_it_makes_from_the_include_file(ws_scenario: Scenario, treehouse_state: Path) -> None:
    # So `post_create`, which runs after seeding, sees during sync the files a run's lease will seed.
    manifest = ws_scenario.env.home / "worktreeinclude"
    manifest.write_text("user.bazelrc\n")
    ws_scenario.configures(paths={"worktree_include": str(manifest)}, capacity={"slots_per_repo": 2})

    ws_scenario.operator("workspace", "sync")
    gets = [c for c in treehouse_calls(treehouse_state) if c[0] == "get"]
    assert len(gets) == 4  # two in each pool
    assert all(c[c.index("--include-file") + 1] == str(manifest) for c in gets)
