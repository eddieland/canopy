"""Attachments (DESIGN §22): text files the operator attaches to a ticket or a task, for its runs to read as data.

What a person sent the operator, such as a design doc, reaches a run only this way: through the operator's channels,
the CLI and the web UI behind the listener secret, refused inside a tick or any agent's run (TRUST_MODEL T1), on a
ticket canopy knows or a task not stopped. Its text is data, never an instruction: the operator's words about it are a
reply or the task's text. Attachments are held to `policy`'s limits in code, each file's size and how many and how much
a subject holds at once, and to plain text: UTF-8, with no NUL, never blank.

The text is kept beside the journal, as a plan is (§25): `<state_dir>/attachments/<kind>.<id>/<attachment>.txt`, written
once, readable only by the operator, its path built from ids and never read from a row. Its row holds the name runs see
it as, unique among the subject's attachments, and its hash. Removing one deletes its file and keeps its row, so the
journal still says what was attached, when, and what it hashed to.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import shutil
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import PurePath
from typing import TYPE_CHECKING, Final

from canopy.core import conversation, db, plans, records, sql
from canopy.core.conversation import KEY_RE, MAX_KEY, Refused
from canopy.infra import logs

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from canopy.core.config import Policy
    from canopy.core.conversation import Ref

#: An attachment's name, as runs see it: a plain file name of letters, digits, `.`, `_`, and `-`, at most 100
#: characters, starting with a letter or digit, so it is never hidden, `..`, or a path.
NAME_RE: Final = re.compile(r"(?=[A-Za-z0-9._-]{1,100}\Z)[A-Za-z0-9][A-Za-z0-9._-]*")
#: Where attachments are kept, under the state directory, each subject's in a directory of its own.
DIR_NAME: Final = "attachments"
#: The subjects that take attachments: a ticket, by its key, and a task, by its id.
KINDS: Final = (conversation.TICKET, conversation.TASK)
#: Where a run's copies of its subject's attachments go, at the root of its worktree, which git there ignores, or in its
#: desk: written for that run alone, and removed before its slot is returned (DESIGN §22).
RUN_DIR: Final = ".canopy-attachments"
KIB: Final = 1024
# What runs of any other character become in a name made from a file's, and the `-` such a run leaves before a `.` or at
# the end, which is dropped.
_UNNAMED_RE: Final = re.compile(r"[^A-Za-z0-9._-]+")
_LEFT_OVER_RE: Final = re.compile(r"-+(?=\.)|-+\Z")


class AttachmentFileError(Exception):
    """An attachment's file is gone, or is no longer the text the operator attached."""


@dataclass(frozen=True)
class Copy:
    """An attachment's text, read again for a run, under the name the run sees it as."""

    name: str
    text: str


@dataclass(frozen=True)
class Limits:
    """What one ticket's or task's attachments may hold, from `policy` (DESIGN §22)."""

    #: How many it may have at once; 0 refuses every attachment.
    files: int
    #: The most bytes one attachment's text holds.
    file_bytes: int
    #: The most bytes its attachments hold together.
    total_bytes: int

    @classmethod
    def from_policy(cls, policy: Policy) -> Limits:
        """Read the limits `policy` sets.

        Returns:
            The limits, in files and bytes.
        """
        return cls(
            files=policy.max_attachments,
            file_bytes=policy.max_attachment_kib * KIB,
            total_bytes=policy.max_attachments_total_kib * KIB,
        )


def attach(
    conn: sqlite3.Connection,
    state_dir: Path,
    ref: Ref,
    name: str,
    data: bytes,
    *,
    limits: Limits,
    channel: str,
) -> records.Attachment:
    """Attach the text `data` to the ticket or task `ref`, as `name`, for its later runs to read (DESIGN §22).

    A channel reads at most one byte past `limits.file_bytes` of a file, so a file over the bound is refused without
    being read whole.

    Returns:
        The attachment, as recorded.

    Raises:
        Refused: `inside_run` inside a tick or a run; `unsupported` for a subject that is not a ticket or a task;
            `unknown` for a ticket that was neither started nor seen by a tick, or a task canopy has no record of;
            `stopped` for a task the operator stopped; `bad_name` for a name that is not `NAME_RE`; `not_text` for data
            that is not UTF-8, or holds a NUL; `empty` for blank text; `too_large` for a file over the bound, or one
            that would take its subject's attachments over theirs; `too_many` for a subject at its count, or with
            attaching turned off; `taken` for a name one of the subject's attachments has.
        PlanFileError: the attachments' directory, or the subject's, is not the operator's alone; nothing is recorded.
        DatabaseError: the row was not recorded, which nothing but a broken journal does.
    """
    conversation.check_operator()
    conversation.check_verb(ref, "attach")
    text = _text(name, data, limits)
    with db.transaction(conn):
        conversation.check_subject(conn, ref)
        _check_room(of(conn, ref), ref, name, len(data), limits)
        insert = sql.insert(
            "attachments",
            subject_kind=ref.kind,
            subject_id=ref.id,
            name=name,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            channel=channel,
            added_at=db.now(),
        )
        attachment_id = int(sql.execute(conn, insert).lastrowid or 0)
        # No row is ever deleted, so an id is taken again only after a transaction that took it rolled back: a file
        # already at it is one that transaction wrote, never an attachment's.
        with contextlib.suppress(FileNotFoundError):
            (state_dir / DIR_NAME / _dir_name(ref) / _file_name(attachment_id)).unlink()
        # Written inside the transaction, so a file that cannot be written records nothing.
        plans.write_new(state_dir / DIR_NAME, _dir_name(ref), _file_name(attachment_id), text, what="attachment")
        found = get(conn, attachment_id)
    if found is None:
        raise sqlite3.DatabaseError("the attachment's row was not recorded")
    return found


