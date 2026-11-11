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
    commit_count: int | None = None,
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
        commit_count,
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


def commit(  # noqa: PLR0913: a row's every mark, each named where the test sets it.
    position: int,
    sha: str,
    subject: str,
    *,
    canopy_trailer: bool | None = True,
    prefixed: bool | None = True,
    runtime_trailer: bool = False,
    harness_pushed: bool = False,
) -> records.RunCommit:
    """A commit run 7 recorded in `api`, carrying canopy's marks unless the test says otherwise."""
    return records.RunCommit(
        7,
        None,
        "api",
        position,
        sha,
        subject,
        canopy_trailer,
        prefixed,
        runtime_trailer,
        harness_pushed,
    )


def test_each_repositorys_commits_are_printed_oldest_first_with_the_marks_they_lack(
    tmp_path: Path,
    snapshot: SnapshotAssertion,
) -> None:
    log = tmp_path / "runs" / "7.log"
    rows = [
        # Four commits, the oldest of which a run's bound left out.
        change("api", kept=(False, False), missing="gone", commit_count=4),
        # No commit in its range.
        change("docs", kept=(False, False), missing="gone", commit_count=0),
        # Its commits never read.
        change("web", kept=(False, False), missing="gone"),
    ]
    commits = {
        "api": [
            commit(0, "5" * 40, "PROJ-7: the change", runtime_trailer=True),
            commit(1, "6" * 40, "a commit around the hooks <U+200B>", canopy_trailer=False, prefixed=False),
            commit(2, "7" * 40, "PROJ-7: the rest", canopy_trailer=None, prefixed=None, harness_pushed=True),
        ],
    }
    lines = readback.change_lines(rows, log_path=str(log), commits=commits)
    assert "\n".join(lines) == snapshot


def test_without_the_commits_their_count_alone_is_printed(tmp_path: Path) -> None:
    log = tmp_path / "runs" / "7.log"
    rows = [change("api", kept=(False, False), missing="gone", commit_count=4)]
    assert readback.change_lines(rows, log_path=str(log)) == [
        f"api  {START[:12]}..{END[:12]}, merge base {FORK[:12]}",
        "  not kept: gone",
        "  commits (4)",
    ]
