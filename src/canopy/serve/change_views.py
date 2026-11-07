"""What a worker's or a task's run changed, as its page and its ticket's runs list show it (DESIGN §45).

Each repository's range, the commits the harness read as the run ended (`run_changes`); on the run's page, with the
two diffs kept beside its log, the run's own change and the branch against its base, each read within a review's
diff's bounds (`review_diff.read`) and said to be missing, or removed by retention, when it is.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import review_diff, run_changes
from canopy.serve.diff_views import diff_view
from canopy.serve.schema import RunChange, RunRange
from canopy.serve.transcript_views import removed_after

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Collection

    from canopy.core import records
    from canopy.core.run_changes import RunTable


def run_changes_of(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    log_path: str,
    ended_at: str | None,
    table: RunTable = "runs",
) -> list[RunChange]:
    """What run `run_id` of `table` changed in each repository, with the diffs kept beside its log, `log_path`.

    `ended_at`, when the run ended, says whether retention removed a diff that is gone. A diff recorded as not kept is
    not read; one whose file is missing, a symlink, or not a regular file is no diff, never an empty one.

    Returns:
        A change per repository the run recorded, by repository; none for a run that recorded none.
    """
    found: list[RunChange] = []
    for row in run_changes.of_run(conn, run_id, table=table):
        change = run_changes.change_path(log_path, row.repo)
        branch = review_diff.run_path_for(log_path, row.repo)
        diff = review_diff.read(change) if row.change_kept else None
        branch_diff = review_diff.read(branch) if row.branch_kept else None
        # Both go with the run's other files in one pass: the first kept one says whether it went.
        kept = change if row.change_kept else branch if row.branch_kept else None
        found.append(
            RunChange(
                range=run_range(row),
                merge_base_sha=row.merge_base_sha,
                diff=diff_view(diff) if diff is not None else None,
                branch_diff=diff_view(branch_diff) if branch_diff is not None else None,
                missing=row.missing,
                removed_after_days=removed_after(conn, kept, ended_at, "run_files_days") if kept else None,
            ),
        )
    return found


def ranges_of(conn: sqlite3.Connection, run_ids: Collection[int]) -> dict[int, list[RunRange]]:
    """The commits each of the worker runs `run_ids` went from and to, by repository, in one read: no diff is read.

    Returns:
        Each run's ranges; a run that recorded none is not in it.
    """
    return {run_id: [run_range(r) for r in rows] for run_id, rows in run_changes.of_runs(conn, run_ids).items()}


def run_range(row: records.RunChange) -> RunRange:
    """Return one repository's range, as the run's end recorded it."""
    return RunRange(
        repo=row.repo,
        start_sha=row.start_sha,
        start_on_base=row.start_on_base,
        end_sha=row.end_sha,
        unpushed_sha=row.unpushed_sha,
    )