def remove(conn: sqlite3.Connection, state_dir: Path, ref: Ref, name: str, *, channel: str) -> records.Attachment:
    """Remove the attachment `name` from `ref`: its file is deleted, and its row kept, marked removed (DESIGN §22).

    A run already started keeps the copy it was given. The file is deleted once the removal is recorded, so a file
    that cannot be deleted is left behind, logged, rather than an attachment whose file is gone.

    Returns:
        The attachment, as removed.

    Raises:
        Refused: `inside_run` inside a tick or a run; `unsupported` for a subject that is not a ticket or a task;
            `unknown` for a subject with no attachment of that name.
        DatabaseError: the row went missing, which nothing but a broken journal does.
    """
    conversation.check_operator()
    conversation.check_verb(ref, "detach")
    with db.transaction(conn):
        found = next((a for a in of(conn, ref) if a.name == name), None)
        if found is None:
            raise Refused("unknown", f"{ref} has no attachment named {name[:100]!r}")
        update = sql.update("attachments").set(removed_at=db.now(), removed_channel=channel).where("id = ?", found.id)
        sql.execute(conn, update)
        removed = get(conn, found.id)
    if removed is None:
        raise sqlite3.DatabaseError("the attachment's row went missing")
    try:
        path(state_dir, removed).unlink(missing_ok=True)
    except OSError as e:
        fields = {"subject": str(ref), "attachment": removed.id, "error": str(e)}
        logs.for_tick(None).warning("removed attachment's file not deleted", extra=fields)
    return removed


def of(conn: sqlite3.Connection, ref: Ref) -> list[records.Attachment]:
    """Return the attachments `ref` holds now, the first attached first: none that was removed.

    Returns:
        The attachments, in the order they were attached.
    """
    query = (
        sql.select("*")
        .from_("attachments")
        .where("subject_kind = ? AND subject_id = ? AND removed_at IS NULL", ref.kind, ref.id)
        .order_by("id")
    )
    return records.fetch_all(conn, records.Attachment, query)


def get(conn: sqlite3.Connection, attachment_id: int) -> records.Attachment | None:
    """Return attachment `attachment_id`, removed or not, or None if there is none."""
    query = sql.select("*").from_("attachments").where("id = ?", attachment_id)
    return records.fetch_one(conn, records.Attachment, query)


def path(state_dir: Path, attachment: records.Attachment) -> Path:
    """Where an attachment's text is kept. Built from its subject and id, which are checked, never read as a path.

    Returns:
        `<state_dir>/attachments/<kind>.<id>/<attachment id>.txt`. The file may not exist.

    Raises:
        ValueError: the attachment's subject is not a ticket's key or a task's id.
    """
    subject = conversation.Ref(attachment.subject_kind, attachment.subject_id)
    return state_dir / DIR_NAME / _dir_name(subject) / _file_name(attachment.id)


def name_from(file_name: str) -> str | None:
    """Make an attachment's name from a file's: its last part, each run of other characters made `-`, cut to fit.

    A channel that is not given a name uses this one, so `Design doc (v2).md` is attached as `Design-doc-v2.md`.

    Returns:
        The name, or None when nothing of the file's name is left to name it by.
    """
    plain = _UNNAMED_RE.sub("-", PurePath(file_name.replace("\\", "/")).name)
    made = _LEFT_OVER_RE.sub("", plain).lstrip("._-")[:100]
    return made if NAME_RE.fullmatch(made) else None


def held_at(conn: sqlite3.Connection, ref: Ref, at: str) -> list[records.Attachment]:
    """Return the attachments `ref` holds now that it already held at `at`: what a run dispatched then was told of.

    Returns:
        The attachments, in the order they were attached.
    """
    return [a for a in of(conn, ref) if a.added_at <= at]


def copies(conn: sqlite3.Connection, state_dir: Path, ref: Ref, at: str) -> list[Copy]:
    """Read again the text of each attachment a run of `ref` dispatched at `at` was told of, and `ref` still holds.

    One the operator removed since is left out: the run's prompt names it, but nothing is copied for it.

    Returns:
        The copies, in the order they were attached.

    Raises:
        AttachmentFileError: an attachment's file is gone or changed since it was attached; the run gets none.
    """
    found: list[Copy] = []
    for attachment in held_at(conn, ref, at):
        text = read(state_dir, attachment)
        if text is None:
            where = path(state_dir, attachment)
            raise AttachmentFileError(f"attachment {attachment.name}'s file {where} is not the text attached")
        found.append(Copy(attachment.name, text))
    return found


