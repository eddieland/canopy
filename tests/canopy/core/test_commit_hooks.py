"""What canopy hands a worker's environment so that git adds its trailers (TRUST_MODEL T5).

That is an entry for git's hooks directory after any the operator's environment holds, and the trailers, unless there
are none to add.
"""

from pathlib import Path

from canopy.core import commit_hooks
from canopy.core.config import load
from tests.conftest import CanopyEnv

TRAILER = "Co-authored-by: canopy worker <noreply@canopy.invalid>"


def test_canopys_entry_comes_after_the_operators_own() -> None:
    inherited = {"GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "a.b", "GIT_CONFIG_KEY_1": "c.d"}
    assert commit_hooks.env(Path("/snap"), [TRAILER, "Co-authored-by: x <y@z>"], inherited) == {
        "GIT_CONFIG_COUNT": "3",
        "GIT_CONFIG_KEY_2": "core.hooksPath",
        "GIT_CONFIG_VALUE_2": "/snap/git-hooks",
        "CANOPY_COMMIT_TRAILERS": f"{TRAILER}\nCo-authored-by: x <y@z>",
    }


def test_a_count_git_would_refuse_is_replaced() -> None:
    found = commit_hooks.env(Path("/snap"), [TRAILER], {"GIT_CONFIG_COUNT": "many"})
    assert (found["GIT_CONFIG_COUNT"], found["GIT_CONFIG_KEY_0"]) == ("1", "core.hooksPath")


def test_with_nothing_to_add_git_is_left_as_it_was() -> None:
    assert commit_hooks.env(Path("/snap"), [], {"GIT_CONFIG_COUNT": "1"}) == {}


def test_the_trailers_are_the_prompts_and_none_while_canopys_is_off(canopy_env: CanopyEnv) -> None:
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert commit_hooks.trailers(cfg, "p/m", "p/n") == [
        "Co-authored-by: p/m (canopy worker) <noreply@canopy.invalid>",
        "Co-authored-by: p/n (canopy planner) <noreply@canopy.invalid>",
    ]
    canopy_env.configure(canopy_env.user_file, {"trust": {"commit_trailer": False}})
    assert commit_hooks.trailers(load(canopy_env.root, canopy_env.user_file), "p/m", "p/n") == []
