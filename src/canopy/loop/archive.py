"""Plans archived to a clone of the operator's own each tick (DESIGN §25): exported, committed, and pushed.

With `paths.plan_archive` set, a live tick exports every plan of the workspace into `<clone>/<workspace>/`
(`plan_export`), each with its planner's prompt unless `paths.plan_archive_prompts` is off, each planned ticket's
conversation with `paths.plan_archive_conversations`, and a README.md indexing each ticket's plans and every ticket,
commits what changed there and nothing else, under a message
naming each file it adds or changes, and pushes the clone's branch to its upstream. A dry run only reads the clone.
Either way the tick raises `archive_unpushed` while the archive is not all on its upstream, so a push that failed is
retried each live tick and the operator sees why until one succeeds. A tick writes at most `PER_TICK` files, so a long
history goes in over several ticks, each commit and push bounded, and the item stays open until it all has.

The path must be a clone's own top level, never a directory inside a repository, which could be one the operator works
in. git runs as the harness always runs it (D107), and the push never forces. Nothing here raises: an archive that fails
is an item, never a failed tick.
"""

from __future__ import annotations

import itertools
import operator
from typing import TYPE_CHECKING

from canopy.core import hostgit, plan_export
from canopy.infra import procs

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from canopy.core.context import Context
    from canopy.infra import logs

#: The attention item raised while the plan archive is not all on its upstream.
REASON = "archive_unpushed"
#: The most plan files one tick exports, commits, and pushes, so a push of a long history fits its timeout.
PER_TICK = 1000
_GIT_TIMEOUT_SECONDS = 60
# The most of git's own message an item's detail carries.
_MAX_ERROR = 300
# The most ticket keys a commit's subject names before it counts the rest.
_SUBJECT_KEYS = 3
# How each change `git diff --name-status` reports is headed in a commit's body, in the body's order.
_CHANGES = {"A": "New", "M": "Changed", "R": "Changed", "D": "Removed"}


def run(ctx: Context, log: logs.TickAdapter, *, dry_run: bool) -> str | None:
    """Archive the workspace's plans to `paths.plan_archive` on a live tick, and say whether the archive is pushed.

    Returns:
        The detail of an `archive_unpushed` item when the archive is not all on its upstream, with why when this tick
        could tell; None when it is, or when no archive is set.
    """
    clone = ctx.config.paths.plan_archive
    if clone is None:
        return None
    if not (clone / hostgit.LINK).exists():
        return (
            f"{clone} is not a git clone's top level, so no plan is archived there; clone your archive repository there"
        )
    git = _Git(ctx.runner, clone)
    failure = None if dry_run else _archive(ctx, git, ctx.workspace.name, log)
    return failure or _unpushed(git, ctx.workspace.name)


def _archive(ctx: Context, git: _Git, name: str, log: logs.TickAdapter) -> str | None:
    """Export the plans into the clone, at most `PER_TICK` files, then commit and push them.

    Returns:
        Why the archive is not all pushed, or None when every step it needed succeeded and no plan waits.
    """
    try:
        exported = plan_export.export(
            ctx.conn,
            ctx.state_dir,
            git.clone / name,
            limit=PER_TICK,
            prompts=ctx.config.paths.plan_archive_prompts,
            conversations=ctx.config.paths.plan_archive_conversations,
            indexes=True,
        )
    except plan_export.ExportError as e:
        log.warning("plans not archived", extra={"error": str(e)})
        return f"plans were not exported to {git.clone}: {e}"
    if exported.written or exported.removed:
        extra = {
            "written": len(exported.written),
            "removed": len(exported.removed),
            "left": exported.left,
            "clone": str(git.clone),
        }
        log.info("plans archived", extra=extra)
    failure = _commit_and_push(git, name, log, exported.removed)
    if failure is None and exported.left:
        waiting = (
            "plans, conversations, or READMEs wait" if exported.left != 1 else "plan, conversation, or README waits"
        )
        return f"{exported.left} {waiting} for the next tick's archive: a tick archives at most {PER_TICK} files"
    return failure


