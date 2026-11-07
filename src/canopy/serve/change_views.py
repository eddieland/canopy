"""What a worker's or a task's run changed, as its page and its ticket's runs list show it (DESIGN §45).

Each repository's range, the commits the harness read as the run ended, and its size, the files and lines git counted
of the run's own change then (`run_changes`): a summary read from the journal alone, no kept diff read. The run's own
diff is sent on its own when the page opens it, read within a review's diff's bounds (`review_diff.read`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import review_diff, run_changes
from canopy.serve.diff_views import diff_view
from canopy.serve.schema import ChangedFile, ReviewDiff, RunChange, RunRange
from canopy.serve.transcript_views import removed_after

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Collection, Mapping

    from canopy.core import records
    from canopy.core.run_changes import RunTable


def run_changes_of(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    log_path: str,
    ended_at: str | None,
    prs: Mapping[str, str] | None = None,
    table: RunTable = "runs",
) -> list[RunChange]:
    """What run `run_id` of `table` changed in each repository: its range, its files as git counted them, no diff.

    `log_path` is where its own change's diff is kept beside, which is looked for and never read; `ended_at`, when the
    run ended, says whether retention removed one that is gone. `prs` is the PR of each repository, by name, whose
    page shows the branch against its base.

    Returns:
        A change per repository the run recorded, by repository; none for a run that recorded none.
    """
    found: list[RunChange] = []
    for row in run_changes.of_run(conn, run_id, table=table):
        path = run_changes.change_path(log_path, row.repo)
        removed = removed_after(conn, path, ended_at, "run_files_days") if row.change_kept else None
        found.append(
            RunChange(
                range=run_range(row),
                files=[
                    ChangedFile(path=f.path, old_path=f.old_path, added=f.added, removed=f.removed)
                    for f in run_changes.files_of(conn, run_id, row.repo, table=table)
                ],
                # Looked for, never read: a link in its place is no diff.
                diff_kept=row.change_kept and path.is_file() and not path.is_symlink(),
                missing=row.missing,
                removed_after_days=removed,
                pr_url=(prs or {}).get(row.repo),
            ),
        )
    return found


def run_diff(
    conn: sqlite3.Connection,
    run_id: int,
    repo: str,
    *,
    log_path: str,
    table: RunTable = "runs",
) -> ReviewDiff | None:
    """The diff of run `run_id`'s own change to `repo`, kept beside its log, `log_path`, read within its bounds.

    Returns:
        The diff; None when the run recorded no change to `repo`, kept no diff of it, or its file is gone, a symlink,
        or not a regular file.
    """
    rows = [r for r in run_changes.of_run(conn, run_id, table=table) if r.repo == repo]
    if not rows or not rows[0].change_kept:
        return None
    # The path is made from the journal's repository name, never the request's.
    diff = review_diff.read(run_changes.change_path(log_path, rows[0].repo))
    return diff_view(diff) if diff is not None else None


def ranges_of(conn: sqlite3.Connection, run_ids: Collection[int]) -> dict[int, list[RunRange]]:
    """The commits each of the worker runs `run_ids` went from and to, and their size, by repository, in one read.

    Returns:
        Each run's ranges; a run that recorded none is not in it.
    """
    return {run_id: [run_range(r) for r in rows] for run_id, rows in run_changes.of_runs(conn, run_ids).items()}


def run_range(row: records.RunChange) -> RunRange:
    """Return one repository's range and size, as the run's end recorded them."""
    return RunRange(
        repo=row.repo,
        start_sha=row.start_sha,
        start_on_base=row.start_on_base,
        end_sha=row.end_sha,
        unpushed_sha=row.unpushed_sha,
        files_changed=row.files_changed,
        lines_added=row.lines_added,
        lines_removed=row.lines_removed,
    )
