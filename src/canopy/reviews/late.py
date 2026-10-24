"""Late findings (DESIGN §21, Answers and rebuttals): a later review's findings on code its PR's first review read.

A review of one of the loop's own PRs, at a commit after the PR's first reviewed one, may find a defect in code that
was there at that first review and is there unchanged: one the first review could have found. A finding of the loop's
own PR starts a `resume`, so a reviewer that finds a few more of those each round keeps the author and the reviewer
going until the per-PR limit. `late` names such findings, for `execute` to hold for the operator as the run closes.

A finding is late when its `location` names a file and a line of it at the reviewed commit, or a range of lines, none
of them one `git diff -U0` of the first reviewed commit and this one adds, and the finding is not `blocking`. Anything
else is not late, so the finding goes to a worker as before: a location with no line, a file absent at this commit,
binary, or added since, a line past its end, a diff git could not take or that a bound cut, or a first commit the
checkout cannot fetch. The path is read in the review's own checkout, the PR's repository: a joint run's PRs are
reviewed one by one, each in its own repository, so a path into another of them is a file absent here. The path is the
reviewer's text, so git reads it as a literal path, never a pattern.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import hostgit, review_diff, review_runs
from canopy.core.vocab import ReviewRunStatus
from canopy.infra import procs

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping
    from pathlib import Path

    from canopy.core import records
    from canopy.core import review_result as result
    from canopy.infra import logs

_GIT_TIMEOUT_SECONDS = 300
#: The severity never held as late: a blocking defect is worth a `resume` whenever it was written.
_NEVER_LATE = "blocking"


def late(
    conn: sqlite3.Connection,
    runner: procs.Runner,
    run: records.ReviewRun,
    stored: result.ReviewResult,
    *,
    slot: Path,
    log: logs.TickAdapter,
) -> list[int]:
    """Return the numbers of review run `run`'s findings that are late, with its commit checked out at `slot`.

    Only a review of one of the loop's own PRs has any, and only at a commit after the PR's first reviewed one.

    Returns:
        The late findings' numbers, from 1, in order; empty when none is, or when git could not say.
    """
    if run.ticket_key is None or run.revises is not None:
        return []
    wanted: dict[str, dict[int, range]] = {}
    for number, finding in enumerate(stored.findings, 1):
        at = review_diff.located(finding.location) if finding.severity != _NEVER_LATE else None
        if at is not None and at.line is not None and at.last is not None and at.line <= at.last:
            wanted.setdefault(at.path, {})[number] = range(at.line, at.last + 1)
    first = _first_reviewed(conn, run) if wanted else None
    if first is None:
        return []
    git = _Git(runner, slot, log, {"review_run_id": run.id, "since": first})
    if not git.has_commit(first):
        return []
    found: list[int] = []
    for path, lines in wanted.items():
        found.extend(_unchanged(git, path, lines, since=first, sha=run.sha))
    return sorted(found)


def _first_reviewed(conn: sqlite3.Connection, run: records.ReviewRun) -> str | None:
    """The commit of the PR's first `done` review before `run`, when it is another commit than `run`'s.

    Returns:
        Its id; None when the PR has no earlier `done` review, or its first is of this same commit.
    """
    earlier = [r for r in review_runs.review_runs_of(conn, run.pr_url) if r.id < run.id]
    first = next((r for r in reversed(earlier) if r.status is ReviewRunStatus.DONE), None)
    return first.sha if first is not None and first.sha != run.sha else None


def _unchanged(git: _Git, path: str, lines: Mapping[int, range], *, since: str, sha: str) -> list[int]:
    """Of `lines`, each finding's number with its lines in `path`, the findings on lines unchanged since `since`.

    Returns:
        Their numbers; empty when `path` is not a text file at `sha`, or git could not take its diff.
    """
    length = git.length(sha, path)
    if length is None:
        return []
    changed = git.added(since, sha, path)
    if changed is None:
        return []
    return [n for n, at in lines.items() if at.start >= 1 and at[-1] <= length and changed.isdisjoint(at)]


class _Git:
    """git over the review's checkout, each failure logged and read as "cannot say", so no finding is held for it."""

    def __init__(
        self,
        runner: procs.Runner,
        slot: Path,
        log: logs.TickAdapter,
        fields: Mapping[str, object],
    ) -> None:
        self.runner = runner
        self.slot = slot
        self.log = log
        self.fields = fields

    def has_commit(self, sha: str) -> bool:
        """Whether the checkout has commit `sha`, fetching it from origin when it does not.

        Returns:
            True once the commit is there.
        """
        if self._out("cat-file", "-e", f"{sha}^{{commit}}", quiet=True) is not None:
            return True
        return self._out("fetch", "--quiet", "origin", sha) is not None

    def length(self, sha: str, path: str) -> int | None:
        """How many lines text file `path` has at commit `sha`.

        Returns:
            The count; None when it is absent, binary, or empty there, or git could not say.
        """
        # `-I` passes over a binary file, so it counts none; '' matches every line, the last one with no newline too.
        out = self._out("grep", "--no-color", "-I", "-c", "", sha, "--", path, quiet=True)
        counted = out.splitlines() if out is not None else []
        # One line, `<sha>:<path>:<count>`, for the file itself: a directory's path counts each file under it.
        if len(counted) != 1:
            return None
        named, _, count = counted[0].rpartition(":")
        return int(count) if named == f"{sha}:{path.removeprefix('./')}" and count.isdigit() else None

    def added(self, since: str, sha: str, path: str) -> frozenset[int] | None:
        """The lines of `path` at `sha` that are not as they were at `since`: those its diff from there adds.

        Returns:
            Their numbers at `sha`; None when git could not take the diff, it shows no lines for the file, or a bound
            cut it.
        """
        args = ("diff", "--no-color", "--no-ext-diff", "--no-textconv", "--no-renames", "-U0", since, sha, "--", path)
        out = self._out(*args)
        if out is None:
            return None
        diff = review_diff.parse(out)
        if diff.truncated or any(f.binary or not f.hunks for f in diff.files):
            return None
        return frozenset(
            ln.new for f in diff.files for h in f.hunks for ln in h.lines if ln.kind == "add" and ln.new is not None
        )

    def _out(self, *args: str, quiet: bool = False) -> str | None:
        """`git <args>`'s stdout, or None when it fails: logged, unless `quiet` says a failure is an answer.

        Returns:
            git's stdout; None when it could not start or exited nonzero.
        """
        # The path is the reviewer's text: read as a literal path, never a pathspec's magic or a glob.
        argv = hostgit.argv("--literal-pathspecs", *args)
        try:
            done = self.runner.run(argv, cwd=self.slot, env=hostgit.ENV, timeout=_GIT_TIMEOUT_SECONDS)
        except procs.ProcError as e:
            self.log.warning("late findings not read", extra={**self.fields, "step": args[0], "error": str(e)})
            return None
        if not done.ok:
            if not quiet:
                error = done.stderr[:500]
                self.log.warning("late findings not read", extra={**self.fields, "step": args[0], "error": error})
            return None
        return done.stdout
