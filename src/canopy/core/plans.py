"""Plans before implementing (DESIGN §25, ROADMAP M44): each plan's file on disk, and its row in the journal.

A plan's text is a markdown file of its own, `<state_dir>/plans/<KEY>/<run>.md`, named for the plan run that wrote it,
so the operator reads, greps, and edits it with their own tools. The journal's `plans` row holds what canopy decides
by: the plan's status, the file's hash as written, and the hash the operator approved. A ticket has at most one plan
that is not superseded, its current plan, waiting (`proposed`) or `approved`.

A file is written once and never overwritten or deleted: under a temporary name in the ticket's directory, then linked
to its own, which fails if the name is taken. `plans/` and each ticket's directory are operator-only, and one that is
not, or a symlink, refuses the write. Every read opens a regular file without following a link and takes at most
`MAX_CHARS` of UTF-8; its hash is of the whole file, so a file over the bound is not a plan and never matches a hash.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import secrets
import stat
from dataclasses import dataclass
from typing import IO, TYPE_CHECKING, Literal

from canopy.core import db, records
from canopy.core.conversation import KEY_RE, MAX_KEY, Refused
from canopy.core.vocab import PlanStatus

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

# What a planner can write in one message and an operator can read before approving (DESIGN §25, The prompt).
MAX_CHARS = 100_000
DIR_NAME = "plans"
# In a plan run's desk: the copy of the plan it replaces, which the planner reads, and the file it writes its plan to,
# the one file its definition lets it edit (DESIGN §25). `.agents/agents/canopy-planner.md` names `WRITTEN` too.
REPLACED = ".canopy-plan.md"
WRITTEN = ".canopy-new-plan.md"
# The most bytes `MAX_CHARS` characters of UTF-8 can take: one more and the file is over the bound however it decodes.
_MAX_BYTES = 4 * MAX_CHARS
_CHUNK = 64 * 1024

# Why a file is not a plan, as `canopy show` and the refusals say it.
type Problem = Literal["missing", "not a regular file", "unreadable", "not UTF-8", "empty", "over the bound"]


class PlanFileError(Exception):
    """A plan's file could not be written: a directory is not the operator's own, or the name is taken."""


@dataclass(frozen=True)
class Written:
    """A plan's file as written: its SHA-256, hex, and its size in bytes, which its row records."""

    sha256: str
    size: int


@dataclass(frozen=True)
class Reading:
    """A plan's file as read: its text when it is a plan, else why not; its hash and size whenever it could be read."""

    text: str | None
    sha256: str | None
    size: int | None
    problem: Problem | None


def path_for(state_dir: Path, key: str, run_id: int) -> Path:
    """Where the plan the run `run_id` wrote for `key` is kept. Built from the key and the id, never read from a row.

    Returns:
        `<state_dir>/plans/<key>/<run_id>.md`. The file may not exist.

    Raises:
        ValueError: `key` is not a ticket key, so it might hold a path separator or `..`.
    """
    if len(key) > MAX_KEY or KEY_RE.fullmatch(key) is None:
        raise ValueError(f"{key[:MAX_KEY]!r} is not a ticket key")
    return state_dir / DIR_NAME / key / f"{run_id}.md"


def write(state_dir: Path, key: str, run_id: int, text: str) -> Written:
    """Write the plan the run `run_id` wrote for `key` to its file, readable only by the operator.

    Returns:
        The file's hash and size, for its row.

    Raises:
        PlanFileError: `plans/` or the ticket's directory is a symlink, not a directory, or not the operator's alone; or
            the file's name is taken, by an earlier file or anything else, which is left as it is.
    """
    path = path_for(state_dir, key, run_id)
    data = text.encode("utf-8")
    plans_fd = _private_dir(None, state_dir / DIR_NAME)
    try:
        ticket_fd = _private_dir(plans_fd, key)
    finally:
        os.close(plans_fd)
    try:
        _link_new(ticket_fd, path.name, data)
    finally:
        os.close(ticket_fd)
    return Written(sha256=hashlib.sha256(data).hexdigest(), size=len(data))


def read(path: Path) -> Reading:
    """Read the plan at `path`, bounded, without following a link at it.

    Returns:
        Its text when the file is a regular file of non-blank UTF-8 within `MAX_CHARS`; else why it is not. The hash
        and size are of the whole file, set whenever it could be read.
    """
    try:
        # Non-blocking, so a FIFO in the plan's place cannot hold the read open; it is refused below.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return Reading(None, None, None, "missing")
    except OSError:
        # A symlink at `path` fails with ELOOP; anything else is unreadable.
        kind: Problem = "not a regular file" if path.is_symlink() else "unreadable"
        return Reading(None, None, None, kind)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        return Reading(None, None, None, "not a regular file")
    with os.fdopen(fd, "rb") as f:
        try:
            head, digest, size = _hashed(f)
        except OSError:
            return Reading(None, None, None, "unreadable")
    problem: Problem | None = None
    text: str | None = None
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError:
        # A file cut at the bound may end mid-character; it is over the bound either way.
        problem = "over the bound" if size > _MAX_BYTES else "not UTF-8"
    if text is not None and (size > _MAX_BYTES or len(text) > MAX_CHARS):
        problem = "over the bound"
    elif text is not None and not text.strip():
        problem = "empty"
    return Reading(text if problem is None else None, digest, size, problem)


def record(conn: sqlite3.Connection, key: str, run_id: int, written: Written) -> records.Plan:
    """Record the plan the run `run_id` wrote for `key`, after its file, as `proposed`. It supersedes the current one.

    Returns:
        The plan's row.
    """
    with db.transaction(conn):
        supersede(conn, key)
        [plan] = records.fetch_all(
            conn,
            records.Plan,
            "INSERT INTO plans (ticket_key, run_id, created_at, status, sha256, size) VALUES (?, ?, ?, ?, ?, ?) "
            "RETURNING *",
            (key, run_id, db.now(), PlanStatus.PROPOSED, written.sha256, written.size),
        )
    return plan