def read(state_dir: Path, attachment: records.Attachment) -> str | None:
    """Read an attachment's text, bounded by its recorded size, without following a link at its file.

    Returns:
        The text, when the file is a regular file of exactly the bytes recorded; else None.
    """
    try:
        # Non-blocking, so a FIFO in the file's place cannot hold the read open; it is refused below.
        fd = os.open(path(state_dir, attachment), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            return None
        data = f.read(attachment.size + 1)
    if len(data) != attachment.size or hashlib.sha256(data).hexdigest() != attachment.sha256:
        return None
    return data.decode("utf-8")


def place(directory: Path, found: Sequence[Copy]) -> None:
    """Write `found` into `directory`, made afresh and readable only by the operator, for one run (DESIGN §22).

    Whatever was at `directory` is removed first (`clear`), so a run never reads an earlier run's copies.

    Raises:
        OSError: the directory or a copy could not be written.
    """
    clear(directory)
    directory.mkdir(mode=0o700)
    for copy in found:
        logs.write_private(directory / copy.name, copy.text)


def clear(directory: Path) -> None:
    """Remove a run's copies at `directory`, never following a link: a link, or anything else, in its place goes too.

    Raises:
        OSError: something at `directory` could not be removed.
    """
    if directory.is_dir() and not directory.is_symlink():
        # rmtree removes a link inside the directory, never what it names.
        shutil.rmtree(directory)
    elif directory.is_symlink() or directory.exists():
        directory.unlink()


def sizes(found: Sequence[records.Attachment]) -> list[tuple[str, str]]:
    """Name each attachment with its size, as a prompt lists them (`prompts.attachments_note`).

    Returns:
        Each one's name and `size_text`.
    """
    return [(a.name, size_text(a.size)) for a in found]


def size_text(size: int) -> str:
    """Say how large `size` bytes are, in KiB from one KiB up.

    Returns:
        `12 KiB`, `12.5 KiB`, or `300 bytes`.
    """
    if size % KIB == 0:
        return f"{size // KIB} KiB"
    return f"{size / KIB:.1f} KiB" if size > KIB else f"{size} bytes"


def _text(name: str, data: bytes, limits: Limits) -> str:
    """Check what the operator would attach as `name`, alone: its name, its size, and that it is plain text.

    Returns:
        Its text.

    Raises:
        Refused: what `attach` says of `bad_name`, `too_large` for the file alone, `not_text`, `empty`, and `too_many`
            with attaching turned off.
    """
    if not NAME_RE.fullmatch(name):
        raise Refused("bad_name", f"{name[:100]!r} is not a plain file name: letters, digits, `.`, `_`, and `-`")
    if limits.files == 0:
        raise Refused("too_many", "attaching is off: policy.max_attachments is 0")
    if len(data) > limits.file_bytes:
        raise Refused("too_large", f"{name} is over the {size_text(limits.file_bytes)} one attachment may hold")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Refused("not_text", f"{name} is not UTF-8 text; export it as Markdown or plain text") from None
    if "\0" in text:
        raise Refused("not_text", f"{name} holds a NUL byte, so it is not plain text")
    if not text.strip():
        raise Refused("empty", f"{name} is empty")
    return text


def _check_room(held: Sequence[records.Attachment], ref: Ref, name: str, size: int, limits: Limits) -> None:
    """Check that `ref`, holding `held`, has room for one more attachment, `name` of `size` bytes.

    Raises:
        Refused: `too_many` at its count, `taken` for a name it has, and `too_large` past its total.
    """
    if len(held) >= limits.files:
        raise Refused("too_many", f"{ref} has {len(held)} attachments, the most it may hold; remove one first")
    if any(a.name == name for a in held):
        raise Refused("taken", f"{ref} already has an attachment named {name}; remove it first, or pick a name")
    total = sum(a.size for a in held) + size
    if total > limits.total_bytes:
        raise Refused(
            "too_large",
            f"{ref}'s attachments would hold {size_text(total)}, over the {size_text(limits.total_bytes)} they may "
            "together",
        )


def _dir_name(ref: Ref) -> str:
    """The directory a subject's attachments are kept in, under `attachments/`: `ticket.<key>` or `task.<id>`.

    A ticket's key holds no `.`, so no two subjects share one.

    Returns:
        The directory's name.

    Raises:
        ValueError: `ref` is not a ticket's key or a task's id, so it might hold a path separator or `..`.
    """
    if ref.kind == conversation.TICKET and len(ref.id) <= MAX_KEY and KEY_RE.fullmatch(ref.id):
        return f"{ref.kind}.{ref.id}"
    if ref.kind == conversation.TASK and ref.id.isascii() and ref.id.isdigit():
        return f"{ref.kind}.{int(ref.id)}"
    raise ValueError(f"{str(ref)[:MAX_KEY]!r} is not a ticket or a task")


def _file_name(attachment_id: int) -> str:
    return f"{attachment_id}.txt"
