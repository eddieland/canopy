"""What `canopy show run:ID` and `show task:N` print of what a run changed (DESIGN §45), from rows written by hand."""

from pathlib import Path

from syrupy.assertion import SnapshotAssertion

from canopy.core import records, review_diff, run_changes
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
    return records.RunChange(7, None, repo, start, on_base, end, fork, left, kept[0], kept[1], missing)


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
