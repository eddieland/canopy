"""The files an `implement` touched, held to the files its approved plan's steps name (DESIGN §25, §45). No model.

The planner's prompt asks each `### Step N: <what it does>` to name the files it adds or changes; the harness counted
the files a run's own change touched as it ended (`run_changes`). This holds the one to the other, in code: the files
touched that no step names, and the steps that name files none of which was touched. It is a reading for the operator,
beside the run's diff, and decides nothing.

A step names a file in a code span, as the prompt's examples cite `path` or `path:line`, and only so: prose is not
read for paths, nor is a fenced block, which may be a diagram or a sample. Conservatively, so a step is flagged only on
a path it surely names: a span with a `/` and a file name with an extension (`src/app.py`, `src/app.py:12`), or ending
in `/` for a directory, is a path the step names; any other span of a path's characters (`README.md`, `Makefile`, a
module's dotted name) counts only when a touched file matches it, and so can match but never flag. A named path matches
a touched file that is it or ends in it on a `/` (`core/app.py` matches `src/core/app.py`), or the file under its
repository's name (`web/src/app.ts` for `src/app.ts` in `web`), a directory every file under it; a renamed file
matches by its old path too. A step that names no file is neither flagged nor matched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import plans, records, run_changes
from canopy.core.vocab import RunKind

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Sequence
    from pathlib import Path

#: A step's heading, as the planner's prompt asks for it, `### Step N: <what it does>`, any one mark as the colon.
_STEP_RE = re.compile(r"###[ \t]+Step[ \t]+(\d+)\b[ \t]*[^\w\s(]?[ \t]*(.*)$", re.IGNORECASE)
#: A heading that ends a step's section: one of its level or above.
_ENDS_STEP_RE = re.compile(r"#{1,3}(?:[ \t]|$)")
#: A code span on one line.
_SPAN_RE = re.compile(r"(`+)([^`\n]+?)\1(?!`)")
#: A path's characters, its parts split on `/`, with a line or a range of lines after it, `:12` or `:12-30`.
_PATH_RE = re.compile(r"(?:\./)?([\w@+.-]+(?:/[\w@+.-]+)*/?)(?::\d+(?:-\d+)?)?")
#: A file name with an extension, `app.py`, `.editorconfig` not among them.
_FILE_RE = re.compile(r"[^/.][^/]*\.[A-Za-z0-9]+")


@dataclass(frozen=True)
class Touched:
    """A file a run's own change touched in one repository, as git counted it. The paths are the branch's text."""

    repo: str
    path: str
    #: The path it had before, when git found it renamed.
    old_path: str | None = None


@dataclass(frozen=True)
class Step:
    """A step of a plan, by its heading: `### Step 2: Wire the button` is step 2, `Wire the button`."""

    number: int
    #: Its title, printable, cut at `plans.MAX_HEADING` characters.
    title: str


@dataclass(frozen=True)
class Held:
    """A run's touched files held to its plan's steps."""

    #: The files touched that no step names, in the order given.
    unnamed: Sequence[Touched]
    #: The steps that surely name a file, none of whose files was touched, in the plan's order.
    untouched: Sequence[Step]


@dataclass(frozen=True)
class Checked:
    """An `implement`'s files held to the approved plan it followed, or why they could not be."""

    #: The plan the run followed.
    plan_id: int
    #: What holding them found; None when it could not be done.
    held: Held | None = None
    #: Why they could not be held; None when they were.
    unchecked: str | None = None