def current(conn: sqlite3.Connection, key: str) -> records.Plan | None:
    """The ticket's current plan: the one not superseded, waiting or approved.

    Returns:
        The plan's row, or None when the ticket has none.
    """
    return records.fetch_one(
        conn, records.Plan, "SELECT * FROM plans WHERE ticket_key = ? AND status != ?", (key, PlanStatus.SUPERSEDED)
    )


def history(conn: sqlite3.Connection, key: str) -> list[records.Plan]:
    """Every plan of the ticket, superseded ones included.

    Returns:
        The plans' rows, oldest first.
    """
    return records.fetch_all(conn, records.Plan, "SELECT * FROM plans WHERE ticket_key = ? ORDER BY id", (key,))


def approve(conn: sqlite3.Connection, state_dir: Path, key: str, *, channel: str) -> records.Plan:
    """Approve the ticket's current plan as its file stands now, the operator's edits included, recording its hash.

    The operator's verbs check the rest first: that no agent run is asking (`inside_run`), and that no plan run for the
    ticket is running.

    Returns:
        The approved plan's row.

    Raises:
        Refused: (`bad_plan`) the ticket has no current plan; it is approved and its file has not changed since; or its
            file is missing, not a regular file, unreadable, or no longer a plan.
    """
    with db.transaction(conn):
        plan = current(conn, key)
        if plan is None:
            raise Refused("bad_plan", f"{key} has no plan waiting to be approved")
        path = path_for(state_dir, key, plan.run_id)
        reading = read(path)
        if plan.status is PlanStatus.APPROVED and reading.sha256 == plan.approved_sha256:
            raise Refused("bad_plan", f"plan {plan.id} of {key} is approved, and its file has not changed since")
        if reading.problem is not None:
            raise Refused("bad_plan", f"plan {plan.id}'s file {path} is {reading.problem}, so it cannot be approved")
        [approved] = records.fetch_all(
            conn,
            records.Plan,
            "UPDATE plans SET status = ?, approved_sha256 = ?, approved_at = ?, approved_channel = ? WHERE id = ? "
            "RETURNING *",
            (PlanStatus.APPROVED, reading.sha256, db.now(), channel, plan.id),
        )
    return approved


def approved_text(state_dir: Path, plan: records.Plan) -> str | None:
    """The text of an approved plan, if its file still has the hash the operator approved.

    Returns:
        The text, or None when the plan is not approved or its file is missing, unreadable, or no longer as approved:
        what `implement` and `resume` refuse as `plan_changed`.
    """
    if plan.status is not PlanStatus.APPROVED:
        return None
    reading = read(path_for(state_dir, plan.ticket_key, plan.run_id))
    return reading.text if reading.sha256 == plan.approved_sha256 else None


def supersede(conn: sqlite3.Connection, key: str) -> int | None:
    """Supersede the ticket's current plan, waiting or approved, if it has one. Call inside a transaction.

    Returns:
        The superseded plan's id, or None when the ticket had no current plan.
    """
    row = conn.execute(
        "UPDATE plans SET status = ? WHERE ticket_key = ? AND status != ? RETURNING id",
        (PlanStatus.SUPERSEDED, key, PlanStatus.SUPERSEDED),
    ).fetchone()
    return int(row[0]) if row is not None else None


def _private_dir(parent_fd: int | None, path: Path | str) -> int:
    """Open the directory `path`, made operator-only if it is missing, refusing one that is not the operator's alone.

    With `parent_fd`, `path` is a name in that directory, so a directory swapped for a link after its parent was checked
    is never followed.

    Returns:
        A descriptor of the directory, which the caller closes.

    Raises:
        PlanFileError: `path` is a symlink, not a directory, or not private to the operator (`logs.private_dir`).
    """
    with contextlib.suppress(FileExistsError):
        os.mkdir(path, 0o700, dir_fd=parent_fd)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    except OSError as e:
        raise PlanFileError(f"{path} is not a directory canopy made: {e.strerror}") from None
    st = os.fstat(fd)
    if st.st_uid != os.getuid() or st.st_mode & 0o077:
        os.close(fd)
        raise PlanFileError(f"{path} is not private to you, so canopy writes no plan in it")
    return fd


def _link_new(dir_fd: int, name: str, data: bytes) -> None:
    """Write `data` to a new file `name` in the directory `dir_fd`: no reader sees half of it, and nothing is replaced.

    Raises:
        PlanFileError: `name` is taken.
    """
    temporary = f".{name}.{secrets.token_hex(8)}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dir_fd)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        # A link, not a rename: a rename would replace a file already at `name`.
        os.link(temporary, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd, follow_symlinks=False)
    except FileExistsError:
        raise PlanFileError(f"a plan named {name} is already there, so canopy leaves it as it is") from None
    finally:
        os.unlink(temporary, dir_fd=dir_fd)


def _hashed(f: IO[bytes]) -> tuple[bytes, str, int]:
    """Read all of `f`, hashing every byte and keeping the first `_MAX_BYTES` and one more.

    Returns:
        The bytes kept, the whole file's SHA-256, hex, and its size.
    """
    digest = hashlib.sha256()
    head = bytearray()
    size = 0
    while chunk := f.read(_CHUNK):
        digest.update(chunk)
        size += len(chunk)
        if len(head) <= _MAX_BYTES:
            head += chunk[: _MAX_BYTES + 1 - len(head)]
    return bytes(head), digest.hexdigest(), size
