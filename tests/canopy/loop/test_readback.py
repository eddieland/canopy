"""What `canopy show run:ID` and `show task:N` print of what a run changed (DESIGN §45), from rows written by hand."""

from pathlib import Path

from syrupy.assertion import SnapshotAssertion

from canopy.core import plan_files, records, review_diff, run_changes
from canopy.loop import readback

START = "1" * 40
END = "2" * 40
FORK = "3" * 40
LEFT = "4" * 40


def change(
    repo: str,
    *,
    start: str | None = START,
    on_base: bool = False,
    end: str | None = END,
    fork: str | None = FORK,
    left: str | None = None,
    kept: tuple[bool, bool] = (True, True),
    missing: str | None = None,
) -> records.RunChange:
    """A row of run 7's: its range, whether each diff was kept, and why one was not."""
    return records.RunChange(
        7,
        None,
        repo,
        start,
        on_base,
        end,
        fork,
        left,
        kept[0],
        kept[1],
        missing,
        None,
        None,
        None,
    )


def test_each_repositorys_range_and_kept_diffs_are_printed(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    log = tmp_path / "runs" / "7.log"
    log.parent.mkdir()
    for repo in ("api", "web", "docs"):
        run_changes.change_path(log, repo).write_text("")
    review_diff.run_path_for(log, "api").write_text("")
    rows = [
        change("api"),
        # Left unpushed, its branch diff since removed with the run's other files.
        change("docs", on_base=True, end=None, left=LEFT),
        change("old", start=None, end=None, fork=None, kept=(False, False), missing=run_changes.CRASHED),
        change("web", fork=None, kept=(True, False), missing="the branch against main: no merge base"),
        change("wiki", end=None, fork=None, kept=(False, False), missing="no branch"),
    ]
    lines = readback.change_lines(rows, log_path=str(log))
    assert "\n".join(lines).replace(str(tmp_path), "<state>") == snapshot


def test_an_implements_files_held_to_its_plan_print_what_was_found_or_why_nothing_was() -> None:
    """A path and a step's title are printed on one line, their control characters dropped."""
    found = plan_files.Checked(
        3,
        held=plan_files.Held(
            unnamed=(plan_files.Touched("web", "src/a\x1b[2J.ts"),),
            untouched=(plan_files.Step(2, "Wire\nthe button"),),
        ),
    )
    assert readback.plan_lines(found) == [
        "touched, named by no step:",
        "  web  src/a [2J.ts",
        "steps none of whose files it touched:",
        "  Step 2: Wire the button",
    ]
    held = plan_files.Checked(3, held=plan_files.Held(unnamed=(), untouched=()))
    assert readback.plan_lines(held) == [
        "every file it touched is named by a step, and every step that names a file had one touched",
    ]
    assert readback.plan_lines(plan_files.Checked(3, unchecked="its file\nchanged")) == [
        "not held to it: its file changed",
    ]
