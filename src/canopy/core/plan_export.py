"""Plans exported into a directory of the operator's, each with what the journal records of it (DESIGN §25).

`export` writes every plan and feedback plan the journal records, superseded ones included, to `<dest>/<KEY>/<run>.md`,
the path its file has under the state directory: a front matter of its row, then its file as it stands now. The row is
what a copy of `plans/` alone would lose: whether the plan was approved, by whom, and as which hash.

An export is the same bytes for the same plan and row, so a file is rewritten only when its plan's file or row changed,
and a git repository at `dest` sees a change only where there is one. Nothing in `dest` is ever removed, and a plan
whose file is missing or no plan is left as it was exported before, if it was. A file is written under a temporary
name, then renamed into place, so no reader sees half of one and a link at its name is replaced, never followed.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import os
import secrets
import stat
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from canopy.core import plans, records, sql

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence
    from pathlib import Path

#: Which of a ticket's plans a file is: the plan before its implement (§25), or one before a resume (§32).
type Kind = Literal["plan", "feedback plan"]

_DIR_MODE = 0o700
_FILE_MODE = 0o600
_FRONT_MATTER = "---\n"


@dataclass(frozen=True)
class Skipped:
    """A plan not exported: its file under the state directory is not a plan, and why."""

    kind: Kind
    ticket_key: str
    run_id: int
    problem: plans.Problem


@dataclass(frozen=True)
class Exported:
    """What an export did."""

    #: The files it wrote, new or changed, relative to `dest`.
    written: Sequence[str]
    #: How many plans it found already exported as they stand.
    unchanged: int
    #: The plans it could not export.
    skipped: Sequence[Skipped]


class ExportError(Exception):
    """A plan could not be written into `dest`: a ticket's directory there is a link, or a write failed."""


def export(conn: sqlite3.Connection, state_dir: Path, dest: Path) -> Exported:
    """Export every plan and feedback plan in the journal into `dest`, made operator-only if it is missing.

    Returns:
        The files written, how many were already as they stand, and the plans whose files are not plans.

    Raises:
        ExportError: `dest`, or a ticket's directory in it, is a link or not a directory, or a file could not be
            written.
    """
    rows: list[tuple[Kind, records.Plan | records.FeedbackPlan]] = [
        *(("plan", p) for p in records.fetch_all(conn, records.Plan, sql.select("*").from_("plans"))),
        *(
            ("feedback plan", p)
            for p in records.fetch_all(conn, records.FeedbackPlan, sql.select("*").from_("feedback_plans"))
        ),
    ]
    rows.sort(key=lambda kind_row: (kind_row[1].ticket_key, kind_row[1].run_id))
    written: list[str] = []
    skipped: list[Skipped] = []
    unchanged = 0
    try:
        dest.mkdir(mode=_DIR_MODE, parents=True, exist_ok=True)
    except OSError as e:
        raise ExportError(f"{dest} is not a directory canopy can export into: {e.strerror}") from None
    for kind, row in rows:
        source = plans.path_for(state_dir, row.ticket_key, row.run_id)
        reading = plans.read(source)
        if reading.text is None:
            # A reading without text always says why; "unreadable" only satisfies the type.
            skipped.append(Skipped(kind, row.ticket_key, row.run_id, reading.problem or "unreadable"))
            continue
        if _write_if_changed(dest, row.ticket_key, source.name, document(kind, row, reading.text)):
            written.append(f"{row.ticket_key}/{source.name}")
        else:
            unchanged += 1
    return Exported(written=written, unchanged=unchanged, skipped=skipped)


def document(kind: Kind, row: records.Plan | records.FeedbackPlan, text: str) -> bytes:
    """A plan as it is exported: a front matter of its kind and its row's columns that are set, then its text.

    Each value is written as JSON, which YAML reads as the same string or number, so a reason the planner wrote cannot
    end the front matter or add a key to it.

    Returns:
        The file's bytes, UTF-8.
    """
    lines = [_FRONT_MATTER, f"kind: {json.dumps(kind)}\n"]
    for field in dataclasses.fields(row):
        value: object = getattr(row, field.name)
        if value is not None:
            lines.append(f"{field.name}: {json.dumps(value)}\n")
    lines.extend([_FRONT_MATTER, "\n", text])
    return "".join(lines).encode("utf-8")


def _write_if_changed(dest: Path, key: str, name: str, data: bytes) -> bool:
    """Write `data` to `<dest>/<key>/<name>` unless it holds exactly that already.

    Returns:
        Whether the file was written.

    Raises:
        ExportError: the ticket's directory is a link or not a directory, or the file could not be written.
    """
    try:
        (dest / key).mkdir(mode=_DIR_MODE, exist_ok=True)
        dir_fd = os.open(dest / key, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as e:
        raise ExportError(f"{dest / key} is not a directory canopy can export into: {e.strerror}") from None
    try:
        if _holds(dir_fd, name, data):
            return False
        temporary = f".{name}.{secrets.token_hex(8)}.tmp"
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, _FILE_MODE, dir_fd=dir_fd)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            # A rename replaces the name itself, never what a link there names.
            os.rename(temporary, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        except OSError as e:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=dir_fd)
            raise ExportError(f"{dest / key / name} was not written: {e.strerror}") from None
        return True
    finally:
        os.close(dir_fd)


def _holds(dir_fd: int, name: str, data: bytes) -> bool:
    """Whether `name` in the directory `dir_fd` is a regular file holding exactly `data`, read without following a link.

    Returns:
        False when it is missing, a link, not a regular file, unreadable, or holds anything else.
    """
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    except OSError:
        return False
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            return False
        # One byte past `data` tells a longer file apart without reading the rest of it.
        return f.read(len(data) + 1) == data
