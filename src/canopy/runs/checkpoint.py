"""A run's slot and the branch it works on (DESIGN §8, D109): the checkout, setup, push check, and the slot's return.

The pushed branch is the checkpoint (DESIGN §4): a slot is checked out detached at the branch as origin has it, or at
its base, and once the agent is done the branch on origin must be what the slot's HEAD holds, pushed once by the
harness if the agent left it unpushed. Worker runs on tickets (`worker.py`) and task runs (`task_worker.py`) share
it; each passes what its own run allows, such as whether a push may replace the branch.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from canopy.core import conversation, hostgit, pools
from canopy.core.config import setup_words
from canopy.infra import procs
from canopy.runs import tidy

if TYPE_CHECKING:
    from canopy.core import records
    from canopy.core.context import Context
    from canopy.core.vocab import PoolKind
    from canopy.infra import logs

_GIT_TIMEOUT_SECONDS = 300
#: The repository whose slot `setup_cmd` runs in, by its name in the map, and the run's branch, which the slot has
#: checked out detached (DESIGN §8).
SETUP_REPO_ENV = "CANOPY_REPO"
SETUP_BRANCH_ENV = "CANOPY_BRANCH"


class SetupError(Exception):
    """A git step before or after the worker failed."""


@dataclass(frozen=True)
class Slot:
    """One of a run's slots: the repository it is in, the worktree, its lease, git in it, and its `.git` link.

    `link` is what the worktree's `.git` file held when the run started, before any git step, or None if it is not a
    file (DESIGN §8). `pool` is the pool that made the lease, which the slot goes back to (DESIGN §18).
    """

    repo: str
    path: Path
    lease_id: str
    lease_holder: str
    base: str
    git: Git
    link: bytes | None
    pool: PoolKind

    def rewritten(self) -> Path | None:
        """Return the file that says where the slot's git is, if the worker changed it: the `.git` file, or `commondir`.

        Returns:
            The `.git` file if it no longer holds what it did when the run started, else `commondir` in the slot's own
            git directory if it no longer names the common directory, else None. Always None when `.git` was not a
            file at the start.
        """
        if self.link is None:
            return None
        if hostgit.read_link(self.path) != self.link:
            return self.path / hostgit.LINK
        if hostgit.commondir_moved(self.path, self.link):
            own = hostgit.own_git_dir(self.path, self.link)
            return (own or self.path) / hostgit.COMMONDIR
        return None

    def reading(self, ctx: Context, objects: Path) -> Slot:
        """The slot, with its git reading the run's object directory as well as the slot's own objects.

        Returns:
            A copy of the slot whose git has the environment that reads `objects` too.

        Raises:
            SetupError: git could not be set up to read `objects`.
        """
        try:
            env = tidy.reading(ctx.runner, self.path, objects)
        except tidy.GitError as e:
            raise SetupError(f"{self.git.where}{e}") from e
        return replace(self, git=Git(ctx.runner, self.path, self.repo, env))

    @classmethod
    def of(cls, ctx: Context, row: records.RunSlot) -> Slot:
        """A worker run's slot, as its row records it, with its `.git` link read now, before any git step.

        Returns:
            The slot.
        """
        return cls.at(
            ctx,
            repo=str(row.repo),
            path=Path(row.slot_path),
            lease_id=row.lease_id,
            lease_holder=row.lease_holder,
            base=str(row.base_branch),
            pool=row.pool,
        )

    @classmethod
    def at(
        cls,
        ctx: Context,
        *,
        repo: str,
        path: Path,
        lease_id: str,
        lease_holder: str,
        base: str,
        pool: PoolKind,
    ) -> Slot:
        """The slot leased at `path` in `repo`'s pool, with its `.git` link read now, before any git step.

        Returns:
            The slot.
        """
        return cls(repo, path, lease_id, lease_holder, base, Git(ctx.runner, path, repo), hostgit.read_link(path), pool)


@dataclass(frozen=True)
class Start:
    """Where a worker run's slot started: HEAD's commit, how many entries HEAD's reflog then had, and origin's branch.

    `pushed` is the commit the branch held on origin when the run started, or "" if origin did not have it.
    """

    commit: str
    moves: int
    pushed: str


def check_out(slot: Slot, branch: str = "") -> Start:
    """Check out the slot's base branch from origin, detached, or `branch` from origin if it is given and there.

    A plan reads its base and creates no branch. A worker run passes its branch, which it continues if it was pushed.
    No run makes a local branch: every slot of a pool shares the repository's branch refs, so one would be state other
    slots see. The worker pushes `HEAD` to the branch by refspec (DESIGN §8, D109).

    Returns:
        HEAD's commit after the checkout, and how many entries HEAD's reflog then had.

    Raises:
        SetupError: a git step failed, or the base branch is not on origin.
    """
    git = slot.git
    # --prune: a slot keeps remote-tracking refs from earlier runs, which would hide a branch since deleted on origin.
    git.run("fetch", "--quiet", "--prune", "origin")
    # Checked even when the branch is continued: the worker's prompt targets the PR at the base. A stacked run's base
    # is another ticket's branch, deleted when its PR merged (DESIGN §10).
    if not git.ok("rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{slot.base}"):
        hint = "; if it was stacked on, its PR may have merged" if branch else ""
        raise SetupError(f"{git.where}the base branch {slot.base} is not on origin{hint}")
    target = slot.base
    if branch and git.ok("rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"):
        target = branch
    git.run("checkout", "--quiet", "--detach", f"refs/remotes/origin/{target}")
    if branch:
        _drop_local_branch(git, branch, target)
    commit = git.run("rev-parse", "HEAD")
    return Start(commit, len(_head_log(git)), commit if target == branch else "")


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


def run_setup(
    ctx: Context,
    slot: Slot,
    out: TextIO,
    log: logs.TickAdapter,
    *,
    run_id: str,
    branch: str,
    objects: Path,
    fields: Mapping[str, object],
) -> None:
    """Run the operator's `setup_cmd` in the slot, at the run's `branch`, and fail the run if it fails (DESIGN §8).

    Unlike treehouse's `post_create`, which runs on the base before the branch is checked out and whose failure leaves
    the lease standing, this sees the branch the worker gets, and a failure stops the run before the worker starts.
    `run_id` is the run's id as its agent gets it, `objects` its object directory, and `fields` name it in the log.

    Raises:
        SetupError: `setup_cmd` could not start, timed out, or exited non-zero.
    """
    argv = setup_words(ctx.config.runtime.setup_cmd)
    if not argv:
        return
    timeout_minutes = ctx.config.runtime.setup_timeout_minutes
    log.info("running setup", extra={**fields, "cmd": argv[0], "cwd": str(slot.path), "repo": slot.repo})
    try:
        result = ctx.runner.run(
            argv,
            cwd=slot.path,
            # The run's id, as the worker gets it: the operator's commands refuse inside canopy's runs (DESIGN §22).
            env={
                conversation.RUN_ID_ENV: run_id,
                SETUP_REPO_ENV: slot.repo,
                SETUP_BRANCH_ENV: branch,
                tidy.OBJECTS_ENV: str(objects),
            },
            timeout=timeout_minutes * 60,
        )
    except procs.ProcError as e:
        raise SetupError(f"{slot.git.where}setup could not start: {e}") from e
    out.write(f"--- setup {slot.repo} stdout ---\n{result.stdout}\n--- setup {slot.repo} stderr ---\n{result.stderr}\n")
    out.write(f"--- setup {slot.repo} exit {result.returncode}{' (timed out)' if result.timed_out else ''} ---\n")
    out.flush()
    if result.timed_out:
        raise SetupError(f"{slot.git.where}setup timed out after {timeout_minutes} minutes; see the run log")
    if not result.ok:
        raise SetupError(f"{slot.git.where}setup exited {result.returncode}; see the run log")


def ensure_pushed(slot: Slot, branch: str, start: Start, log: logs.TickAdapter, *, rebase: bool) -> str:
    """Check the checkpoint invariant: the branch on origin is the slot's HEAD. Push HEAD to it once if it is not.

    Detached, HEAD is the only thing holding the worker's commits, so a worker that moved it off them leaves them
    behind: that is unpushed too. With `rebase` (`trust.rebase`), the push may replace the branch, but only if origin
    still has it where the run started: a worker that rebased and did not push loses nothing anyone else pushed.

    Returns:
        Why the work is not pushed, or "" if it is, or if the worker committed nothing.
    """
    git = slot.git
    local = git.run("rev-parse", "HEAD")
    remote = remote_head(git, branch)
    # A HEAD that holds nothing past the start is no work of the worker's; whatever is on origin is its doing.
    if remote != local and not git.ok("merge-base", "--is-ancestor", local, start.commit):
        log.warning("worker left commits unpushed; pushing once", extra={"branch": branch, "repo": slot.repo})
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


def _head_log(git: Git) -> list[str]:
    """The commits in the slot's HEAD reflog, newest first, or none if it has no reflog.

    Returns:
        The commits' full hashes, one per reflog entry.
    """
    found = git.result("log", "--walk-reflogs", "--format=%H", "HEAD")
    return found.stdout.split() if found.ok else []


def remote_head(git: Git, branch: str) -> str:
    """The commit `branch` points to on origin, asked of origin itself.

    Returns:
        The commit's full hash, or "" if origin has no such branch.
    """
    listed = git.run("ls-remote", "origin", f"refs/heads/{branch}")
    return listed.split()[0] if listed else ""


def release(
    ctx: Context,
    slots: Collection[Slot],
    *,
    objects: Path,
    log: logs.TickAdapter,
    fields: Mapping[str, object],
) -> None:
    """Tidy each slot, return the ones tidied, and remove the run's object directory `objects` (DESIGN §8).

    A slot that could not be tidied is not returned, and the object directory is kept, so its objects can still be
    read. `fields` name the run in the log.
    """
    tidied = True
    for slot in slots:
        where = {**fields, "slot": str(slot.path), "repo": slot.repo}
        ok = tidy.tidy(ctx.runner, slot.path, link=slot.link, base=slot.base, objects=objects, log=log, fields=where)
        if ok:
            _return_slot(ctx, slot, log, {**where, "lease_id": slot.lease_id})
        tidied = tidied and ok
    if tidied:
        tidy.remove_objects(objects, log)


def _return_slot(ctx: Context, slot: Slot, log: logs.TickAdapter, fields: Mapping[str, object]) -> None:
    try:
        outcome = ctx.pool_of(slot.pool, slot.repo).return_slot(
            slot.path,
            lease_id=slot.lease_id,
            lease_holder=slot.lease_holder,
        )
    except pools.PoolError as e:
        # The next tick's reconcile returns a canopy lease with no running run.
        log.error("slot not returned", extra={**fields, "error": str(e)})  # noqa: TRY400
        return
    if outcome is pools.ReturnOutcome.RETURNED:
        log.info("slot returned", extra=fields)
    else:
        log.warning("slot not returned", extra={**fields, "outcome": outcome.value})


class Git:
    """git in one slot, through the runner. `name` is the slot's repository, for errors, or "" to leave it unnamed."""

    def __init__(self, runner: procs.Runner, slot: Path, name: str = "", env: Mapping[str, str] = hostgit.ENV) -> None:
        """Run git in `slot` through `runner` with `env`: the host's flags, and where it reads the run's objects."""
        self.runner = runner
        self.slot = slot
        self.where = f"{name}: " if name else ""
        self.env = env
        # Whether git here reads the run's object directory, and so must write no shared ref (DESIGN §8).
        self.reads_run = "GIT_OBJECT_DIRECTORY" in env

    def result(self, *args: str) -> procs.Result:
        """Run `git <args>` and return how it ended, whatever its exit.

        Returns:
            Its result.

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
        """Whether `git <args>` exits 0.

        Returns:
            True if it did.
        """
        return self.result(*args).ok

    def run(self, *args: str) -> str:
        """Run `git <args>`, which must exit 0, and return what it printed.

        Returns:
            Its stdout, stripped.

        Raises:
            SetupError: it exited nonzero.
        """
        result = self.result(*args)
        if not result.ok:
            detail = (result.stderr.strip() or result.stdout.strip())[:500]
            raise SetupError(f"{self.where}git {args[0]} exited {result.returncode}: {detail}")
        return result.stdout.strip()
