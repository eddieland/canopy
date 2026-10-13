"""A review run's diff, as the web UI's review page shows it (DESIGN §21, Reading reviews).

`_review` writes `git diff` of the reviewed commit against where it leaves its pool's base branch beside the run's log,
`<id>.diff`. This reads it back and parses it into files, hunks, and numbered lines, and anchors each finding at its
`path:line` when that line is in the diff. The diff is the PR's own text: untrusted, and unbounded until it is read.
So the file is read only if it is a regular file and not a symlink, at most `MAX_BYTES` of it; control characters
other than tabs become spaces; and files, lines, and each line's characters are cut at a bound, with `truncated` saying
something was.
"""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# How much of a diff is written and read: a large PR's, and little enough to read on each request.
MAX_BYTES = 4 * 1024 * 1024
# How many files and lines a diff holds, and how many characters a line keeps.
MAX_FILES = 500
MAX_LINES = 30_000
MAX_LINE_CHARS = 1000

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$")
_LOCATION_RE = re.compile(r"^(?P<path>.+?)(?::L?(?P<line>\d+)(?:[-:]\d+)?)?$")

type LineKind = Literal["add", "del", "ctx"]


@dataclass(frozen=True)
class Line:
    """One line of a hunk, with its number on each side it is on."""

    kind: LineKind
    old: int | None
    new: int | None
    text: str


@dataclass
class Hunk:
    """One `@@` hunk: its header after the ranges, such as a function's name, and its lines."""

    header: str
    lines: list[Line] = field(default_factory=list)


@dataclass
class File:
    """One file's change. `old_path` is set when it was renamed; `binary` when git shows no lines for it."""

    path: str
    old_path: str | None = None
    binary: bool = False
    hunks: list[Hunk] = field(default_factory=list)


@dataclass
class Diff:
    """The files a diff changes, in its order, and whether a bound left something out."""

    files: list[File] = field(default_factory=list)
    truncated: bool = False


def path_for(log_path: str | Path) -> Path:
    """Where a review run's diff is kept: beside its log, as `<id>.diff`."""
    return Path(log_path).with_suffix(".diff")


def read(path: Path) -> Diff | None:
    """Read and parse the diff at `path`. None when it is missing, a symlink, or not a regular file."""
    try:
        # Non-blocking, so a FIFO in the diff's place cannot hold the request open; it is refused below.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        return None
    with os.fdopen(fd, "rb") as f:
        data = f.read(MAX_BYTES + 1)
    truncated = len(data) > MAX_BYTES
    if truncated:
        # The last line read may be cut short; drop it.
        data = data[: data.rfind(b"\n", 0, MAX_BYTES) + 1]
    diff = parse(data.decode("utf-8", errors="replace"))
    diff.truncated = diff.truncated or truncated
    return diff


def parse(text: str) -> Diff:
    """Parse `git diff` output into files, hunks, and numbered lines, within the bounds."""
    parser = _Parser()
    for raw in text.splitlines():
        if not parser.feed(raw):
            parser.diff.truncated = True
            break
    return parser.diff


def anchor(diff: Diff, location: str) -> tuple[int | None, int | None]:
    """Where a finding's `path:line` falls in `diff`: the file's index and the line, when the diff shows it.

    `(index, None)` when the file is in the diff but the line is not, or the location names no line; `(None, None)`
    when no file matches. A path matches a file's in full, or as its unique suffix after a `/`.
    """
    found = _LOCATION_RE.match(location.strip())
    if found is None:
        return None, None
    path = found["path"].strip().strip("`")
    for prefix in ("./", "a/", "b/"):
        if path.startswith(prefix) and not any(f.path == path for f in diff.files):
            path = path.removeprefix(prefix)
    index = _file_index(diff, path)
    if index is None:
        return None, None
    if found["line"] is None:
        return index, None
    line = int(found["line"])
    shown = any(ln.new == line for h in diff.files[index].hunks for ln in h.lines)
    return index, line if shown else None


class _Parser:
    """Reads a diff line by line, keeping the file and hunk it is in and the next line's numbers on each side."""

    def __init__(self) -> None:
        self.diff = Diff()
        self.file: File | None = None
        self.hunk: Hunk | None = None
        self.old = 0
        self.new = 0
        self.lines = 0

    def feed(self, raw: str) -> bool:
        """Take one line. False when a bound is reached: the rest is left out."""
        if raw.startswith("diff --git "):
            if len(self.diff.files) >= MAX_FILES:
                return False
            self.file = File(path=_from_header(raw))
            self.diff.files.append(self.file)
            self.hunk = None
        elif self.file is None or raw.startswith("\\"):
            pass  # before the first file, or "\ No newline at end of file"
        elif raw.startswith("@@"):
            self._start_hunk(self.file, raw)
        elif self.hunk is None:
            _file_header(self.file, raw)
        else:
            if self.lines >= MAX_LINES:
                return False
            self._line(self.hunk, raw)
        return True

    def _start_hunk(self, f: File, raw: str) -> None:
        found = _HUNK_RE.match(raw)
        if found is None:
            return
        self.hunk = Hunk(header=_clean(found[3].strip()))
        f.hunks.append(self.hunk)
        self.old, self.new = int(found[1]), int(found[2])

    def _line(self, hunk: Hunk, raw: str) -> None:
        kind, text = _kind(raw)
        hunk.lines.append(
            Line(
                kind=kind,
                old=self.old if kind != "add" else None,
                new=self.new if kind != "del" else None,
                text=_clean(text),
            )
        )
        self.lines += 1
        self.old += kind != "add"
        self.new += kind != "del"


def _from_header(raw: str) -> str:
    # `diff --git a/x b/y`: the new path, unless a later line names it exactly (paths with spaces, renames).
    rest = raw.removeprefix("diff --git ")
    _, sep, new = rest.rpartition(" b/")
    return _clean(new if sep else rest)


def _file_header(f: File, raw: str) -> None:
    if raw.startswith("rename from "):
        f.old_path = _clean(_unquote(raw.removeprefix("rename from ")))
    elif raw.startswith("rename to "):
        f.path = _clean(_unquote(raw.removeprefix("rename to ")))
    elif raw.startswith("+++ ") and raw != "+++ /dev/null":
        f.path = _clean(_unquote(raw.removeprefix("+++ ")).removeprefix("b/"))
    elif raw.startswith("--- ") and raw != "--- /dev/null" and f.old_path is None:
        old = _clean(_unquote(raw.removeprefix("--- ")).removeprefix("a/"))
        f.old_path = old if old != f.path else None
    elif raw.startswith("Binary files ") or raw == "GIT binary patch":
        f.binary = True


def _kind(raw: str) -> tuple[LineKind, str]:
    if raw.startswith("+"):
        return "add", raw[1:]
    if raw.startswith("-"):
        return "del", raw[1:]
    return "ctx", raw[1:]


def _unquote(path: str) -> str:
    # git quotes a path with unusual characters as a C string; show it without the quotes, escapes as they are.
    return path[1:-1] if len(path) > 1 and path.startswith('"') and path.endswith('"') else path


def _clean(text: str) -> str:
    cleaned = "".join(c if c.isprintable() or c == "\t" else " " for c in text)
    return cleaned[:MAX_LINE_CHARS]


def _file_index(diff: Diff, path: str) -> int | None:
    exact = [i for i, f in enumerate(diff.files) if path in (f.path, f.old_path)]
    if exact:
        return exact[0]
    suffix = [i for i, f in enumerate(diff.files) if f.path.endswith(f"/{path}")]
    return suffix[0] if len(suffix) == 1 else None
