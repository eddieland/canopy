"""What a worker's or a task's run changed, per repository, as the harness read it when the run ended (DESIGN §45).

`runs.changes` reads each slot as the run ends, after its push and before a flaky kick (§8 step 5): the commit the run
started from, the commit it left on origin, and the merge base with its base, and keeps two diffs beside the run's
log, as a review keeps its one: the run's own change (`change_path`) and the branch against its base
(`review_diff.run_path_for`, with the commit it was taken at beside it). It counts the run's own change's lines too,
per file, so a page names its size without reading a diff, and logs the commits in the range, with canopy's marks on
each and whether the harness's own push put it on origin. This records them, a row per repository, one per file
counted, and one per commit, in the transaction that closes the run, and reads them back. The commits are the harness's
own reads, never the agent's word; the diffs, the paths counted, and the commits' subjects are the branch's text,
untrusted, the diffs read back within `review_diff`'s bounds. The rows are never removed: the files go with the run's
others after `run_files_days` (§26).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, LiteralString, assert_never

from canopy.core import records, review_diff

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Collection, Iterable, Sequence

#: Why a run that crashed keeps nothing: no git runs in a slot whose links may point at a git directory the worker made
#: (§8 step 5), and a setup failure or a signal ends the run before its slot is read.
CRASHED = "the run crashed, so canopy read nothing of its slot and kept no diff"
#: The most commits of a repository's range a run records, the newest: far more than a run makes, and the count names
#: the rest.
MAX_COMMITS = 100
#: The tables of the runs that record what they changed: a worker's, and a one-off task's (DESIGN §36).
type RunTable = Literal["runs", "task_runs"]


@dataclass(frozen=True)
class Counted:
    """How much a run's own change touched in one repository, as `git diff --numstat` counted it."""

    #: The files, in git's order, at most a review diff's many (`review_diff.MAX_FILES`).
    files: Sequence[review_diff.Count]
    #: How many files it touched, those past the bound included.
    files_changed: int
    #: The lines it added, a binary file's counting none.
    lines_added: int
    #: The lines it removed.
    lines_removed: int


def counted(found: Sequence[review_diff.Count]) -> Counted:
    """Total what git counted of each file, keeping the files a review diff would.

    Returns:
        The files within the bound, and the totals over every one.
    """
    return Counted(
        files=tuple(found[: review_diff.MAX_FILES]),
        files_changed=len(found),
        lines_added=sum(c.added or 0 for c in found),
        lines_removed=sum(c.removed or 0 for c in found),
    )


@dataclass(frozen=True)
class Commit:
    """One commit in a run's range, as git logged it, with canopy's marks on it (TRUST_MODEL T5)."""

    sha: str
    #: Its subject, the branch's text, cut, every hidden character named.
    subject: str
    #: Whether it carries every trailer canopy's hooks add; None when the run's marks named none.
    canopy_trailer: bool | None = None
    #: Whether its subject starts with canopy's prefix, or is a fixup's; None when the run's marks named none.
    prefixed: bool | None = None
    #: Whether it carries a `Co-authored-by` trailer not canopy's, as the runtime's own attribution is.
    runtime_trailer: bool = False
    #: Whether the harness's own push after the worker, not the worker, put it on origin.
    harness_pushed: bool = False


@dataclass(frozen=True)
class Change:
    """One repository's range and kept diffs, as a run's end read them: what its row records."""

    repo: str
    #: The commit the run started from: origin's branch then, or the base's commit when origin had none; None when no
    #: git ran in the slot.
    start: str | None
    #: Whether `start` is the base's commit, origin having had no branch.
    start_on_base: bool = False
    #: The commit the run left on origin's branch, before any kick; None when origin has no branch.
    end: str | None = None
    #: Where the diffed commit leaves the base, as the slot last fetched it.
    merge_base: str | None = None
    #: For a slot the run left unpushed, the last commit the run made there, whose diffs are of work not on origin.
    unpushed: str | None = None
    #: Whether the run's own change was kept, at `change_path`.
    change_kept: bool = False
    #: Whether the branch against its base was kept, at `review_diff.run_path_for`.
    branch_kept: bool = False
    #: Why a diff was not kept; None when both were.
    missing: str | None = None
    #: How much the run's own change touched; None when canopy counted nothing.
    counted: Counted | None = None
    #: The commits in the range, oldest first, at most the newest `MAX_COMMITS`.
    commits: Sequence[Commit] = ()
    #: How many commits the range held, those past the bound included; None when canopy read none.
    commit_count: int | None = None


def crashed(repos: Iterable[str]) -> tuple[Change, ...]:
    """What a run that crashed records of each of its repositories: no commits, and why nothing was kept.

    Returns:
        A change per repository, each saying the run kept nothing.
    """
    return tuple(Change(repo, None, missing=CRASHED) for repo in repos)


def change_path(log_path: str | Path, repo: str) -> Path:
    """Where a run keeps the diff of its own change to `repo`: from the commit it started from to the one it left.

    Returns:
        `<id>.<repo>.change.diff` beside `log_path`. The file may not exist.
    """
    log = Path(log_path)
    return log.with_name(f"{log.stem}.{repo}.change.diff")


def files(log_path: str | Path, repos: Iterable[str]) -> list[Path]:
    """The files a run keeps of what it changed in `repos`: each one's own change, its branch, and that diff's head.

    Returns:
        The paths, three per repository; any may not exist.
    """
    found: list[Path] = []
    for repo in repos:
        branch = review_diff.run_path_for(log_path, repo)
        found.extend((change_path(log_path, repo), branch, branch.with_suffix(".head")))
    return found


