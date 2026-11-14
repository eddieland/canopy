"""Where the sandbox stands, as `canopy health` says it: each command in it or not, srt, and the templates.

The srt `canopy sandbox setup` would install is a script that answers a version to --version, beside the lockfile
setup records. PATH holds only what a test puts there, so no srt of the machine running the tests is found.
"""

import os
import shutil
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import canopy_sandbox
import pytest

from canopy.cli.health import SANDBOX_OFF
from canopy.cli.main import main
from canopy.core import config
from canopy.infra.procs import SubprocessRunner
from canopy.setup import sandbox, sandbox_health
from tests.conftest import CanopyEnv, executable

#: The prefix `canopy init` prints for a worker run's commands, and its like for the others.
WORKER = "canopy-sandbox worker --read {definitions_dir} --"
REVIEW = "canopy-sandbox review --read {definitions_dir} --"
#: The words of a command the fake agent runs, after a prefix.
AGENT = "env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent {agent} --format json {prompt}"


@dataclass(frozen=True)
class Machine:
    """The operator's templates and the srt setup installed, as `canopy sandbox setup` leaves them."""

    templates: Path
    srt: Path

    def answers(self, version: str) -> None:
        """Have the installed srt answer `version` to --version."""
        executable(self.srt, f"#!{sys.executable}\nprint({version!r})\n")


@pytest.fixture
def machine(canopy_env: CanopyEnv, tmp_path: Path) -> Iterator[Machine]:
    """The shipped templates and the pinned srt where setup puts them, and PATH an empty directory, `bin`."""
    templates = config.user_config_dir() / "sandbox"
    templates.mkdir(parents=True)
    for role in canopy_sandbox.ROLES:
        shutil.copy(canopy_sandbox.TEMPLATES / f"{role}.json", templates)
    runtime = canopy_sandbox.runtime_dir()
    srt = runtime / "node_modules" / ".bin" / "srt"
    srt.parent.mkdir(parents=True)
    shutil.copy(canopy_sandbox.RUNTIME_SPEC / "package-lock.json", runtime / sandbox.INSTALLED_LOCK)
    (tmp_path / "bin").mkdir()
    with mock.patch.dict(os.environ, {"PATH": str(tmp_path / "bin")}):
        found = Machine(templates, srt)
        found.answers(sandbox.pinned_version())
        yield found


def health(capsys: pytest.CaptureFixture[str]) -> list[str]:
    """Run `canopy health`, and return the lines it printed about the sandbox."""
    assert main(["health"]) == 0
    out = capsys.readouterr().out.splitlines()
    starts = [i for i, line in enumerate(out) if line.startswith("Sandbox")]
    assert len(starts) == 1, out
    return out[starts[0] :]


def agent(name: str) -> str:
    return AGENT.format(definitions_dir="{definitions_dir}", agent=name, prompt="{prompt}")