def _commit_and_push(git: _Git, name: str, log: logs.TickAdapter, removed: Sequence[str]) -> str | None:
    """Commit what changed in `name/`, the files `removed` from it among it, and push when the branch is ahead.

    Returns:
        Why the archive is not pushed, or None when every step it needed succeeded.
    """
    failure = _stage(git, name, removed) or _commit(git, name)
    if failure is not None:
        return failure
    if git.has_commits() and git.ahead() != 0:
        pushed = git.run("push", "--quiet")
        if not pushed.ok:
            log.warning("plan archive not pushed", extra={"error": pushed.stderr.strip()[:_MAX_ERROR]})
            return git.failed("push", pushed)
    return None


def _stage(git: _Git, name: str, removed: Sequence[str]) -> str | None:
    """Stage what changed in `name/`, the files `removed` from it among it.

    Returns:
        Why it could not be staged, or None when it was.
    """
    if removed:
        # Out of the index first: one that ignores case, as on macOS, takes a file renamed in case alone for the file
        # it holds, and `add` would keep the old name, or drop it and miss the new one.
        unstaged = git.run("rm", "--cached", "--quiet", "--ignore-unmatch", "--", *(f"{name}/{r}" for r in removed))
        if not unstaged.ok:
            return git.failed("rm", unstaged)
    # git refuses a path that matches nothing, as `name/` does before the workspace has a plan.
    if any((git.clone / name).iterdir()):
        added = git.run("add", "--all", "--", name)
        if not added.ok:
            return git.failed("add", added)
    return None


def _commit(git: _Git, name: str) -> str | None:
    """Commit what is staged in `name/`, and nothing else the operator staged in the clone.

    Returns:
        Why it could not be committed, or None when it was, or nothing was staged.
    """
    # Exit 1 is staged changes under `name/`, which a commit that failed on an earlier tick may have left too.
    staged = git.run("diff", "--cached", "--quiet", "--", name)
    if staged.returncode not in {0, 1}:
        return git.failed("diff", staged)
    if staged.returncode == 0:
        return None
    # With nothing else staged, the index is committed as it stands, since a commit naming paths stages them again,
    # which an index that ignores case refuses for a file renamed in case alone.
    others = git.run("diff", "--cached", "--quiet", "--", ".", f":(exclude){name}")
    if others.returncode not in {0, 1}:
        return git.failed("diff", others)
    paths = ("--", name) if others.returncode == 1 else ()
    committed = git.run("commit", "--quiet", "-m", _message(git, name), *paths)
    return None if committed.ok else git.failed("commit", committed)


def _message(git: _Git, name: str) -> str:
    """A commit message for what is staged under `name/`: how many files of each sort, of which tickets, then each.

    A plan's file is named for its run, status, and title (`plan_export.name`), so the file's name says what each plan
    is, and a plan whose status changed shows as its rename. A prompt is named for its run alone, a conversation for
    nothing but its ticket, and an index for nothing at all, the one of every ticket outside any ticket's directory.

    Returns:
        The message; a subject alone when git cannot say what is staged.
    """
    # Renames asked for here, whatever the operator's config says, so a plan renamed for its status is one change.
    staged = git.run("diff", "--cached", "--name-status", "--find-renames", "-z", "--", name)
    changes = _changes(staged.stdout, name)
    if not staged.ok or not changes:
        return f"Archive the plans of {name}"
    keys = list(dict.fromkeys(path.partition("/")[0] for _, path, _ in changes if "/" in path))
    named = ", ".join(keys[:_SUBJECT_KEYS])
    if len(keys) > _SUBJECT_KEYS:
        named += f" and {len(keys) - _SUBJECT_KEYS} more"
    file_names = [path.rpartition("/")[2] for _, path, _ in changes]
    prompts = sum(map(plan_export.is_prompt, file_names))
    conversations = sum(map(plan_export.is_conversation, file_names))
    readmes = sum(map(plan_export.is_index, file_names))
    counts = [
        (len(changes) - prompts - conversations - readmes, "plan"),
        (prompts, "prompt"),
        (conversations, "conversation"),
        (readmes, "README"),
    ]
    # Never empty: every change is counted as one sort or another.
    *rest, last = [f"{n} {noun}{'s' if n != 1 else ''}" for n, noun in counts if n]
    counted = f"{', '.join(rest)} and {last}" if rest else last
    lines = [f"Archive {counted} of {name}: {named}" if named else f"Archive {counted} of {name}"]
    headings = list(dict.fromkeys(_CHANGES.values()))
    by_heading = sorted(changes, key=lambda change: headings.index(change[0]))
    for heading, group in itertools.groupby(by_heading, key=operator.itemgetter(0)):
        lines.extend(["", f"{heading}:"])
        for _, path, was in group:
            lines.append(f"- {path} (was {was.rpartition('/')[2]})" if was else f"- {path}")
    return "\n".join(lines) + "\n"


