"""Plans archived to a clone of the operator's own each tick (DESIGN §25): exported, committed, and pushed.

With `paths.plan_archive` set, a live tick exports every plan of the workspace into `<clone>/<workspace>/`
(`plan_export`), commits what changed there and nothing else, under a message naming each plan it adds or changes, and
pushes the clone's branch to its upstream. A dry run
only reads the clone. Either way the tick raises `archive_unpushed` while the archive is not all on its upstream, so a
push that failed is retried each live tick and the operator sees why until one succeeds. A tick writes at most
`PER_TICK` files, so a long history goes in over several ticks, each commit and push bounded, and the item stays open
until it all has.

The path must be a clone's own top level, never a directory inside a repository, which could be one the operator works
in. git runs as the harness always runs it (D107), and the push never forces. Nothing here raises: an archive that fails
is an item, never a failed tick.
"""

from __future__ import annotations

import itertools
import json
import operator
from typing import TYPE_CHECKING, get_args

from canopy.core import hostgit, plan_export
from canopy.core.vocab import PlanStatus
from canopy.infra import procs

if TYPE_CHECKING:
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
_CHANGES = {"A": "New", "M": "Changed", "D": "Removed"}
# The front matter `plan_export.document` opens and closes a file with.
_FRONT_MATTER = "---"


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
        exported = plan_export.export(ctx.conn, ctx.state_dir, git.clone / name, limit=PER_TICK)
    except plan_export.ExportError as e:
        log.warning("plans not archived", extra={"error": str(e)})
        return f"plans were not exported to {git.clone}: {e}"
    if exported.written:
        extra = {"written": len(exported.written), "left": exported.left, "clone": str(git.clone)}
        log.info("plans archived", extra=extra)
    failure = _commit_and_push(git, name, log)
    if failure is None and exported.left:
        return (
            f"{exported.left} {'plans wait' if exported.left != 1 else 'plan waits'} for the next tick's archive: "
            f"a tick archives at most {PER_TICK} files"
        )
    return failure


def _commit_and_push(git: _Git, name: str, log: logs.TickAdapter) -> str | None:
    """Commit what changed in `name/`, and push when the branch is ahead.

    Returns:
        Why the archive is not pushed, or None when every step it needed succeeded.
    """
    # git refuses a path that matches nothing, as `name/` does before the workspace has a plan.
    if any((git.clone / name).iterdir()):
        added = git.run("add", "--all", "--", name)
        if not added.ok:
            return git.failed("add", added)
    # Exit 1 is staged changes under `name/`, which a commit that failed on an earlier tick may have left too.
    staged = git.run("diff", "--cached", "--quiet", "--", name)
    if staged.returncode not in {0, 1}:
        return git.failed("diff", staged)
    if staged.returncode == 1:
        # Only `name/`: anything else the operator staged in the clone stays staged.
        committed = git.run("commit", "--quiet", "-m", _message(git, name), "--", name)
        if not committed.ok:
            return git.failed("commit", committed)
    if git.has_commits() and git.ahead() != 0:
        pushed = git.run("push", "--quiet")
        if not pushed.ok:
            log.warning("plan archive not pushed", extra={"error": pushed.stderr.strip()[:_MAX_ERROR]})
            return git.failed("push", pushed)
    return None


def _message(git: _Git, name: str) -> str:
    """A commit message for what is staged under `name/`: how many plans of which tickets, then each file and its plan.

    Returns:
        The message; a subject alone when git cannot say what is staged.
    """
    staged = git.run("diff", "--cached", "--name-status", "--no-renames", "-z", "--", name)
    fields = staged.stdout.split("\0")
    changes = [
        (change, path.removeprefix(f"{name}/"))
        for change, path in zip(fields[::2], fields[1::2], strict=False)
        if change in _CHANGES
    ]
    if not staged.ok or not changes:
        return f"Archive the plans of {name}"
    keys = list(dict.fromkeys(path.partition("/")[0] for _, path in changes))
    named = ", ".join(keys[:_SUBJECT_KEYS])
    if len(keys) > _SUBJECT_KEYS:
        named += f" and {len(keys) - _SUBJECT_KEYS} more"
    files = f"{len(changes)} plan{'s' if len(changes) != 1 else ''}"
    lines = [f"Archive {files} of {name}: {named}"]
    by_change = sorted(changes, key=lambda change_path: list(_CHANGES).index(change_path[0]))
    for change, group in itertools.groupby(by_change, key=operator.itemgetter(0)):
        lines.extend(["", f"{_CHANGES[change]}:"])
        for _, path in group:
            described = None if change == "D" else _described(git.clone / name / path)
            lines.append(f"- {path} ({described})" if described else f"- {path}")
    return "\n".join(lines) + "\n"


def _described(path: Path) -> str | None:
    """A plan's kind and status, from the front matter its export opens with.

    Only values canopy writes are taken, so nothing else in the file reaches a commit message.

    Returns:
        Its kind and status, as `feedback plan, approved`; None when the file holds no front matter that names both.
    """
    found: dict[str, str] = {}
    try:
        with path.open(encoding="utf-8") as f:
            if f.readline().rstrip("\n") != _FRONT_MATTER:
                return None
            for line in f:
                key, _, value = line.rstrip("\n").partition(": ")
                if key == _FRONT_MATTER:
                    break
                if key in {"kind", "status"}:
                    decoded: object = json.loads(value)
                    if isinstance(decoded, str):
                        found[key] = decoded
    except (OSError, ValueError):
        return None
    kind, status = found.get("kind"), found.get("status")
    if kind not in get_args(plan_export.Kind.__value__) or status not in set(PlanStatus):
        return None
    return f"{kind}, {status}"


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
