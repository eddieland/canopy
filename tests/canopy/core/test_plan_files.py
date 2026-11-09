"""An `implement`'s touched files held to its approved plan's steps (DESIGN §25, §45), in code, from plans by hand.

A step names a file in a code span: one with a `/` and an extension, or a directory, surely; any other span of a path's
characters only when a touched file matches it. A file touched that no step names, and a step that surely names files
none of which was touched, are what holding them finds. Prose, fenced blocks, and sections outside the steps are not
read.
"""

import sqlite3
from pathlib import Path

import pytest

from canopy.core import db, plan_files, plans, review_diff, run_changes
from canopy.core.context import DISPATCH_LOCK
from canopy.core.plan_files import Held, Step, Touched
from canopy.core.vocab import RunKind, RunStatus
from tests.canopy.helpers import KEY, proposed

#: A plan as the planner's prompt asks for one: files cited in its context, and steps that name theirs.
PLAN = """\
# Plan: PROJ-1 Export reports

## Context

`src/report.py:40` builds the report; `src/unused.py` is read only.

## Steps

### Step 1: Add the CSV writer

Add `src/export/csv.py:1-30` with `write_csv()`, tested in `tests/test_csv.py`.

```text
`src/in_a_fence.py`
```

### Step 2: Wire the button

In `web/src/button.tsx`, and `README.md` says how.

#### Its test

`web/tests/`

### Step 3: Document it

Update `docs/export.md`, and nothing under `src/legacy/`.

### Step 4: Push and open the PR

Run `make check`, then push `agent/PROJ-1-work`.

## Verification

`src/verify.py`
"""


def test_a_plans_steps_hold_the_paths_their_code_spans_name_and_nothing_outside_them() -> None:
    assert plan_files.steps(PLAN) == [
        (Step(1, "Add the CSV writer"), ["src/export/csv.py", "tests/test_csv.py"]),
        (Step(2, "Wire the button"), ["web/src/button.tsx", "README.md", "web/tests/"]),
        (Step(3, "Document it"), ["docs/export.md", "src/legacy/"]),
        # A command has a space, so it is no path; a branch's name is one, though it never surely names a file.
        (Step(4, "Push and open the PR"), ["agent/PROJ-1-work"]),
    ]


def test_files_no_step_names_and_steps_that_touched_none_of_theirs_are_found() -> None:
    touched = [
        Touched("api", "src/export/csv.py"),
        Touched("api", "src/report.py"),
        Touched("web", "tests/button.test.tsx"),
        Touched("web", "README.md"),
    ]
    assert plan_files.held(PLAN, touched) == Held(
        # Cited in the context, and a fence, are not a step's.
        unnamed=(Touched("api", "src/report.py"),),
        # Step 2 names `README.md`, touched; step 4 names no file surely, so it is neither flagged nor matched.
        untouched=(Step(3, "Document it"),),
    )


@pytest.mark.parametrize(
    ("named", "touched"),
    [
        ("src/app.py", Touched("api", "src/app.py")),
        # A path the file ends in on a `/`, the file under its repository's name, and a directory above it.
        ("core/app.py", Touched("api", "src/core/app.py")),
        ("api/src/app.py", Touched("api", "src/app.py")),
        ("src/", Touched("api", "src/deep/app.py")),
        # A renamed file, by the path it had.
        ("src/old.py", Touched("api", "src/new.py", "src/old.py")),
        # A span of a path's characters but no sure path matches only a touched file it is, or ends.
        ("Makefile", Touched("api", "Makefile")),
        ("app.py", Touched("api", "src/app.py")),
    ],
)
def test_a_step_names_a_touched_file_by_its_path_its_end_or_its_directory(named: str, touched: Touched) -> None:
    plan = f"### Step 1: Change it\n\n`{named}`\n"
    assert plan_files.held(plan, [touched]) == Held(unnamed=(), untouched=())


@pytest.mark.parametrize(
    "named",
    [
        # Not on a `/` boundary, the other repository's, a parent the step climbs to, and a span with a space.
        "rc/app.py",
        "web/src/app.py",
        "../src/app.py",
        "src/app.py and more",
    ],
)
def test_a_span_that_does_not_name_the_file_leaves_it_unnamed(named: str) -> None:
    touched = Touched("api", "src/app.py")
    assert plan_files.held(f"### Step 1: Change it\n\n`{named}`\n", [touched]).unnamed == (touched,)