def _changes(listed: str, name: str) -> list[tuple[str, str, str | None]]:
    """The changes `git diff --name-status -z` listed under `name/`, in git's order.

    Returns:
        Each change's heading in `_CHANGES`, its path, and a rename's earlier path, both relative to `name/`; a copy or
        a change of type is headed as changed.
    """
    fields = iter(listed.split("\0"))
    changes: list[tuple[str, str, str | None]] = []
    for status in fields:
        if not status:
            break
        # A rename or a copy names its earlier path, then its path; any other change names its path alone.
        was = next(fields, "") if status[0] in {"R", "C"} else None
        path = next(fields, "")
        heading = _CHANGES.get(status[0], _CHANGES["M"])
        changes.append((heading, path.removeprefix(f"{name}/"), was and was.removeprefix(f"{name}/")))
    return changes


def _unpushed(git: _Git, name: str) -> str | None:
    """Whether the archive in the clone is all committed and on its upstream, read without changing anything.

    Returns:
        What is not, or None.
    """
    status = git.run("status", "--porcelain", "--", name)
    if not status.ok:
        return git.failed("status", status)
    if status.stdout.strip():
        return f"plans exported to {git.clone / name} are not committed"
    if not git.has_commits():
        return None
    ahead = git.ahead()
    if ahead is None:
        return f"{git.clone}'s branch has no upstream canopy can push to"
    if ahead:
        return f"{ahead} commit{'s' if ahead != 1 else ''} of plans in {git.clone} are not on its upstream"
    return None


class _Git:
    """git in the archive's clone, as the harness runs it: hooks off, no prompt, a timeout (D107)."""

    def __init__(self, runner: procs.Runner, clone: Path) -> None:
        self.runner = runner
        self.clone = clone

    def run(self, *args: str) -> procs.Result:
        """Run `git <args>` in the clone.

        Returns:
            Its result; one that could not start reads as failed, with why.
        """
        try:
            return self.runner.run(hostgit.argv(*args), cwd=self.clone, env=hostgit.ENV, timeout=_GIT_TIMEOUT_SECONDS)
        except procs.ProcError as e:
            return procs.Result(tuple(hostgit.argv(*args)), 127, "", str(e))

    def has_commits(self) -> bool:
        """Whether the clone's branch has a commit.

        Returns:
            False for a clone of an empty repository until its first archive.
        """
        return self.run("rev-parse", "--verify", "--quiet", "HEAD").ok

    def ahead(self) -> int | None:
        """How many commits HEAD has that its upstream does not.

        Returns:
            The count, or None when git cannot tell, as for a branch with no upstream.
        """
        counted = self.run("rev-list", "--count", "@{upstream}..HEAD")
        return int(counted.stdout.strip()) if counted.ok and counted.stdout.strip().isdigit() else None

    def failed(self, step: str, result: procs.Result) -> str:
        """An item's detail for a git step that failed: what git said, cut short.

        Returns:
            The detail.
        """
        said = (result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}")[:_MAX_ERROR]
        if result.timed_out:
            said = f"timed out after {_GIT_TIMEOUT_SECONDS}s"
        return f"git {step} in {self.clone} failed: {said}"
