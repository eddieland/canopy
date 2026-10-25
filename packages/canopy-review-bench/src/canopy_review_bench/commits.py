"""Each case's two commits, built in the source clone with git's plumbing: the PR's base, and its head on top of it.

No branch, index, or working tree of the clone changes: trees are built in a private index file, and the commits are
written as objects alone, which a push names by their hashes.

- A `replay` keeps the history up to its base, which holds nothing of the bug's future. Its head is one commit on the
  base with the PR's whole change, its message the case's title, so no commit message of the PR's gives it away.
- An `undo_fix` has no history at all. Its base is the fix's tree, as a commit with no parent, since any history
  would hold the fix's own commit and its message; its head reverses the fix, or its `paths` part of it.

An overlay, files such as the reviewer's instructions, is written into both trees at its paths, so the reviewer reads
it on every case and the PR's diff never shows it.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from canopy_review_bench import command
from canopy_review_bench.bench import BenchError, Case, Side, Spot

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: The message of a base commit the bench writes: an `undo_fix`'s, or a `replay`'s with an overlay on it.
BASE_MESSAGE = "Update repository settings"
#: Git's settings for every command here: no paths quoted in a diff, and no driver or filter a repository can name.
_GIT = ("git", "-c", "core.quotePath=off", "-c", "diff.noprefix=false", "-c", "diff.mnemonicPrefix=false")
_HUNK = re.compile(r"^@@ -(?P<a>\d+)(?:,(?P<b>\d+))? \+(?P<c>\d+)(?:,(?P<d>\d+))? @@")
_PUSH_TIMEOUT_SECONDS = 1800


@dataclass(frozen=True)
class Overlay:
    """Files written into every case's two trees, at their paths in the repository."""

    #: Each file's bytes, and whether it is executable, by its path.
    files: Mapping[str, tuple[bytes, bool]]

    @property
    def digest(self) -> str:
        """The sha256 of every file's path and bytes, in hex: so two runs can say whether they read the same."""
        h = hashlib.sha256()
        for path in sorted(self.files):
            data, _ = self.files[path]
            h.update(f"{path}\0{len(data)}\0".encode())
            h.update(data)
        return h.hexdigest()


#: No overlay: the trees as the source has them.
NO_OVERLAY = Overlay({})


@dataclass(frozen=True)
class Built:
    """A case's commits, ready to push."""

    base: str
    head: str
    #: Where the bug is: the case's own spots, or, for an `undo_fix` that names none, every hunk of its diff.
    spots: Sequence[Spot]
    #: `git diff --stat` of the PR.
    stat: str


def read_overlay(directory: Path) -> Overlay:
    """Read every file under `directory` as an overlay, at its path relative to it.

    Returns:
        The overlay.

    Raises:
        BenchError: it is not a directory, holds a link, or a file cannot be read.
    """
    if not directory.is_dir():
        raise BenchError(f"overlay {directory} is not a directory")
    files: dict[str, tuple[bytes, bool]] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise BenchError(f"overlay {path} is a link; copy the file in")
        if path.is_file():
            try:
                files[path.relative_to(directory).as_posix()] = (path.read_bytes(), os.access(path, os.X_OK))
            except OSError as e:
                raise BenchError(f"overlay {path}: {e}") from e
    return Overlay(files)


def build(source: Path, case: Case, overlay: Overlay) -> Built:
    """Write `case`'s base and head commits in `source`, with `overlay` in both trees.

    Returns:
        The commits, where the bug is, and the PR's stat.

    Raises:
        BenchError: a commit the case names is not in `source`, its PR would change nothing, or git failed.
    """
    with tempfile.TemporaryDirectory(prefix="review-bench-") as tmp:
        git = _Git(source, Path(tmp) / "index")
        if case.replay is not None:
            base, head = git.replay(case.replay.base, case.replay.head, overlay, case.title)
        else:
            assert case.undo_fix is not None  # noqa: S101 - a case has exactly one source.
            base, head = git.undo(case.undo_fix.fix, case.undo_fix.paths, overlay, case.title)
        if git.tree(base) == git.tree(head):
            raise BenchError(f"case {case.name}: its PR changes nothing")
        spots = case.spots or tuple(_hunk_spots(git.diff(base, head)))
        return Built(base, head, spots, git.stat(base, head))


def push(source: Path, url: str, refs: Mapping[str, str]) -> None:
    """Push each commit in `refs` from `source` to `url` as the branch its key names, creating it.

    Raises:
        BenchError: the push failed.
    """
    specs = [f"{sha}:refs/heads/{branch}" for branch, sha in refs.items()]
    command.run(
        [*_GIT, "push", "--quiet", "--no-verify", url, *specs],
        cwd=source,
        timeout=_PUSH_TIMEOUT_SECONDS,
    )


