"""Which runs canopy starts in the sandbox wrapper itself: those in `runtime.sandbox_repos` (DESIGN §24)."""

from pathlib import Path
from typing import Final

from canopy.core import config, sandboxing

RUNTIME: Final = config.Runtime(sandbox_repos=("api", "docs"))
DEFINITIONS: Final = Path("/state/definitions")


def test_a_run_in_a_sandboxed_repository_starts_in_the_wrapper_with_its_role() -> None:
    wrapper = str(sandboxing.WRAPPER)

    assert sandboxing.wrap(RUNTIME, ["api"], "worker", ["agent", "run"], DEFINITIONS) == [
        wrapper,
        "worker",
        "--read",
        str(DEFINITIONS),
        "--",
        "agent",
        "run",
    ]
    assert sandboxing.wrap(RUNTIME, ["docs"], "setup", ["make", "setup"]) == [wrapper, "setup", "--", "make", "setup"]
    assert sandboxing.wrap(RUNTIME, ["api"], "review", ["agent"], DEFINITIONS)[:2] == [wrapper, "review"]
    # By its absolute path, beside the interpreter: never looked up where a branch's files could stand in for it.
    assert sandboxing.WRAPPER.is_absolute()


def test_a_run_in_no_sandboxed_repository_starts_as_its_template_has_it() -> None:
    assert sandboxing.wrap(RUNTIME, ["web"], "worker", ["agent", "run"], DEFINITIONS) == ["agent", "run"]
    # A review's repository in a workspace of one is None, and no name matches it.
    assert sandboxing.wrap(RUNTIME, [None], "review", ["agent"], DEFINITIONS) == ["agent"]
    assert sandboxing.wrap(config.Runtime(), ["api"], "worker", ["agent"], DEFINITIONS) == ["agent"]


def test_a_joint_run_is_sandboxed_if_any_of_its_repositories_is() -> None:
    # The dispatch refuses one whose repositories disagree; one the config changed under since still gets the sandbox.
    assert sandboxing.wrap(RUNTIME, ["web", "api"], "worker", ["agent"], DEFINITIONS)[0] == str(sandboxing.WRAPPER)


def test_only_repositories_that_disagree_are_mixed() -> None:
    assert sandboxing.mixed(RUNTIME, ["api", "docs"]) is None
    assert sandboxing.mixed(RUNTIME, ["web", "ios"]) is None
    assert sandboxing.mixed(RUNTIME, ["api", "web"]) == (
        "api runs sandboxed and web does not (runtime.sandbox_repos), and one run is one sandbox or none: dispatch "
        "them as separate runs, or the operator sandboxes all of them or none"
    )
    assert (reason := sandboxing.mixed(RUNTIME, ["api", "docs", "web", "ios"])) is not None
    assert reason.startswith("api, docs run sandboxed and web, ios do not ")
