"""The checkpoint in a run's slot (DESIGN §8): its branch checked out detached, and its push verified after the agent.

A worker's run (`worker.py`) and a task's (`task_run.py`) share them. Every git step runs through the runner with the
harness's flags (D107), and no step makes a local branch (D109): the pushed branch is the checkpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import commit_hooks, hostgit
from canopy.core.config import AUTOSQUASH
from canopy.infra import procs

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from canopy.infra import logs

_GIT_TIMEOUT_SECONDS = 300
# The most commits a note names that lack one of canopy's marks; it counts the rest.
_MAX_NAMED = 5


class SetupError(Exception):
    """A git step before or after the agent failed, or something else the run needed before its agent started."""


@dataclass(frozen=True)
class Start:
    """Where a run's slot started: HEAD's commit, how many entries HEAD's reflog then had, and origin's branch.

    `pushed` is the commit the branch held on origin when the run started, or "" if origin did not have it.
    """

    commit: str
    moves: int
    pushed: str


class Git:
    """git in one slot, through the runner. `name` is the slot's repository, for errors, or "" to leave it unnamed."""

    def __init__(self, runner: procs.Runner, slot: Path, name: str = "", env: Mapping[str, str] = hostgit.ENV) -> None:
        """Run git in `slot` through `runner`, with `env`, naming the repository `name` in what it raises."""
        self.runner = runner
        self.slot = slot
        self.name = name
        self.where = f"{name}: " if name else ""
        self.env = env
        # Whether git here reads the run's object directory, and so must write no shared ref (DESIGN §8).
        self.reads_run = "GIT_OBJECT_DIRECTORY" in env

    def result(self, *args: str) -> procs.Result:
        """Run `git <args>` and return how it went, whatever its exit code.

        Returns:
            git's result.

        Raises:
            SetupError: git could not start, or timed out.
        """
        try:
            result = self.runner.run(hostgit.argv(*args), cwd=self.slot, env=self.env, timeout=_GIT_TIMEOUT_SECONDS)
        except procs.ProcError as e:
            raise SetupError(f"{self.where}git {args[0]}: {e}") from e
        if result.timed_out:
            raise SetupError(f"{self.where}git {args[0]} timed out")
        return result

    def ok(self, *args: str) -> bool:
        """Run `git <args>`.

        Returns:
            Whether it exited 0.
        """
        return self.result(*args).ok

    def run(self, *args: str) -> str:
        """Run `git <args>`, which must succeed.

        Returns:
            Its stdout, stripped.

        Raises:
            SetupError: git exited non-zero.
        """
        result = self.result(*args)
        if not result.ok:
            detail = (result.stderr.strip() or result.stdout.strip())[:500]
            raise SetupError(f"{self.where}git {args[0]} exited {result.returncode}: {detail}")
        return result.stdout.strip()


def check_out(git: Git, base: str, branch: str = "") -> Start:
    """Check out `base` from origin, detached, or `branch` from origin if it is given and there.

    A plan reads its base and creates no branch. A worker run passes its branch, which it continues if it was pushed,
    and so does a task's. No run makes a local branch: every slot of a pool shares the repository's branch refs, so one
    would be state other slots see. The agent pushes `HEAD` to the branch by refspec (DESIGN §8, D109).

    Returns:
        HEAD's commit after the checkout, and how many entries HEAD's reflog then had.

    Raises:
        SetupError: a git step failed, or the base branch is not on origin.
    """
    # --prune: a slot keeps remote-tracking refs from earlier runs, which would hide a branch since deleted on origin.
    git.run("fetch", "--quiet", "--prune", "origin")
    # Checked even when the branch is continued: the worker's prompt targets the PR at the base. A stacked run's base
    # is another ticket's branch, deleted when its PR merged (DESIGN §10).
    if not git.ok("rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{base}"):
        hint = "; if it was stacked on, its PR may have merged" if branch else ""
        raise SetupError(f"{git.where}the base branch {base} is not on origin{hint}")
    target = base
    if branch and git.ok("rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"):
        target = branch
    git.run("checkout", "--quiet", "--detach", f"refs/remotes/origin/{target}")
    if branch:
        _drop_local_branch(git, branch, target)
    commit = git.run("rev-parse", "HEAD")
    return Start(commit, len(_head_log(git)), commit if target == branch else "")