def of_run(conn: sqlite3.Connection, state_dir: Path, run_id: int) -> Checked | None:
    """Hold what `implement` run `run_id` changed to the approved plan it followed, read from its file.

    Returns:
        What holding them found, or why it could not be done: the plan's file is no longer as approved, or canopy
        counted not every file the run touched. None for a run of another kind, one that followed no plan, and one
        that recorded no count of what it changed, as one still running, crashed, or closed by reconcile.
    """
    run = records.select(records.Run).where("id = ?", run_id).one(conn)
    if run is None or run.kind is not RunKind.IMPLEMENT or run.plan_id is None:
        return None
    changes = [c for c in run_changes.of_run(conn, run_id) if c.files_changed is not None]
    if not changes:
        return None
    touched: list[Touched] = []
    for c in changes:
        files = run_changes.files_of(conn, run_id, c.repo)
        if len(files) < (c.files_changed or 0):
            why = f"the run touched {c.files_changed} files in {c.repo}, more than canopy keeps the names of"
            return Checked(run.plan_id, unchecked=why)
        touched.extend(Touched(c.repo, f.path, f.old_path) for f in files)
    plan = records.select(records.Plan).where("id = ?", run.plan_id).one(conn)
    reading = plans.read(plans.path_for(state_dir, plan.ticket_key, plan.run_id)) if plan is not None else None
    if plan is None or reading is None or reading.text is None or reading.sha256 != plan.approved_sha256:
        why = f"plan {run.plan_id}'s file is missing, unreadable, or no longer as the operator approved it"
        return Checked(run.plan_id, unchecked=why)
    return Checked(run.plan_id, held=held(reading.text, touched))


def held(text: str, touched: Iterable[Touched]) -> Held:
    """Hold the files a run touched to the files the steps of the plan `text` name.

    Returns:
        The files touched that no step names, and the steps that surely name a file none of whose files was touched.
    """
    touched = tuple(touched)
    named_any: set[Touched] = set()
    untouched: list[Step] = []
    for step, spans in steps(text):
        matched = {t for t in touched for span in spans if _matches(span, t)}
        named_any |= matched
        if not matched and any(_sure(span) for span in spans):
            untouched.append(step)
    return Held(unnamed=tuple(t for t in touched if t not in named_any), untouched=tuple(untouched))


def steps(text: str) -> list[tuple[Step, list[str]]]:
    """A plan's steps, each with the spans of a path's characters its section holds, its heading's included.

    A step's section runs from its heading to the next heading of its level or above, outside fenced code.

    Returns:
        Each step in the plan's order, with its spans, a leading `./` and a line's or a range's `:12` dropped.
    """
    found: list[tuple[Step, list[str]]] = []
    spans: list[str] | None = None
    for line in plans.unfenced(text):
        heading = plans.heading_of(line)
        if heading is not None and _ENDS_STEP_RE.match(heading):
            spans = None
            step = _STEP_RE.match(heading)
            if step is not None:
                spans = []
                title = step.group(2).rstrip(" #")[: plans.MAX_HEADING]
                found.append((Step(int(step.group(1)), title), spans))
        if spans is not None:
            spans.extend(_spans(line))
    return found


def _spans(line: str) -> list[str]:
    """Return the code spans of `line` made of a path's characters, as paths, none climbing out with `..`."""
    found: list[str] = []
    for span in _SPAN_RE.finditer(line):
        path = _PATH_RE.fullmatch(span.group(2).strip())
        if path is not None and not {".", ".."} & set(path.group(1).rstrip("/").split("/")):
            found.append(path.group(1))
    return found


def _sure(span: str) -> bool:
    """Return whether a span surely names a path: a file with an extension below a directory, or a directory."""
    if span.endswith("/"):
        return True
    return "/" in span and _FILE_RE.fullmatch(span.rsplit("/", 1)[1]) is not None


def _matches(span: str, touched: Touched) -> bool:
    """Return whether a span names a touched file: by its path or its old path, under its repository's name or not."""
    for path in (touched.path, touched.old_path):
        if path is None:
            continue
        for full in (path, f"{touched.repo}/{path}"):
            # A directory names every file under it; a file, the path it is or ends in on a `/`.
            if span.endswith("/"):
                if f"/{span}" in f"/{full}":
                    return True
            elif full == span or full.endswith(f"/{span}"):
                return True
    return False
