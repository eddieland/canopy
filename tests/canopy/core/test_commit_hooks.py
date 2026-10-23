"""What canopy hands a worker's environment so that git puts its marks on its commits (TRUST_MODEL T5).

That is an entry for git's hooks directory after any the operator's environment holds, and the trailers and prefix,
unless there is nothing to add; the prefix names the run's ticket, and a task, which has none, gets none that names it.
"""

from pathlib import Path
from unittest import mock

import pytest

from canopy.core import commit_hooks
from canopy.core.config import ConfigError, load
from canopy.infra import procs
from tests.conftest import CanopyEnv

TRAILER = "Co-authored-by: canopy worker <noreply@canopy.invalid>"


def test_canopys_entry_comes_after_the_operators_own() -> None:
    inherited = {"GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "a.b", "GIT_CONFIG_KEY_1": "c.d"}
    marks = commit_hooks.Marks((TRAILER, "Co-authored-by: x <y@z>"), "PROJ-1: ")
    assert commit_hooks.env(Path("/snap"), marks, inherited) == {
        "GIT_CONFIG_COUNT": "3",
        "GIT_CONFIG_KEY_2": "core.hooksPath",
        "GIT_CONFIG_VALUE_2": "/snap/git-hooks",
        "CANOPY_COMMIT_TRAILERS": f"{TRAILER}\nCo-authored-by: x <y@z>",
        "CANOPY_COMMIT_PREFIX": "PROJ-1: ",
    }


def test_a_count_git_would_refuse_is_replaced() -> None:
    found = commit_hooks.env(Path("/snap"), commit_hooks.Marks((TRAILER,)), {"GIT_CONFIG_COUNT": "many"})
    assert (found["GIT_CONFIG_COUNT"], found["GIT_CONFIG_KEY_0"]) == ("1", "core.hooksPath")
    assert commit_hooks.PREFIX_ENV not in found


def test_with_nothing_to_add_git_is_left_as_it_was() -> None:
    assert commit_hooks.env(Path("/snap"), commit_hooks.NONE, {"GIT_CONFIG_COUNT": "1"}) == {}


def test_the_trailers_are_the_prompts_and_none_while_canopys_is_off(canopy_env: CanopyEnv) -> None:
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert commit_hooks.marks(cfg, key="PROJ-1", model="p/m", planner_model="p/n") == commit_hooks.Marks(
        (
            "Co-authored-by: p/m (canopy worker) <noreply@canopy.invalid>",
            "Co-authored-by: p/n (canopy planner) <noreply@canopy.invalid>",
        ),
    )
    canopy_env.configure(canopy_env.user_file, {"trust": {"commit_trailer": False}})
    assert commit_hooks.marks(load(canopy_env.root, canopy_env.user_file), key="PROJ-1") == commit_hooks.NONE


def test_the_prefix_names_the_runs_ticket_and_a_task_gets_none_that_names_one(canopy_env: CanopyEnv) -> None:
    canopy_env.configure(canopy_env.user_file, {"trust": {"commit_prefix": "[{key}] "}})
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert commit_hooks.marks(cfg, key="PROJ-1").prefix == "[PROJ-1] "
    assert commit_hooks.marks(cfg, key=None).prefix == ""
    # One that names no ticket is every run's, a task's too.
    canopy_env.configure(canopy_env.user_file, {"trust": {"commit_prefix": "agent: "}})
    assert commit_hooks.marks(load(canopy_env.root, canopy_env.user_file), key=None).prefix == "agent: "


@pytest.mark.parametrize(
    "prefix",
    ["`{key}` ", "{ticket}: ", "#{key} ", " {key}: ", "fixup! ", "{key}:\n", "x" * 61],
)
def test_a_prefix_that_would_break_a_subject_or_its_quoting_is_refused(canopy_env: CanopyEnv, prefix: str) -> None:
    canopy_env.configure(canopy_env.user_file, {"trust": {"commit_prefix": prefix}})
    with pytest.raises(ConfigError, match="commit_prefix"):
        load(canopy_env.root, canopy_env.user_file)


def test_a_shared_file_cannot_set_the_prefix(canopy_env: CanopyEnv) -> None:
    canopy_env.configure(canopy_env.shared_file, {"trust": {"commit_prefix": "{key}: "}})
    with pytest.raises(ConfigError, match="commit_prefix"):
        load(canopy_env.root, canopy_env.user_file)


@pytest.mark.parametrize(
    ("printed", "old"),
    [
        ("git version 2.30.9\n", "2.30"),
        ("git version 1.8.3.1\n", "1.8"),
        ("git version 2.31.0\n", None),
        ("git version 2.39.3 (Apple Git-145)\n", None),
        ("git version 2.45.1.windows.1\n", None),
        # A git that does not say its version is no finding: its runs' own git steps say what is wrong.
        ("not git\n", None),
    ],
)
def test_a_git_older_than_the_hooks_need_is_named(canopy_env: CanopyEnv, printed: str, old: str | None) -> None:
    runner = mock.create_autospec(procs.Runner, instance=True)
    runner.run.return_value = procs.Result(("git", "--version"), 0, printed, "")
    found = commit_hooks.git_too_old(load(canopy_env.root, canopy_env.user_file), runner)
    if old is None:
        assert found is None
    else:
        assert found == (
            f"git {old} on PATH is older than 2.31, which canopy's commit hooks need: workers' commits get no trailer "
            "or prefix, and each run's note names them; install git 2.31 or later"
        )


def test_a_git_that_cannot_run_is_no_finding(canopy_env: CanopyEnv) -> None:
    runner = mock.create_autospec(procs.Runner, instance=True)
    runner.run.side_effect = procs.CommandNotFoundError("git")
    assert commit_hooks.git_too_old(load(canopy_env.root, canopy_env.user_file), runner) is None


def test_with_no_marks_to_add_the_version_is_not_read(canopy_env: CanopyEnv) -> None:
    canopy_env.configure(canopy_env.user_file, {"trust": {"commit_trailer": False}})
    runner = mock.create_autospec(procs.Runner, instance=True)
    assert commit_hooks.git_too_old(load(canopy_env.root, canopy_env.user_file), runner) is None
    runner.run.assert_not_called()