def ensure_pushed(git: Git, branch: str, start: Start, log: logs.TickAdapter, *, rebase: bool) -> str:
    """Check the checkpoint invariant: the branch on origin is the slot's HEAD. Push HEAD to it once if it is not.

    Detached, HEAD is the only thing holding the agent's commits, so an agent that moved it off them leaves them
    behind: that is unpushed too. With `rebase` (`trust.rebase`), the push may replace the branch, but only if origin
    still has it where the run started: a worker that rebased and did not push loses nothing anyone else pushed. A
    task's run passes it False whatever `trust.rebase` says (DESIGN §36): its push only ever adds commits.

    Returns:
        Why the work is not pushed, or "" if it is, or if the agent committed nothing.
    """
    local = git.run("rev-parse", "HEAD")
    remote = remote_head(git, branch)
    # A HEAD that holds nothing past the start is no work of the agent's; whatever is on origin is its doing.
    if remote != local and not git.ok("merge-base", "--is-ancestor", local, start.commit):
        log.warning("worker left commits unpushed; pushing once", extra={"branch": branch, "repo": git.name})
        pushed = _push(git, branch, start.pushed if rebase else None)
        remote = remote_head(git, branch)
        if not pushed.ok or remote != local:
            detail = (pushed.stderr.strip() or pushed.stdout.strip())[:500]
            return f"{git.where}commits on {branch} are not on origin; the push failed: {detail}"
    left = _left_behind(git, branch, start, remote)
    if left:
        return (
            f"{git.where}the worker moved HEAD off {len(left)} commit(s) not on origin, such as {left[0][:12]}; "
            "nothing was pushed for them"
        )
    return ""


def remote_head(git: Git, branch: str) -> str:
    """Return the commit `branch` is at on origin, as origin says now.

    Returns:
        The commit's full hash, or "" when origin has no such branch.
    """
    listed = git.run("ls-remote", "origin", f"refs/heads/{branch}")
    return listed.split()[0] if listed else ""


def unmarked(git: Git, branch: str, start: Start, base: str, marks: commit_hooks.Marks) -> list[str]:
    """Return a harness note for each of `marks` that a run's commit on origin's `branch` lacks, naming those commits.

    The run's commits are those the branch holds that neither HEAD at the start nor origin's `base` does. canopy's
    hooks put the marks on them (`commit_hooks`, TRUST_MODEL T5); a commit made around them is reported, never
    rewritten. A fixup, which keeps its subject for `--autosquash`, needs no prefix. Best effort: a git step that fails
    reports nothing.

    Returns:
        A note for the trailers and one for the prefix, each only when a commit lacks it.

    Raises:
        SetupError: git could not start, or timed out.
    """
    remote = remote_head(git, branch) if marks.trailers or marks.prefix else ""
    if not remote:
        return []
    # Unfolded and joined, each commit's subject and trailers fit on its line.
    listed = git.result(
        "log",
        "--format=%h%x1f%s%x1f%(trailers:only,unfold,separator=%x1e)",
        remote,
        f"^{start.commit}",
        f"^refs/remotes/origin/{base}",
        "--",
    )
    if not listed.ok:
        return []
    untrailed: list[str] = []
    unprefixed: list[str] = []
    for line in listed.stdout.splitlines():
        commit, subject, found = [*line.split("\x1f"), "", ""][:3]
        if not set(marks.trailers) <= set(found.split("\x1e")):
            untrailed.append(commit)
        if marks.prefix and not subject.startswith((marks.prefix, *AUTOSQUASH)):
            unprefixed.append(commit)
    notes = [(untrailed, "canopy's trailer"), (unprefixed, f"the prefix `{marks.prefix}`")]
    return [f"{git.where}{_lacking(commits, branch, what)}" for commits, what in notes if commits]


def _lacking(commits: Sequence[str], branch: str, what: str) -> str:
    named = ", ".join(commits[:_MAX_NAMED])
    more = f" and {len(commits) - _MAX_NAMED} more" if len(commits) > _MAX_NAMED else ""
    pushed = (
        f"1 commit pushed to {branch} lacks" if len(commits) == 1 else f"{len(commits)} commits pushed to {branch} lack"
    )
    return f"{pushed} {what}: {named}{more}"


def ignore(git: Git, name: str) -> None:
    """Have git ignore `name` at a worktree's root in every slot of the repository, so `git add -A` leaves it out.

    The line goes in the repository's exclude file, which every slot shares, once. A file canopy writes into a slot
    for one run, a plan's copy (DESIGN §25) or a task's report (§36), is ignored so.

    Raises:
        SetupError: git could not name the repository's git directory, or the exclude file could not be written.
    """
    common = Path(git.run("rev-parse", "--path-format=absolute", "--git-common-dir"))
    exclude = common / "info" / "exclude"
    line = f"/{name}"
    try:
        held = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
        if line not in held.splitlines():
            exclude.parent.mkdir(parents=True, exist_ok=True)
            with exclude.open("a", encoding="utf-8") as f:
                f.write(f"{'' if not held or held.endswith(chr(10)) else chr(10)}{line}\n")
    except OSError as e:
        raise SetupError(f"{git.where}could not have git ignore {name}: {e}") from e