def record(conn: sqlite3.Connection, run_id: int, changes: Iterable[Change], *, table: RunTable = "runs") -> None:
    """Record what run `run_id` of `table` changed, a row per repository and one per file counted.

    In the transaction that closes it.
    """
    changes = tuple(changes)
    rows = [
        (
            run_id,
            c.repo,
            c.start,
            c.start_on_base,
            c.end,
            c.merge_base,
            c.unpushed,
            c.change_kept,
            c.branch_kept,
            c.missing,
            c.counted.files_changed if c.counted is not None else None,
            c.counted.lines_added if c.counted is not None else None,
            c.counted.lines_removed if c.counted is not None else None,
            c.commit_count,
        )
        for c in changes
    ]
    if not rows:
        return
    columns: list[LiteralString] = [
        _column(table),
        "repo",
        "start_sha",
        "start_on_base",
        "end_sha",
        "merge_base_sha",
        "unpushed_sha",
        "change_kept",
        "branch_kept",
        "missing",
        "files_changed",
        "lines_added",
        "lines_removed",
        "commit_count",
    ]
    records.insert_rows(records.RunChange, columns).many(conn, rows)
    files = [
        (run_id, c.repo, f.path, f.old_path, f.added, f.removed)
        for c in changes
        if c.counted is not None
        for f in c.counted.files
    ]
    if files:
        file_columns: list[LiteralString] = [_column(table), "repo", "path", "old_path", "added", "removed"]
        records.insert_rows(records.RunChangeFile, file_columns).many(conn, files)
    commits = [
        (
            run_id,
            c.repo,
            position,
            commit.sha,
            commit.subject,
            commit.canopy_trailer,
            commit.prefixed,
            commit.runtime_trailer,
            commit.harness_pushed,
        )
        for c in changes
        for position, commit in enumerate(c.commits)
    ]
    if commits:
        commit_columns: list[LiteralString] = [
            _column(table),
            "repo",
            "position",
            "sha",
            "subject",
            "canopy_trailer",
            "prefixed",
            "runtime_trailer",
            "harness_pushed",
        ]
        records.insert_rows(records.RunCommit, commit_columns).many(conn, commits)


def of_run(conn: sqlite3.Connection, run_id: int, *, table: RunTable = "runs") -> list[records.RunChange]:
    """Return what run `run_id` of `table` changed, by repository.

    Returns:
        A row per repository the run recorded; none for a run that recorded none, as one reconcile closed.
    """
    query = records.select(records.RunChange)
    match table:
        case "runs":
            query = query.where("run_id = ?", run_id)
        case "task_runs":
            query = query.where("task_run_id = ?", run_id)
        case _:
            assert_never(table)
    return query.order_by("repo").all(conn)


def files_of(
    conn: sqlite3.Connection,
    run_id: int,
    repo: str,
    *,
    table: RunTable = "runs",
) -> list[records.RunChangeFile]:
    """Return the files run `run_id` of `table` changed in `repo`, as git counted them.

    Returns:
        A row per file counted, in git's order; none for a repository canopy counted nothing of.
    """
    query = records.select(records.RunChangeFile).where("repo = ?", repo)
    match table:
        case "runs":
            query = query.where("run_id = ?", run_id)
        case "task_runs":
            query = query.where("task_run_id = ?", run_id)
        case _:
            assert_never(table)
    # Inserted in git's order, so the rowid keeps it.
    return query.order_by("rowid").all(conn)


def commits_of(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    table: RunTable = "runs",
) -> dict[str, list[records.RunCommit]]:
    """Return the commits run `run_id` of `table` recorded in its range, by repository.

    Returns:
        Each repository's commits, oldest first; a repository with none recorded is not in it.
    """
    query = records.select(records.RunCommit)
    match table:
        case "runs":
            query = query.where("run_id = ?", run_id)
        case "task_runs":
            query = query.where("task_run_id = ?", run_id)
        case _:
            assert_never(table)
    found: dict[str, list[records.RunCommit]] = {}
    for row in query.order_by("repo, position").all(conn):
        found.setdefault(row.repo, []).append(row)
    return found


def commits_of_runs(
    conn: sqlite3.Connection,
    run_ids: Collection[int],
    repo: str,
) -> dict[int, list[records.RunCommit]]:
    """Return the commits each of the worker runs `run_ids` recorded in `repo`, in one read.

    Returns:
        Each run's commits, oldest first; a run with none recorded there is not in it.
    """
    found: dict[int, list[records.RunCommit]] = {}
    if not run_ids:
        return found
    query = records.select(records.RunCommit).where_in("run_id", run_ids).where("repo = ?", repo)
    for row in query.order_by("run_id, position").all(conn):
        if row.run_id is not None:
            found.setdefault(row.run_id, []).append(row)
    return found


def of_runs(conn: sqlite3.Connection, run_ids: Collection[int]) -> dict[int, list[records.RunChange]]:
    """Return what each of the worker runs `run_ids` changed, by repository, in one read.

    Returns:
        Each run's rows, as `of_run` reads them; a run that recorded none is not in it.
    """
    found: dict[int, list[records.RunChange]] = {}
    if not run_ids:
        return found
    for row in records.select(records.RunChange).where_in("run_id", run_ids).order_by("repo").all(conn):
        if row.run_id is not None:
            found.setdefault(row.run_id, []).append(row)
    return found


def _column(table: RunTable) -> Literal["run_id", "task_run_id"]:
    match table:
        case "runs":
            return "run_id"
        case "task_runs":
            return "task_run_id"
        case _:
            assert_never(table)
