"""Whether a worker's push kept to the files its approved plan's steps name (DESIGN §25, Workers follow the plan).

No model: a worker run that follows the ticket's approved plan keeps, beside its log, every path its pushed branch
touches against where it leaves its base (`keep`, one file per repository), and `canopy show run:ID` sets them against
the files the plan's `### Step N` sections name (`compare`): the paths no step names, and each step's files the push
left untouched. It decides nothing, and says nothing of whether the work is right.

How a step names a file, kept simple so the operator can predict it:

- A step's section runs from its heading, a level-3 heading starting `Step N`, to the next heading of level 3 or above.
- It names a file with an inline code span, outside fenced code, whose text is a relative path: `src/canopy/plans.py`.
  A `:12`, `:12-20`, `#L12`, or `::test_name` after the path is dropped, so `path:line` citations count.
- A path with a `/` names that file and, as a directory, every file under it: `src/canopy/core/` or `src/canopy/core`.
  A joint run's step may lead with the repository, as its planner reads it through its desk: `api/src/app.py`.
- A bare name, such as `README.md` or `plans.outline`, reads as well as a qualified name as a file, so it names a file
  only when the push touched one of that path at a repository's top level, and is never reported untouched.
- A span with spaces, a glob, a URL, or `..` names nothing, and neither does a path outside a code span.

The kept paths are git's names for files a worker made, and the plan is model text: both untrusted (TRUST_MODEL T1).
The file is read only if it is a regular file and not a symlink, at most `MAX_BYTES` of it, and at most `MAX_PATHS`
paths; the caller makes each printable before it shows it.
"""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from canopy.infra import logs

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

#: How much of a repository's kept paths is written and read.
MAX_BYTES = 1024 * 1024
#: How many of a repository's kept paths are read.
MAX_PATHS = 5000

# CommonMark's: an ATX heading and a fence's marker, each indented at most three spaces.
_HEADING_RE = re.compile(r" {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*#*[ \t]*$")
_FENCE_RE = re.compile(r" {0,3}(`{3,}|~{3,})")
_STEP_RE = re.compile(r"step\s+\d+\b", re.IGNORECASE)
_STEP_LEVEL = 3
# An inline code span on one line: a run of backticks, its text, and a run of the same length.
_SPAN_RE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
# What may follow a path in a citation: a line, a range, a column, a GitHub anchor, or a test's name.
_CITED_RE = re.compile(r"(?:::.*|:L?\d+(?:[-:]L?\d+)?|#L\d+(?:-L?\d+)?)$")
_PATH_RE = re.compile(r"[\w.@+-]+(?:/[\w.@+-]+)*/?")


class Touched(NamedTuple):
    """A path a push touched, in the repository it touched it in."""

    repo: str
    path: str


@dataclass(frozen=True)
class Step:
    """One of a plan's `### Step N` sections, and the files it names."""

    #: Its heading's text, without the `###`: `Step 2: Add the command`.
    title: str
    #: The files it names, as written, each once, in the order it names them: its bare names only when touched.
    files: Sequence[str]


@dataclass(frozen=True)
class Untouched:
    """A step whose files the push left untouched, some or all of them."""

    step: Step
    #: Its files no touched path is, or is under, in the order the step names them.
    files: Sequence[str]


@dataclass(frozen=True)
class Coverage:
    """A push's paths against a plan's steps: what no step names, and what no push touched."""

    #: Every step the plan has, in order; none for a plan without `### Step N` sections.
    steps: Sequence[Step]
    #: The paths the push touched that no step names, by repository and path.
    unplanned: Sequence[Touched]
    #: Each step that names a file the push left untouched, in order.
    untouched: Sequence[Untouched]

    @property
    def names_files(self) -> bool:
        """Whether any step names a file: with none, every touched path is unplanned, which says nothing."""
        return any(step.files for step in self.steps)


def compare(text: str, touched: Iterable[Touched]) -> Coverage:
    """Set the paths a push `touched` against the files the steps of the plan `text` name.

    Returns:
        The plan's steps, the touched paths no step names, and each step whose named files went untouched.
    """
    found = sorted(set(touched))
    roots = {t.path for t in found if "/" not in t.path}
    steps: list[Step] = []
    untouched: list[Untouched] = []
    for title, names in _sections(text):
        files = [name for name in names if "/" in name or name in roots]
        step = Step(title=title, files=files)
        steps.append(step)
        missed = [name for name in files if not any(_covers(name, t) for t in found)]
        if missed:
            untouched.append(Untouched(step=step, files=missed))
    named = [name for step in steps for name in step.files]
    unplanned = [t for t in found if not any(_covers(name, t) for name in named)]
    return Coverage(steps=steps, unplanned=unplanned, untouched=untouched)


def path_for(log_path: str | Path, repo: str) -> Path:
    """Where a worker run keeps the paths its push touched in one repository: beside its log.

    Returns:
        `<id>.<repo>.paths` beside `log_path`. The file may not exist.
    """
    log = Path(log_path)
    return log.with_name(f"{log.stem}.{repo}.paths")


def keep(path: Path, names: str) -> None:
    """Write `names`, git's NUL-ended paths, to `path`, readable only by the operator, cut at the bound `read` reads."""
    logs.write_private(path, names[:MAX_BYTES])


def read(path: Path) -> list[str] | None:
    """Read the paths kept at `path`.

    Returns:
        The paths, at most `MAX_PATHS`, in the order git named them; None when the file is missing, a symlink, or not
        a regular file.
    """
    try:
        # Non-blocking, so a FIFO in the file's place cannot hold the read open; it is refused below.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        return None
    with os.fdopen(fd, "rb") as f:
        data = f.read(MAX_BYTES)
    if len(data) == MAX_BYTES:
        # `keep` cut it at the bound, so the last path may be cut short; drop it.
        data = data[: data.rfind(b"\0") + 1]
    return [name for name in data.decode("utf-8", errors="replace").split("\0") if name][:MAX_PATHS]


# Each `### Step N` section of `text`: its heading's text, and the paths its code spans name, each once.
def _sections(text: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    names: list[str] | None = None
    fence = ""
    for line in text.splitlines():
        marker = _FENCE_RE.match(line)
        if fence:
            if marker is not None and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence):
                fence = ""
            continue
        if marker is not None:
            fence = marker.group(1)
            continue
        heading = _HEADING_RE.match(line)
        if heading is not None and len(heading.group(1)) <= _STEP_LEVEL:
            title = (heading.group(2) or "").strip()
            # A step's heading starts its section; any other heading of its level or above ends it.
            names = [] if len(heading.group(1)) == _STEP_LEVEL and _STEP_RE.match(title) else None
            if names is not None:
                sections.append((title, names))
        if names is not None:
            names.extend(name for name in _paths(line) if name not in names)
    return sections


# The relative paths `line`'s inline code spans name, as the module docstring says.
def _paths(line: str) -> Iterable[str]:
    for span in _SPAN_RE.finditer(line):
        name = _CITED_RE.sub("", span.group(2).strip()).removeprefix("./")
        parts = name.rstrip("/").split("/")
        if name and _PATH_RE.fullmatch(name) and not {".", ".."} & set(parts):
            yield name


# Whether a step's `name` is the `touched` path, or a directory it is under, with or without its repository.
def _covers(name: str, touched: Touched) -> bool:
    stem = name.rstrip("/")
    spellings = (touched.path, f"{touched.repo}/{touched.path}")
    return any(path == stem or path.startswith(f"{stem}/") for path in spellings)
