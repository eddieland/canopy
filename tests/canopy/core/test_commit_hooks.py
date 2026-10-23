"""What canopy hands a worker's environment so that git puts its marks on its commits (TRUST_MODEL T5).

That is an entry for git's hooks directory after any the operator's environment holds, and the trailers and prefix,
unless there is nothing to add; the prefix names the run's ticket, and a task, which has none, gets none that names it.
"""

from pathlib import Path

import pytest

from canopy.core import commit_hooks
from canopy.core.config import ConfigError, load
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
