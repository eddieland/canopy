"""A push's paths against the files its approved plan's steps name: what no step names, and what went untouched."""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import plan_files
from canopy.core.plan_files import Step, Touched, Untouched, compare

if TYPE_CHECKING:
    from pathlib import Path

PLAN = """\
# Plan: PROJ-1 Add the export

## Context

`src/app/old.py:12` is where it starts, which no step names.

## Steps

### Step 1: Add the parser

Add `parse` to `src/app/parse.py`, cited again as `src/app/parse.py:40`, tested in `tests/test_parse.py::test_it`.

```python
# `src/app/fenced.py` is code, not a step's file.
```

#### Tests

`tests/test_parse.py` again, under a lower heading of the same step.

### Step 2: Wire the command `src/app/cli.py`

Call `parse()` and `app.parse`, run `make check`, and touch nothing under `docs/`.

## Verification

`src/app/verify.py` is not a step.
"""


def touched(*paths: str, repo: str = "repo") -> list[Touched]:
    """`paths` as one repository's push touched them."""
    return [Touched(repo, path) for path in paths]


def test_a_push_that_kept_to_its_steps_leaves_nothing_over() -> None:
    found = compare(PLAN, touched("src/app/parse.py", "tests/test_parse.py", "src/app/cli.py", "docs/guide.md"))

    assert found.steps == [
        Step("Step 1: Add the parser", ["src/app/parse.py", "tests/test_parse.py"]),
        Step("Step 2: Wire the command `src/app/cli.py`", ["src/app/cli.py", "docs/"]),
    ]
    assert found.names_files
    assert found.unplanned == []
    assert found.untouched == []


def test_a_path_no_step_names_and_a_step_left_untouched_are_both_found() -> None:
    found = compare(PLAN, touched("src/app/parse.py", "src/app/old.py", "src/app/verify.py", "src/app/fenced.py"))

    # Context, Verification, and fenced code name no step's files.
    assert found.unplanned == touched("src/app/fenced.py", "src/app/old.py", "src/app/verify.py")
    [step_1, step_2] = found.steps
    assert found.untouched == [
        Untouched(step_1, ["tests/test_parse.py"]),
        Untouched(step_2, ["src/app/cli.py", "docs/"]),
    ]


def test_a_bare_name_names_a_file_only_when_the_push_touched_it() -> None:
    plan = "## Steps\n\n### Step 1: Docs\n\nUpdate `README.md` and `CHANGELOG.md`, and call `plans.outline`.\n"

    found = compare(plan, touched("README.md"))

    # `CHANGELOG.md` and `plans.outline` could be names in code: never reported untouched.
    assert found.steps == [Step("Step 1: Docs", ["README.md"])]
    assert found.unplanned == []
    assert found.untouched == []


def test_a_joint_runs_step_may_name_a_path_by_its_repository() -> None:
    plan = "### Step 1: Both\n\nChange `api/src/server.py` and `src/client.ts`.\n"

    pushed = [*touched("src/server.py", repo="api"), *touched("src/client.ts", "src/extra.ts", repo="web")]

    found = compare(plan, pushed)

    assert found.unplanned == touched("src/extra.ts", repo="web")
    assert found.untouched == []


def test_a_directory_names_every_file_under_it_but_not_one_beside_it() -> None:
    plan = "### Step 1: Core\n\nEverything in `src/core` changes.\n"

    found = compare(plan, touched("src/core/a.py", "src/core/b/c.py", "src/core_extra.py"))

    assert found.unplanned == touched("src/core_extra.py")


def test_spans_that_are_no_relative_path_name_nothing() -> None:
    names = ["canopy show run:ID", "https://example.com/a/b", "tests/**/*.py", "../outside/a.py", "/etc/passwd"]
    plan = "### Step 1: Odd\n\n" + "\n".join(f"- `{name}`" for name in names) + "\n"

    assert compare(plan, touched("a.py")).steps == [Step("Step 1: Odd", [])]


def test_a_plan_whose_steps_name_no_files_says_so() -> None:
    plan = "## Steps\n\n### Step 1: Think\n\nDecide what to do.\n\n### Step 2: Do it\n\nDo it well.\n"

    found = compare(plan, touched("src/a.py"))

    assert len(found.steps) == 2
    assert not found.names_files
    # Every path is unplanned, which says nothing: `names_files` tells the caller not to show it.
    assert found.unplanned == touched("src/a.py")


def test_a_plan_without_steps_has_none() -> None:
    plan = "# Plan\n\n## Steps\n\n1. Change `src/a.py`.\n\n### Not a step `src/b.py`\n"

    found = compare(plan, touched("src/a.py"))

    assert found.steps == []
    assert not found.names_files


def test_kept_paths_read_back_as_git_named_them(tmp_path: Path) -> None:
    path = plan_files.path_for(tmp_path / "7.log", "api")
    plan_files.keep(path, "src/a b.py\0src/é.py\0")

    assert path.name == "7.api.paths"
    assert plan_files.read(path) == ["src/a b.py", "src/é.py"]
    assert plan_files.read(tmp_path / "missing.paths") is None


def test_kept_paths_cut_at_the_bound_drop_the_path_cut_short(tmp_path: Path) -> None:
    path = tmp_path / "7.repo.paths"
    whole = "a" * 300 + "\0"
    plan_files.keep(path, whole * (plan_files.MAX_BYTES // len(whole) + 1))

    found = plan_files.read(path)

    assert found is not None
    assert len(found) == plan_files.MAX_BYTES // len(whole)
    assert set(found) == {"a" * 300}


def test_kept_paths_through_a_link_are_not_read(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere"
    target.write_text("secret\0")
    link = tmp_path / "7.repo.paths"
    link.symlink_to(target)

    assert plan_files.read(link) is None
