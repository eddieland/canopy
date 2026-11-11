"""Reading what a worker's or a task's run changed in each of its slots as it ends, and keeping the diffs (DESIGN §45).

After the push check (`checkpoint.ensure_pushed`) and before a flaky kick rewrites the branch (§8 step 5, §23), `keep`
reads one slot: the commit the branch is at on origin as the push check read it, not again, since someone else may
have moved it since, and for a slot left unpushed the last commit the run made there (`checkpoint.left_work`), and the
merge base of the one it diffs with the base as the slot last fetched it. It keeps two diffs beside the run's log: the
run's own change, from the commit it started from, and the branch against its base, with the commit it was taken at;
and it counts each file's lines in the run's own change, which a run's page and its ticket's runs list name. It logs
the commits in the run's range too, bounded, each with canopy's marks on it (TRUST_MODEL T5) and whether the push
check's own push, not the worker, put it on origin, so who put what on a branch can be told after a kick rewrites it.
Each is kept then or never: the slot is returned, a kick may rewrite the branch, and the run's objects are deleted with
it.

Every read is of commits the slot already holds, by the harness's git with hooks, drivers, and textconv off (D107):
nothing here fetches, pushes, or moves a ref. Best effort throughout, as a kept diff is: the run needs none of it, so a
failure is logged and named in what the run records, and never ends the run otherwise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from canopy.core import review_diff, run_changes
from canopy.core.config import AUTOSQUASH
from canopy.core.memory_text import visible
from canopy.core.vocab import RunKind
from canopy.runs import checkpoint

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.core import commit_hooks
    from canopy.infra import logs

#: The kinds of worker run that record what they changed: those that work on the ticket's branch. A plan pushes none.
RECORDED: frozenset[str] = frozenset({RunKind.IMPLEMENT, RunKind.FIX_CI, RunKind.RESUME})
#: How much of what git said a reason a diff was not kept holds.
_MAX_REASON = 300
#: How much of a commit's subject a run records, every hidden character named: a page or a terminal line's worth.
MAX_SUBJECT = 200
#: How much of `git log`'s output the commits are read from: far more than `run_changes.MAX_COMMITS` subjects and
#: their trailers fill. A commit cut off at the end is not recorded.
_MAX_LOG_CHARS = 512 * 1024
#: One piece of a subject with its hidden characters named: a name, `<U+200B>`, or any other character.
_NAMED_RE = re.compile(r"<U\+[0-9A-F]{4,6}>|.", re.DOTALL)
#: The trailer key of a co-author, as git matches it, ignoring case.
_CO_AUTHOR = "co-authored-by"


def keep(
    git: checkpoint.Git,
    *,
    repo: str,
    base: str,
    branch: str,
    start: checkpoint.Start,
    pushed: checkpoint.Pushed,
    marks: commit_hooks.Marks,
    log_path: str | Path,
    log: logs.TickAdapter,
) -> run_changes.Change:
    """Read what the run changed in the slot `git` runs in, and keep its two diffs beside the run's log, `log_path`.

    `pushed` is what the push check found: where origin's branch was, the run's end, and whether the slot's work is
    there; a slot whose work is not keeps the diffs of the last commit the run made there, as work not on origin.
    `marks` are what canopy's hooks put on the run's commits, which each commit is read for.

    Returns:
        The slot's range, its commits, which diffs were kept, and why one was not.
    """
    fields = {"repo": repo, "branch": branch}
    found = run_changes.Change(repo, start.commit, start_on_base=not start.pushed, end=pushed.head or None)
    try:
        unpushed = checkpoint.left_work(git, branch, start, pushed) if pushed.unpushed else None
    except checkpoint.SetupError as e:
        log.warning("run's change not read", extra={**fields, "error": str(e)})
        return replace(found, missing=f"canopy could not read what the run left unpushed: {_cut(str(e))}")
    found = replace(found, unpushed=unpushed)
    head = unpushed or found.end
    if head is None:
        return replace(found, missing="the run left no branch on origin and no commit of its own in its slot")
    change = _keep(git, start.commit, head, run_changes.change_path(log_path, repo))
    if change is not None:
        log.warning("run's change not kept", extra={**fields, "error": change})
    counted = _count(git, start.commit, head)
    if isinstance(counted, str):
        log.warning("run's change not counted", extra={**fields, "error": counted})
    try:
        logged = _commits(git, Range(start.commit, head, base), marks, pushed)
    except checkpoint.SetupError as e:
        log.warning("run's commits not read", extra={**fields, "error": str(e)})
        logged = None
    try:
        fork = _merge_base(git, base, head)
    except checkpoint.SetupError as e:
        fork, against = None, _cut(str(e))
    else:
        against = _keep(git, fork, head, review_diff.run_path_for(log_path, repo), at=head)
    if against is not None:
        log.warning("run's branch against its base not kept", extra={**fields, "base": base, "error": against})
    missing = [
        *([f"its own change: {change}"] if change is not None else []),
        *([f"the branch against {base}: {against}"] if against is not None else []),
    ]
    return replace(
        found,
        merge_base=fork,
        change_kept=change is None,
        branch_kept=against is None,
        missing="; ".join(missing) or None,
        counted=counted if not isinstance(counted, str) else None,
        commits=logged[0] if logged is not None else (),
        commit_count=logged[1] if logged is not None else None,
    )


def recorded(kind: str) -> bool:
    """Return whether a worker run of `kind` records what it changed: one that works on the ticket's branch.

    Returns:
        True for an `implement`, a `fix-ci`, or a `resume`.
    """
    return kind in RECORDED


@dataclass(frozen=True)
class Range:
    """The commits a run's slot holds of its work: those `head` holds that neither `start` nor origin's `base` does."""

    #: The commit the run started from.
    start: str
    #: The commit its diff is of: the one it left on origin, or the last it left unpushed.
    head: str
    #: The base branch, as the slot last fetched it.
    base: str

    def args(self) -> tuple[str, ...]:
        """Return git's revisions for the range, ended by `--` so none is read as a path.

        Returns:
            `head`, then `start` and the base's remote-tracking ref, each excluded.
        """
        return (self.head, f"^{self.start}", f"^refs/remotes/origin/{self.base}", "--")


def _commits(
    git: checkpoint.Git,
    commits: Range,
    marks: commit_hooks.Marks,
    pushed: checkpoint.Pushed,
) -> tuple[tuple[run_changes.Commit, ...], int]:
    """Log the commits in the run's range, the newest `run_changes.MAX_COMMITS`, oldest first, with their marks.

    Each commit is read for canopy's trailers and prefix (`marks`, TRUST_MODEL T5), a fixup counting as prefixed as
    `checkpoint.unmarked` counts it, for a co-author trailer not canopy's, and for whether the push check's own push
    put it on origin: a commit past where origin's branch was before that push (`pushed.harness_from`).

    Returns:
        The commits, and how many the range held, those past the bound included.

    Raises:
        SetupError: git could not start, timed out, or failed.
    """
    count = int(git.run("rev-list", "--count", *commits.args()) or "0")
    listed = git.result(
        "log",
        "--topo-order",
        "-z",
        f"--max-count={run_changes.MAX_COMMITS}",
        "--format=%H%x00%s%x00%(trailers:only,unfold)",
        *commits.args(),
        max_stdout=_MAX_LOG_CHARS,
    )
    if not listed.ok:
        raise checkpoint.SetupError(f"git log exited {listed.returncode}: {_cut(listed.stderr.strip())}")
    fields = listed.stdout.split("\0")
    # Each commit is three fields, ended by a NUL; one cut off at the bound is not recorded.
    whole = len(fields) // 3 * 3 if listed.stdout.endswith("\0") else (len(fields) - 1) // 3 * 3
    harness = _harness_pushed(git, commits, pushed)
    found = [
        _commit(sha, subject, trailers, marks, harness=sha in harness)
        for sha, subject, trailers in zip(fields[0:whole:3], fields[1:whole:3], fields[2:whole:3], strict=True)
    ]
    return tuple(reversed(found)), count


def _harness_pushed(git: checkpoint.Git, commits: Range, pushed: checkpoint.Pushed) -> frozenset[str]:
    """Return the commits of the range the push check's own push put on origin: none when it pushed nothing.

    Returns:
        Their full hashes.

    Raises:
        SetupError: git could not start, timed out, or failed.
    """
    if pushed.harness_from is None or not pushed.head:
        return frozenset()
    since = (f"^{pushed.harness_from}",) if pushed.harness_from else ()
    return frozenset(git.run("rev-list", pushed.head, *since, *commits.args()[1:]).split())


def _commit(sha: str, subject: str, trailers: str, marks: commit_hooks.Marks, *, harness: bool) -> run_changes.Commit:
    """Return one logged commit: its subject cut and named, and canopy's marks on it read from its trailers.

    Returns:
        The commit as a run records it.
    """
    lines = [line.strip() for line in trailers.split("\n") if line.strip()]
    return run_changes.Commit(
        sha.strip(),
        _cut_named(visible(subject)),
        canopy_trailer=set(marks.trailers) <= set(lines) if marks.trailers else None,
        prefixed=subject.startswith((marks.prefix, *AUTOSQUASH)) if marks.prefix else None,
        runtime_trailer=any(
            line.split(":", 1)[0].strip().casefold() == _CO_AUTHOR and line not in marks.trailers for line in lines
        ),
        harness_pushed=harness,
    )


def _cut_named(named: str) -> str:
    """Return a subject, its hidden characters named, cut to `MAX_SUBJECT` between characters, never inside a name.

    Returns:
        `named` whole when it fits, else as many of its characters and names as fit, then "...".
    """
    if len(named) <= MAX_SUBJECT:
        return named
    kept = ""
    for piece in _NAMED_RE.findall(named):
        if len(kept) + len(piece) > MAX_SUBJECT - 3:
            break
        kept += piece
    return kept + "..."


def _merge_base(git: checkpoint.Git, base: str, head: str) -> str:
    """Return where `head` leaves `base`, as the slot last fetched it.

    Returns:
        The merge base's full hash.

    Raises:
        SetupError: git found none, or could not look: what it said, so the record names the real failure.
    """
    found = git.result("merge-base", f"refs/remotes/origin/{base}", head)
    fork = found.stdout.strip()
    if found.ok and fork:
        return fork
    said = found.stderr.strip()
    # git says nothing and exits 1 when the two share no history; anything else is a failure to look.
    if found.returncode == 1 and not said:
        raise checkpoint.SetupError(f"no merge base of {head[:12]} with {base} in its slot")
    raise checkpoint.SetupError(f"git merge-base exited {found.returncode}: {said or fork}")


def _keep(git: checkpoint.Git, fork: str, head: str, path: Path, *, at: str | None = None) -> str | None:
    """Keep the diff of `head` against `fork` at `path`, and the commit it was taken at, `at`, beside it when given.

    The commit is written before the diff, so a diff is never kept without it. git's output is read no further than
    the bound `review_diff.keep` writes, so a diff of any size costs canopy no more than that.

    Returns:
        Why it was not kept, or None once it was.
    """
    try:
        diff = git.result(*review_diff.diff_args(fork, head), max_stdout=review_diff.KEPT_CHARS)
        if not diff.ok:
            return _cut(f"git diff exited {diff.returncode}: {diff.stderr.strip() or diff.stdout.strip()}")
        if at is not None:
            review_diff.keep_head(path, at)
        review_diff.keep(path, diff.stdout)
    except (checkpoint.SetupError, OSError) as e:
        return _cut(str(e))
    return None


def _count(git: checkpoint.Git, fork: str, head: str) -> run_changes.Counted | str:
    """Count each file's lines in the diff of `head` against `fork`, as git's `--numstat` does.

    Read no further than a kept diff is: a change whose count runs past that is not counted, rather than counted short.

    Returns:
        The count, or why there is none.
    """
    try:
        found = git.result(*review_diff.numstat_args(fork, head), max_stdout=review_diff.KEPT_CHARS)
    except checkpoint.SetupError as e:
        return _cut(str(e))
    if not found.ok:
        return _cut(f"git diff --numstat exited {found.returncode}: {found.stderr.strip()}")
    if len(found.stdout) >= review_diff.KEPT_CHARS:
        return "git's count ran past what canopy reads"
    return run_changes.counted(review_diff.counts(found.stdout))


def _cut(text: str) -> str:
    """Return `text` on one line, cut to `_MAX_REASON`."""
    line = " ".join(text.split())
    return line if len(line) <= _MAX_REASON else line[: _MAX_REASON - 3] + "..."