@pytest.mark.usefixtures("machine")
def test_with_no_command_in_the_sandbox_health_says_so_in_one_neutral_line(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert health(capsys) == [SANDBOX_OFF]

    found = sandbox_health.standing(config.load(canopy_env.root), SubprocessRunner())

    assert not found.sandboxed
    assert (found.srt, found.templates) == (None, {})


@pytest.mark.usefixtures("machine")
def test_a_command_left_outside_beside_wrapped_ones_is_named(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The worker and planner are wrapped by hand, and the private worker, easy to miss, is not (docs/SANDBOX.md)."""
    canopy_env.configure(
        canopy_env.user_file,
        {
            "runtime": {
                "worker_cmd": f"{WORKER} {agent('canopy-worker')}",
                "plan_cmd": f"{WORKER} {agent('canopy-planner')}",
                "review_cmd": f"{REVIEW} {agent('canopy-reviewer')}",
                "chore_cmd": f"canopy-sandbox chore -- {agent('canopy-chore')}",
            },
            "chores": {"deps": {"prompt": "~/deps.md", "every_minutes": 60, "cmd": "deps-check {prompt}"}},
        },
    )

    assert health(capsys) == [
        "Sandbox, by the config in force (! outside it, or what keeps a run from starting in it):",
        "  overseer        outside the sandbox: runtime.overseer_cmd !",
        "  worker          worker.json",
        "  private worker  outside the sandbox: runtime.private_worker_cmd !",
        "  planner         worker.json",
        "  reviewer        review.json",
        "  chore           chore.json",
        "  chore deps      outside the sandbox: chores.deps.cmd !",
        f"  srt {sandbox.pinned_version()}, as pinned",
        "  worker.json, review.json, chore.json load",
    ]


@pytest.mark.usefixtures("machine")
def test_the_repositories_sandbox_repos_names_are_said(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    canopy_env.configure(
        canopy_env.user_file,
        {"runtime": {"sandbox_repos": ["repo", "billing"], "setup_cmd": "sh -c true"}},
    )

    lines = health(capsys)

    assert lines[1:9] == [
        "  overseer        outside the sandbox: runtime.overseer_cmd !",
        "  worker          worker.json in repo, billing",
        "  private worker  worker.json in repo, billing",
        "  planner         worker.json in repo, billing",
        "  reviewer        review.json in repo, billing",
        "  chore           outside the sandbox: runtime.chore_cmd !",
        "  setup           setup.json in repo, billing",
        f"  srt {sandbox.pinned_version()}, as pinned",
    ]
    assert lines[9:] == ["  worker.json, review.json, setup.json load"]


def test_an_srt_off_the_pin_and_a_template_a_run_would_refuse_are_flagged(
    machine: Machine,
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    canopy_env.configure(
        canopy_env.user_file,
        {"runtime": {"worker_cmd_prefix": WORKER, "review_cmd": f"{REVIEW} {agent('canopy-reviewer')}"}},
    )
    machine.answers("0.0.1")
    (machine.templates / "review.json").write_text('{"network": {"allowedDomains": []}, "filesystem": {}}')
    (machine.templates / "worker.json").unlink()
    runtime = canopy_sandbox.runtime_dir()
    setup = "run `canopy sandbox setup` !"

    lines = health(capsys)

    assert lines[-3:] == [
        f"  srt in {runtime} answers 0.0.1 to --version, not the pinned {sandbox.pinned_version()}: {setup}",
        f"  worker.json: no policy template at {machine.templates / 'worker.json'}; {setup}",
        "  review.json: the policy template denies no reads: give it a filesystem.denyRead !",
    ]


def test_an_srt_missing_or_found_on_path_alone_is_not_the_pinned_one(
    machine: Machine,
    canopy_env: CanopyEnv,
    tmp_path: Path,
) -> None:
    canopy_env.configure(canopy_env.user_file, {"runtime": {"worker_cmd_prefix": WORKER}})
    shutil.rmtree(canopy_sandbox.runtime_dir())
    version = sandbox.pinned_version()

    def srt() -> str | None:
        return sandbox_health.standing(config.load(canopy_env.root), SubprocessRunner()).srt

    assert srt() == f"srt is not installed, so no sandboxed run starts; canopy pins {version}"

    on_path = executable(tmp_path / "bin" / "srt", f"#!{sys.executable}\nprint({version!r})\n")
    assert srt() == f"the wrapper runs {on_path}, from PATH, not the srt {version} canopy pins"

    machine.srt.parent.mkdir(parents=True)
    machine.answers(version)
    assert srt() == f"srt {version} in {canopy_sandbox.runtime_dir()} was not installed from this canopy's lockfile"


@pytest.mark.usefixtures("machine")
def test_a_role_the_wrapper_does_not_know_is_flagged(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    canopy_env.configure(canopy_env.user_file, {"runtime": {"worker_cmd_prefix": "canopy-sandbox --"}})

    lines = health(capsys)

    assert "  worker          --.json" in lines
    assert lines[-1] == (
        "  --.json: canopy-sandbox has no role '--': it takes worker, setup, chore, review, overseer !"
    )


@pytest.mark.usefixtures("machine")
def test_inside_one_of_canopys_runs_health_leaves_the_sandbox_out(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    canopy_env.configure(canopy_env.user_file, {"runtime": {"worker_cmd_prefix": WORKER}})

    with mock.patch.dict(os.environ, {"CANOPY_RUN_ID": "7"}):
        assert main(["health"]) == 0

    assert not any(line.startswith("Sandbox") for line in capsys.readouterr().out.splitlines())