def _drop_local_branch(git: Git, branch: str, target: str) -> None:
    """Delete a local `branch` an earlier canopy's `checkout -B` left in the pool's repository, if origin has it all.

    A worker that made the branch again would fail, or fall back to the stale one. One with commits origin lacks is
    kept: they may be the only copy.
    """
    ref = f"refs/heads/{branch}"
    if git.ok("rev-parse", "--verify", "--quiet", ref) and git.ok(
        "merge-base",
        "--is-ancestor",
        ref,
        f"refs/remotes/origin/{target}",
    ):
        git.result("branch", "--quiet", "--delete", "--force", branch)  # refused if a worktree has it checked out


def _head_log(git: Git) -> list[str]:
    """The commits in the slot's HEAD reflog, newest first, or none if it has no reflog.

    Returns:
        The commits' full hashes, one per reflog entry.
    """
    found = git.result("log", "--walk-reflogs", "--format=%H", "HEAD")
    return found.stdout.split() if found.ok else []


def _push(git: Git, branch: str, lease: str | None) -> procs.Result:
    """Push HEAD to `branch` on origin, and leave the shared refs as they were if git reads the run's objects.

    With a `lease`, the push may replace the branch, if origin has it at that commit, or does not have it when the
    lease is "". Without one, it only adds commits.

    A push also moves origin's remote-tracking ref, which every slot of the pool shares. Pointed at a commit only the
    run's object directory holds, it would break git in every slot, and in the primary clone, once that directory goes
    (DESIGN §8). The next fetch moves it, from origin's own objects.

    Returns:
        The push's result, whether or not it succeeded.
    """
    tracking = f"refs/remotes/origin/{branch}"
    before = git.result("rev-parse", "--verify", "--quiet", tracking).stdout.strip() if git.reads_run else ""
    force = () if lease is None else (f"--force-with-lease=refs/heads/{branch}:{lease}",)
    pushed = git.result("push", "--quiet", *force, "origin", f"HEAD:refs/heads/{branch}")
    if git.reads_run and before:
        git.result("update-ref", tracking, before)
    elif git.reads_run:
        git.result("update-ref", "-d", tracking)
    return pushed


def _left_behind(git: Git, branch: str, start: Start, remote: str) -> list[str]:
    """Commits HEAD held during the run whose changes neither HEAD nor origin holds.

    That is commits that neither HEAD, origin's `branch` now or when the run started, nor any of origin's branches
    holds, less those whose own change origin's `branch` already has (`_on_origin`). A worker that rebased, could not
    push the copies, and pushed the same work another way left nothing behind; one that rebased and pushed with a lease
    (`trust.rebase`) replaced the commits origin had, which were pushed before the run.

    Read from HEAD's reflog, the slot's own, so a worker that cleared it hides what it left; this catches a worker that
    checked something else out, not one that tried to hide its work.

    Returns:
        The commits left behind, none if HEAD did not move during the run.
    """
    entries = _head_log(git)
    held = list(dict.fromkeys(entries[: max(0, len(entries) - start.moves)]))
    if not held:
        return []
    keep = ["HEAD", start.pushed] if start.pushed else ["HEAD"]
    if remote and not git.ok("cat-file", "-e", f"{remote}^{{commit}}"):
        # --refmap=: no remote-tracking ref moves, only the slot's own FETCH_HEAD, which tidying drops.
        git.result("fetch", "--quiet", "--refmap=", "origin", f"refs/heads/{branch}")
    if not (remote and git.ok("cat-file", "-e", f"{remote}^{{commit}}")):
        return git.run("rev-list", *held, "--not", *keep, "--remotes=origin").split()
    left = git.run("rev-list", *held, "--not", *keep, remote, "--remotes=origin").split()
    tree = git.run("rev-parse", f"{remote}^{{tree}}")
    return [commit for commit in left if not _on_origin(git, commit, remote, tree)]


def _on_origin(git: Git, commit: str, remote: str, tree: str) -> bool:
    """Whether `remote`, with tree `tree`, already has `commit`'s own change: applying it there changes nothing.

    A rebased copy of a commit origin has, or a commit whose change went up in another one, is not lost. It is a
    three-way merge of `commit` into `remote` on `commit`'s first parent, so a change made again by hand counts too, and
    a change origin has only in part does not. A root commit counts as not on origin, and so does every commit under
    git older than 2.40, which lacks `--merge-base`.

    Returns:
        True if the merge is clean and leaves `remote`'s tree as it is.
    """
    if not git.ok("rev-parse", "--verify", "--quiet", f"{commit}^"):
        return False
    merged = git.result("merge-tree", "--write-tree", f"--merge-base={commit}^", remote, commit)
    return merged.ok and merged.stdout.split()[:1] == [tree]