def test_a_step_without_a_sure_path_is_never_flagged_and_a_heading_ends_a_step() -> None:
    plan = (
        "## Steps\n\n### Step 1 - Tidy `src/a.py`\n\nIn prose, src/b.py.\n\n"
        "### Step 2. Explain it\n\nSee `plans.outline` and `README.md`.\n\n## Risks\n\n`src/c.py`\n"
    )
    assert plan_files.steps(plan) == [
        (Step(1, "Tidy `src/a.py`"), ["src/a.py"]),
        (Step(2, "Explain it"), ["plans.outline", "README.md"]),
    ]
    assert plan_files.held(plan, [Touched("api", "src/b.py")]) == Held(
        unnamed=(Touched("api", "src/b.py"),),
        untouched=(Step(1, "Tidy `src/a.py`"),),
    )


def test_an_implement_is_held_to_the_plan_it_followed_as_approved(conn: sqlite3.Connection, tmp_path: Path) -> None:
    plan_id = approved(conn, tmp_path)
    run_id = implement(conn, tmp_path, plan_id, [review_diff.Count("src/export/csv.py", None, 3, 0)])
    assert plan_files.of_run(conn, tmp_path, run_id) == plan_files.Checked(
        plan_id,
        held=Held(unnamed=(), untouched=(Step(2, "Wire the button"), Step(3, "Document it"))),
    )


def test_a_plan_changed_since_approval_or_files_past_the_count_are_not_held(
    conn: sqlite3.Connection,
    tmp_path: Path,
) -> None:
    plan_id = approved(conn, tmp_path)
    many = [review_diff.Count(f"src/{n}.py", None, 1, 0) for n in range(review_diff.MAX_FILES + 1)]
    run_id = implement(conn, tmp_path, plan_id, many)
    checked = plan_files.of_run(conn, tmp_path, run_id)
    assert checked is not None
    assert checked.held is None
    assert checked.unchecked == (
        f"the run touched {review_diff.MAX_FILES + 1} files in api, more than canopy keeps the names of"
    )
    plan = plans.current(conn, KEY)
    assert plan is not None
    plans.path_for(tmp_path, KEY, plan.run_id).write_text(PLAN + "\nEdited after.\n")
    run_id = implement(conn, tmp_path, plan_id, [review_diff.Count("src/export/csv.py", None, 3, 0)])
    assert plan_files.of_run(conn, tmp_path, run_id) == plan_files.Checked(
        plan_id,
        unchecked=f"plan {plan_id}'s file is missing, unreadable, or no longer as the operator approved it",
    )


def test_a_run_that_followed_no_plan_or_counted_nothing_is_not_held(conn: sqlite3.Connection, tmp_path: Path) -> None:
    plan_id = approved(conn, tmp_path)
    counted = [review_diff.Count("src/export/csv.py", None, 3, 0)]
    assert plan_files.of_run(conn, tmp_path, implement(conn, tmp_path, None, counted)) is None
    assert plan_files.of_run(conn, tmp_path, implement(conn, tmp_path, plan_id, None)) is None
    resume = implement(conn, tmp_path, plan_id, counted, kind=RunKind.RESUME)
    assert plan_files.of_run(conn, tmp_path, resume) is None
    assert plan_files.of_run(conn, tmp_path, 999) is None


def approved(conn: sqlite3.Connection, state_dir: Path) -> int:
    """Write `PLAN` as KEY's plan and approve it; return its id."""
    proposed(conn, state_dir, PLAN)
    return plans.approve(conn, state_dir, KEY, channel="cli", dispatch_lock=state_dir / DISPATCH_LOCK).id


def implement(
    conn: sqlite3.Connection,
    state_dir: Path,
    plan_id: int | None,
    counted: list[review_diff.Count] | None,
    *,
    kind: RunKind = RunKind.IMPLEMENT,
) -> int:
    """Record an ended run of KEY that followed `plan_id`, and what it changed in `api`, `counted` or not."""
    tick_id = db.start_tick(conn, dry_run=False)
    run_id = db.insert_run(
        conn,
        tick_id=tick_id,
        key=KEY,
        kind=kind,
        branch="agent/PROJ-1-work",
        slots=[],
        runs_dir=state_dir / "runs",
        plan_id=plan_id,
    )
    db.finish_run(conn, "runs", run_id, RunStatus.DONE, None)
    change = run_changes.Change(
        "api",
        "a" * 40,
        end="b" * 40,
        counted=run_changes.counted(counted) if counted is not None else None,
    )
    run_changes.record(conn, run_id, [change])
    return run_id
