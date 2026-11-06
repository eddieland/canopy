"""Reading what a worker's or a task's run changed in each of its slots as it ends, and keeping the diffs (DESIGN §45).

After the push check (`checkpoint.ensure_pushed`) and before a flaky kick rewrites the branch (§8 step 5, §23), `keep`
reads one slot: the commit the branch is at on origin as the push check read it, not again, since someone else may
have moved it since, and for a slot left unpushed the last commit the run made there (`checkpoint.left_work`), and the
merge base of the one it diffs with the base as the slot last fetched it. It keeps two diffs beside the run's log: the
run's own change, from the commit it started from, and the branch against its base, with the commit it was taken at.
Each is kept then or never: the slot is returned, a kick may rewrite the branch, and the run's objects are deleted with
it.

Every read is of commits the slot already holds, by the harness's git with hooks, drivers, and textconv off (D107):
nothing here fetches, pushes, or moves a ref. Best effort throughout, as a kept diff is: the run needs none of it, so a
failure is logged and named in what the run records, and never ends the run otherwise.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from canopy.core import review_diff, run_changes
from canopy.core.vocab import RunKind
from canopy.runs import checkpoint

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.infra import logs

#: The kinds of worker run that record what they changed: those that work on the ticket's branch. A plan pushes none.
RECORDED: frozenset[str] = frozenset({RunKind.IMPLEMENT, RunKind.FIX_CI, RunKind.RESUME})
#: How much of what git said a reason a diff was not kept holds.
_MAX_REASON = 300


def keep(
    git: checkpoint.Git,
    *,
    repo: str,
    base: str,
    branch: str,
    start: checkpoint.Start,
    pushed: checkpoint.Pushed,
    log_path: str | Path,
    log: logs.TickAdapter,
) -> run_changes.Change:
    """Read what the run changed in the slot `git` runs in, and keep its two diffs beside the run's log, `log_path`.

    `pushed` is what the push check found: where origin's branch was, the run's end, and whether the slot's work is
    there; a slot whose work is not keeps the diffs of the last commit the run made there, as work not on origin.

    Returns:
        The slot's range, which diffs were kept, and why one was not.
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
    )


def recorded(kind: str) -> bool:
    """Return whether a worker run of `kind` records what it changed: one that works on the ticket's branch.

    Returns:
        True for an `implement`, a `fix-ci`, or a `resume`.
    """
    return kind in RECORDED


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


def _cut(text: str) -> str:
    """Return `text` on one line, cut to `_MAX_REASON`."""
    line = " ".join(text.split())
    return line if len(line) <= _MAX_REASON else line[: _MAX_REASON - 3] + "..."
