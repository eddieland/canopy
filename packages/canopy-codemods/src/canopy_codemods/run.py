"""Run codemods over files: find the Python under the paths given, rewrite each file's text, and say what changed.

Nothing here writes a file or prints: `rewrite_all` gives back each file's text before and after, and the command line
decides whether that is a file to write or a diff to fail on.
"""

from __future__ import annotations

import difflib
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from libcst.codemod import CodemodContext, TransformExit, TransformFailure, TransformSkip, TransformSuccess
from libcst.codemod import transform_module as apply

from canopy_codemods.registry import CODEMODS

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Sequence

#: Directories never searched, beside the hidden ones: other tools' files, and what a build leaves behind.
PRUNED: Final = frozenset({"__pycache__", "build", "dist", "node_modules", "site-packages", "venv"})
#: Below this many files a pool of processes costs more to start than it saves.
_SERIAL: Final = 8


@dataclass(frozen=True)
class Rewrite:
    """What the codemods made of one file."""

    path: Path
    #: The file's text as it was read.
    before: str
    #: Its text after every codemod; equal to `before` when none changed it, or one failed.
    after: str
    #: Why a codemod could not run on the file, such as a syntax error, or None.
    error: str | None = None

    @property
    def changed(self) -> bool:
        """Whether the codemods would rewrite the file."""
        return self.after != self.before

    def diff(self) -> str:
        """The change as a unified diff.

        Returns:
            The diff, empty when the file is unchanged.
        """
        before, after = self.before.splitlines(keepends=True), self.after.splitlines(keepends=True)
        return "".join(difflib.unified_diff(before, after, str(self.path), str(self.path)))


def rewrite_all(paths: Iterable[Path], names: Sequence[str]) -> list[Rewrite]:
    """Run the codemods named over every Python file under `paths`, changing none.

    Args:
        paths: Files, taken as Python whatever their names, and directories, searched for it.
        names: The codemods to run, of `registry.CODEMODS`, in order.

    Returns:
        A rewrite for each file, in the files' order.
    """
    found = files(paths)
    if len(found) < _SERIAL:
        return [rewrite_file(path, names) for path in found]
    with ProcessPoolExecutor() as pool:
        return list(pool.map(rewrite_file, found, [names] * len(found), chunksize=16))


def files(paths: Iterable[Path]) -> list[Path]:
    """The Python files under `paths`, sorted, each once.

    A file named outright is taken as Python. A directory gives its `.py` files and its scripts that open with a
    Python shebang, such as the test fakes, but nothing under a hidden directory or one of `PRUNED`.

    Returns:
        The files.
    """
    found: set[Path] = set()
    for path in paths:
        if not path.is_dir():
            found.add(path)
            continue
        for directory, subdirectories, names in os.walk(path):
            subdirectories[:] = [d for d in subdirectories if d not in PRUNED and not d.startswith(".")]
            found.update(file for name in names if _is_python(file := Path(directory, name)))
    return sorted(found)


def rewrite_file(path: Path, names: Collection[str]) -> Rewrite:
    """Run the codemods named over the file at `path`, without changing it.

    Returns:
        The file's text before and after, or the error that stopped a codemod.
    """
    try:
        before = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return Rewrite(path, "", "", error=str(e))
    try:
        return Rewrite(path, before, rewrite(before, names, filename=str(path)))
    except CodemodError as e:
        return Rewrite(path, before, before, error=str(e))


class CodemodError(Exception):
    """A codemod could not run on a module: it does not parse, or the codemod itself failed."""


def rewrite(source: str, names: Iterable[str], *, filename: str | None = None) -> str:
    """Run the codemods named over a module's text, each on what the one before it made.

    Returns:
        The module's text after the last of them.

    Raises:
        CodemodError: When one of them could not run.
    """
    for name in names:
        codemod = CODEMODS[name]
        if not codemod.wants(source):
            continue
        result = apply(codemod(CodemodContext(filename=filename)), source)
        match result:
            case TransformSuccess():
                source = result.code
            case TransformSkip():
                pass
            case TransformFailure():
                raise CodemodError(f"{name}: {result.error}")
            case TransformExit():
                raise CodemodError(f"{name}: interrupted")
    return source


def _is_python(file: Path) -> bool:
    """Whether a file found in a directory is Python: by its suffix, or with none, by its shebang.

    Returns:
        True for Python.
    """
    if file.suffix:
        return file.suffix == ".py"
    try:
        with file.open("rb") as stream:
            first = stream.readline(128)
    except OSError:
        return False
    return first.startswith(b"#!") and b"python" in first
