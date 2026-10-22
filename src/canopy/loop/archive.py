"""Plans archived to a clone of the operator's own each tick (DESIGN §25): exported, committed, and pushed.

With `paths.plan_archive` set, a live tick exports every plan of the workspace into `<clone>/<workspace>/`, or the
clone's top level with `paths.plan_archive_workspace_dir` off (`plan_export`), each with its planner's prompt unless
`paths.plan_archive_prompts` is off, each planned ticket's conversation with `paths.plan_archive_conversations`, and a
README.md indexing each ticket's plans and every ticket, commits what changed there and nothing else, under a message
naming each file it adds or changes, and pushes the clone's branch to its upstream. At the top level, "there" is what
the export wrote (`plan_export.owned`): each planned ticket's directory, and the index of every ticket while it is
canopy's, so the operator's own files beside them are never committed. A dry run only reads the clone.
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
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import hostgit, plan_export
from canopy.infra import procs

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path
    from sqlite3 import Connection

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
    name = ctx.workspace.name
    place = _Place(name, name if ctx.config.paths.plan_archive_workspace_dir else "")
    failure = None if dry_run else _archive(ctx, git, place, log)
    return failure or _unpushed(git, place, place.paths(ctx.conn, clone))


def _archive(ctx: Context, git: _Git, place: _Place, log: logs.TickAdapter) -> str | None:
    """Export the plans into the clone, at most `PER_TICK` files, then commit and push them.

    Returns:
        Why the archive is not all pushed, or None when every step it needed succeeded and no plan waits.
    """
    try:
        exported = plan_export.export(
            ctx.conn,
            ctx.state_dir,
            git.clone / place.directory,
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
    failure = _commit_and_push(git, place, place.paths(ctx.conn, git.clone), log, exported.removed)
    if failure is None and exported.left:
        waiting = (
            "plans, conversations, or READMEs wait" if exported.left != 1 else "plan, conversation, or README waits"
        )
        return f"{exported.left} {waiting} for the next tick's archive: a tick archives at most {PER_TICK} files"
    return failure


def _commit_and_push(
    git: _Git,
    place: _Place,
    paths: Sequence[str],
    log: logs.TickAdapter,
    removed: Sequence[str],
) -> str | None:
    """Commit what changed in `paths`, the files `removed` from them among it, and push when the branch is ahead.

    Returns:
        Why the archive is not pushed, or None when every step it needed succeeded.
    """
    failure = _stage(git, place, paths, removed) or _commit(git, place, paths)
    if failure is not None:
        return failure
    if git.has_commits() and git.ahead() != 0:
        pushed = git.run("push", "--quiet")
        if not pushed.ok:
            log.warning("plan archive not pushed", extra={"error": pushed.stderr.strip()[:_MAX_ERROR]})
            return git.failed("push", pushed)
    return None


def _stage(git: _Git, place: _Place, paths: Sequence[str], removed: Sequence[str]) -> str | None:
    """Stage what changed in `paths`, the files `removed` from them among it.

    Returns:
        Why it could not be staged, or None when it was.
    """
    if removed:
        # Out of the index first: one that ignores case, as on macOS, takes a file renamed in case alone for the file
        # it holds, and `add` would keep the old name, or drop it and miss the new one.
        unstaged = git.run("rm", "--cached", "--quiet", "--ignore-unmatch", "--", *map(place.path, removed))
        if not unstaged.ok:
            return git.failed("rm", unstaged)
    # git refuses a path that matches nothing, as the workspace's directory does before the workspace has a plan.
    held = [p for p in paths if (git.clone / p).is_file() or any((git.clone / p).iterdir())]
    if held:
        added = git.run("add", "--all", "--", *held)
        if not added.ok:
            return git.failed("add", added)
    return None


def _commit(git: _Git, place: _Place, paths: Sequence[str]) -> str | None:
    """Commit what is staged in `paths`, and nothing else the operator staged in the clone.

    Returns:
        Why it could not be committed, or None when it was, or nothing was staged.
    """
    # No path would be every path in the clone: nothing of the archive is there yet.
    if not paths:
        return None
    # Exit 1 is staged changes in `paths`, which a commit that failed on an earlier tick may have left too.
    staged = git.run("diff", "--cached", "--quiet", "--", *paths)
    if staged.returncode not in {0, 1}:
        return git.failed("diff", staged)
    if staged.returncode == 0:
        return None
    # With nothing else staged, the index is committed as it stands, since a commit naming paths stages them again,
    # which an index that ignores case refuses for a file renamed in case alone.
    others = git.run("diff", "--cached", "--quiet", "--", ".", *(f":(exclude){p}" for p in paths))
    if others.returncode not in {0, 1}:
        return git.failed("diff", others)
    named = ("--", *paths) if others.returncode == 1 else ()
    committed = git.run("commit", "--quiet", "-m", _message(git, place, paths), *named)
    return None if committed.ok else git.failed("commit", committed)


def _message(git: _Git, place: _Place, paths: Sequence[str]) -> str:
    """A commit message for what is staged in `paths`: how many files of each sort, of which tickets, then each.

    A plan's file is named for its run, status, and title (`plan_export.name`), so the file's name says what each plan
    is, and a plan whose status changed shows as its rename. A prompt is named for its run alone, a conversation for
    nothing but its ticket, and an index for nothing at all, the one of every ticket outside any ticket's directory.

    Returns:
        The message; a subject alone when git cannot say what is staged.
    """
    # Renames asked for here, whatever the operator's config says, so a plan renamed for its status is one change.
    staged = git.run("diff", "--cached", "--name-status", "--find-renames", "-z", "--", *paths)
    changes = _changes(staged.stdout, place)
    name = place.name
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


def _changes(listed: str, place: _Place) -> list[tuple[str, str, str | None]]:
    """The changes `git diff --name-status -z` listed in the archive, in git's order.

    Returns:
        Each change's heading in `_CHANGES`, its path, and a rename's earlier path, both relative to the archive's
        directory; a copy or a change of type is headed as changed.
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
        changes.append((heading, place.relative(path), was and place.relative(was)))
    return changes