class _Git:
    """git in the source clone, with a private index file for building trees."""

    def __init__(self, source: Path, index: Path) -> None:
        self._source = source
        self._env = {"GIT_INDEX_FILE": str(index)}

    def replay(self, base: str, head: str, overlay: Overlay, title: str) -> tuple[str, str]:
        """Write a replay's commits: the base, with the overlay if any, and the PR's change on it as `title`.

        Returns:
            The base commit and the head commit.
        """
        self._commit_exists(base)
        self._commit_exists(head)
        if overlay.files:
            base = self._commit(self._tree_of(base, overlay), parent=base, message=BASE_MESSAGE)
        return base, self._commit(self._tree_of(head, overlay), parent=base, message=title)

    def undo(self, fix: str, paths: Sequence[str], overlay: Overlay, title: str) -> tuple[str, str]:
        """Write an `undo_fix`'s commits: the fix's tree with no history, and the fix reversed on it, `title`.

        Returns:
            The base commit and the head commit.

        Raises:
            BenchError: the fix has no parent, so there is nothing to reverse it to, or it changes nothing in `paths`.
        """
        self._commit_exists(fix)
        parents = self._git("rev-list", "--parents", "-n", "1", fix).split()
        if len(parents) < 2:  # noqa: PLR2004 - the commit, then its first parent.
            raise BenchError(f"{fix} has no parent, so it cannot be undone")
        base = self._commit(self._tree_of(fix, overlay), parent=None, message=BASE_MESSAGE)
        patch = self._git("diff", "--binary", "--no-ext-diff", "--no-textconv", parents[1], fix, "--", *paths)
        if not patch.strip():
            raise BenchError(f"{fix} changes nothing under {', '.join(paths)}, so its PR changes nothing")
        self._git("read-tree", base)
        command.run([*_GIT, "apply", "--cached", "-R"], cwd=self._source, env=self._env, stdin=patch.encode())
        self._write_overlay(overlay)
        return base, self._commit(self._git("write-tree").strip(), parent=base, message=title)

    def tree(self, commit: str) -> str:
        """Return `commit`'s tree."""
        return self._git("rev-parse", f"{commit}^{{tree}}").strip()

    def diff(self, base: str, head: str) -> str:
        """Return the diff from `base` to `head`, with no context lines."""
        return self._git("diff", "--unified=0", "--no-color", "--no-ext-diff", "--no-textconv", base, head)

    def stat(self, base: str, head: str) -> str:
        """Return the diff's stat from `base` to `head`."""
        return self._git("diff", "--stat", base, head).rstrip()

    def _commit_exists(self, sha: str) -> None:
        try:
            self._git("cat-file", "-e", f"{sha}^{{commit}}")
        except BenchError as e:
            raise BenchError(f"{sha} is not a commit in {self._source}; fetch it first") from e

    def _tree_of(self, commit: str, overlay: Overlay) -> str:
        self._git("read-tree", commit)
        self._write_overlay(overlay)
        return self._git("write-tree").strip()

    def _write_overlay(self, overlay: Overlay) -> None:
        for path, (data, executable) in overlay.files.items():
            sha = command.run([*_GIT, "hash-object", "-w", "--stdin"], cwd=self._source, stdin=data).strip()
            mode = "100755" if executable else "100644"
            self._git("update-index", "--add", "--cacheinfo", f"{mode},{sha},{path}")

    def _commit(self, tree: str, *, parent: str | None, message: str) -> str:
        argv = ["commit-tree", tree, *(["-p", parent] if parent else [])]
        return self._git(*argv, "-m", message).strip()

    def _git(self, *args: str) -> str:
        return command.run([*_GIT, *args], cwd=self._source, env=self._env)


def _hunk_spots(diff: str) -> list[Spot]:
    """Return a `--unified=0` diff's hunks as spots: what each adds, on the head's side, and deletes, on the base's.

    A hunk with nothing on one side marks the line it sits after there, so a comment beside a deleted guard finds it.

    Returns:
        The spots, a hunk's head side first.
    """
    spots: list[Spot] = []
    old = new = ""
    for line in diff.splitlines():
        if line.startswith("--- "):
            old = line[len("--- a/") :] if line.startswith("--- a/") else ""
        elif line.startswith("+++ "):
            new = line[len("+++ b/") :] if line.startswith("+++ b/") else ""
        elif (hunk := _HUNK.match(line)) is not None:
            a, b = int(hunk["a"]), int(hunk["b"] or "1")
            c, d = int(hunk["c"]), int(hunk["d"] or "1")
            if new:
                spots.append(Spot(new, max(c, 1), max(c + d - 1, c, 1), Side.HEAD))
            if old:
                spots.append(Spot(old, max(a, 1), max(a + b - 1, a, 1), Side.BASE))
    return spots