def _unpushed(git: _Git, place: _Place, paths: Sequence[str]) -> str | None:
    """Whether the archive in the clone, `paths`, is all committed and on its upstream, read without changing anything.

    Returns:
        What is not, or None.
    """
    # No path would be every path in the clone: nothing of the archive is there to commit.
    if paths:
        status = git.run("status", "--porcelain", "--", *paths)
        if not status.ok:
            return git.failed("status", status)
        if status.stdout.strip():
            return f"plans exported to {git.clone / place.directory} are not committed"
    if not git.has_commits():
        return None
    ahead = git.ahead()
    if ahead is None:
        return f"{git.clone}'s branch has no upstream canopy can push to"
    if ahead:
        return f"{ahead} commit{'s' if ahead != 1 else ''} of plans in {git.clone} are not on its upstream"
    return None


@dataclass(frozen=True)
class _Place:
    """Where in the clone a workspace's plans are archived."""

    #: The workspace's name, which each commit's subject names.
    name: str
    #: The directory in the clone the plans go in, relative to it: the workspace's name, or empty for its top level.
    directory: str

    def paths(self, conn: Connection, clone: Path) -> list[str]:
        """The paths in the clone the archive commits.

        Returns:
            The workspace's directory; at the top level, what an export wrote there, so nothing of the operator's.
        """
        return [self.directory] if self.directory else plan_export.owned(conn, clone)

    def path(self, exported: str) -> str:
        """A path in the archive's directory, as `plan_export` names it, made relative to the clone.

        Returns:
            The path, as git names it.
        """
        return f"{self.directory}/{exported}" if self.directory else exported

    def relative(self, path: str) -> str:
        """A path in the clone, as git names it, made relative to the archive's directory.

        Returns:
            The path, as `plan_export` names it.
        """
        return path.removeprefix(f"{self.directory}/") if self.directory else path


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
