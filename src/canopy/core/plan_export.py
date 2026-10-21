"""Plans exported into a directory of the operator's, each with what the journal records of it (DESIGN §25).

`export` writes every plan and feedback plan the journal records, superseded ones included, to `<dest>/<KEY>/`: a front
matter of its row, then its file as it stands now. The row is what a copy of `plans/` alone would lose: whether the plan
was approved, by whom, and as which hash. The file's name says which plan it is and where it stands, so a listing reads
without opening one: its run, its status, then its title as a slug (`name`), as `412-approved-export-reports-as-csv.md`.

An export is the same bytes for the same plan and row, so a file is rewritten only when its plan's file or row changed,
and a git repository at `dest` sees a change only where there is one. When a plan's status or title changes, so does its
name: the export writes the new name, then removes the plan's file under any name it had before, and nothing else, so
git sees a rename. A plan whose file is missing or no plan is left as it was exported before, if it was. A file is
written under a temporary name, then renamed into place, so no reader sees half of one and a link at its name is
replaced, never followed.

A history of thousands of plans is exported each tick, so an export reads only what may have changed: for each plan it
found exported as it stands, it keeps a fingerprint of its row and of both files' stat in the state directory, and
next time skips a plan whose fingerprint still matches with a stat of each file and no read (`_Seen`). With `limit`,
it stops once it has written that many files, so a long history goes in over several exports.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import itertools
import json
import os
import re
import secrets
import stat
import time
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Self

from canopy.core import plans, records, sql
from canopy.core.vocab import PlanStatus

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator, Mapping, Sequence
    from pathlib import Path

#: Which of a ticket's plans a file is: the plan before its implement (§25), or one before a resume (§32).
type Kind = Literal["plan", "feedback plan"]

#: Where, under the state directory, each destination's fingerprints are kept (`_Seen`), one file for each.
SEEN_DIR = "plan-exports"
_DIR_MODE = 0o700
_FILE_MODE = 0o600
_FRONT_MATTER = "---\n"
# Bumped whenever `document` or `name` changes, so every plan exported before is read and compared again.
_FORMAT = 2
# The most characters of a title a file's name carries.
_MAX_SLUG = 60
# What a planner's heading opens with before the ticket's title (the plan prompts' outline): `Plan: KEY`.
_HEADING_PREFIX = re.compile(r"(?:feedback\s+)?plan(?:\s*:|\s*$)\s*", re.IGNORECASE)
# How long before an export a file must have last changed for its stat to stand for its bytes. A file changed in the
# same tick of the filesystem's clock as it was read can change again with the same stat, git's "racily clean" case.
_SETTLED_NS = 2_000_000_000


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
    #: How many plans it left unchecked, having written its `limit` of files first.
    left: int = 0
    #: The files it removed, relative to `dest`: each a plan's earlier name, the plan now under a new one.
    removed: Sequence[str] = dataclasses.field(default_factory=list[str])


class ExportError(Exception):
    """A plan could not be written into `dest`: a ticket's directory there is a link, or a write failed."""


def export(conn: sqlite3.Connection, state_dir: Path, dest: Path, *, limit: int | None = None) -> Exported:
    """Export every plan and feedback plan in the journal into `dest`, made operator-only if it is missing.

    With `limit`, stop once that many files are written; the plans after them are left for the next export.

    Returns:
        The files written and removed, how many were already as they stand, the plans whose files are not plans, and
        how many plans `limit` left unchecked.

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
    tally = _Tally()
    checked = 0
    # Before any file is read: one changed after this is never taken as settled.
    settled_before = time.time_ns() - _SETTLED_NS
    with _dest_dir(dest) as dest_fd, _Seen.of(state_dir, dest) as seen:
        for key, group in itertools.groupby(rows, key=lambda kind_row: kind_row[1].ticket_key):
            if limit is not None and len(tally.written) >= limit:
                break
            source_dir = plans.dir_for(state_dir, key)
            with _source_dir(source_dir) as source_fd, _ticket_dir(dest_fd, dest / key) as dir_fd:
                dirs = _Dirs(key, source_dir, source_fd, dest / key, dir_fd, _list(dir_fd))
                for kind, row in group:
                    if limit is not None and len(tally.written) >= limit:
                        break
                    checked += 1
                    _export_plan(kind, row, dirs, seen, tally, settled_before=settled_before)
    return Exported(
        written=tally.written,
        unchanged=tally.unchanged,
        skipped=tally.skipped,
        left=len(rows) - checked,
        removed=tally.removed,
    )


def name(kind: Kind, row: records.Plan | records.FeedbackPlan, text: str) -> str:
    """A plan's file name in an export: its run, its status, `feedback` for a feedback plan, and its title's slug.

    The title is the plan's first `# ` heading, less the `Plan: KEY` the planner opens it with. A plan is model text
    (TRUST_MODEL T1), so its slug holds only lowercase letters, digits, and single hyphens, and is cut short; a plan
    with no title past that prefix has none in its name.

    Returns:
        The name, as `412-approved-export-reports-as-csv.md`.
    """
    parts = [str(row.run_id), row.status.value]
    if kind == "feedback plan":
        parts.append("feedback")
    slug = _slug(_title(text, row.ticket_key))
    if slug:
        parts.append(slug)
    return "-".join(parts) + ".md"


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


@dataclass(frozen=True)
class _Dirs:
    """Where one ticket's plans are read from, under the state directory, and exported to."""

    key: str
    source: Path
    #: The source directory's descriptor, to stat its files; None when it could not be opened.
    source_fd: int | None
    dest: Path
    dest_fd: int
    #: The names in `dest` as the ticket's export began.
    listing: Sequence[str]


@dataclass
class _Tally:
    """What an export has done so far, kept as it goes."""

    written: list[str] = dataclasses.field(default_factory=list[str])
    removed: list[str] = dataclasses.field(default_factory=list[str])
    skipped: list[Skipped] = dataclasses.field(default_factory=list[Skipped])
    unchanged: int = 0


def _export_plan(
    kind: Kind,
    row: records.Plan | records.FeedbackPlan,
    dirs: _Dirs,
    seen: _Seen,
    tally: _Tally,
    *,
    settled_before: int,
) -> None:
    """Export one plan into its ticket's directory, unless it is there as it stands, and remove its earlier names.

    Raises:
        ExportError: its file could not be written, or an earlier one removed.
    """
    plan = f"{dirs.key}/{row.run_id}"
    source_name = plans.file_name(row.run_id)
    # Every name this plan's file has in `dest`: one, unless its status or title changed since.
    names = [n for n in dirs.listing if _is_name_of(row.run_id, n)]
    # Each stat before its file is read, so a change after the read shows on the next export.
    source_stat = None if dirs.source_fd is None else _stat(source_name, dirs.source_fd)
    if len(names) == 1:
        exported = _stat(names[0], dirs.dest_fd)
        if seen.matches(plan, kind, row, source=source_stat, exported_name=names[0], exported=exported):
            tally.unchanged += 1
            return
    reading = plans.read(dirs.source / source_name)
    if reading.text is None:
        # A reading without text always says why; "unreadable" only satisfies the type.
        tally.skipped.append(Skipped(kind, dirs.key, row.run_id, reading.problem or "unreadable"))
        return
    exported_name = name(kind, row, reading.text)
    data = document(kind, row, reading.text)
    held = _held(dirs.dest_fd, exported_name, data)
    if held is None:
        _write(dirs.dest_fd, dirs.dest / exported_name, data)
        tally.written.append(f"{dirs.key}/{exported_name}")
    else:
        tally.unchanged += 1
    # Only once the plan is in place under its name, so a failed write leaves it under the earlier one.
    for earlier in names:
        if earlier != exported_name:
            _remove(dirs.dest_fd, dirs.dest / earlier)
            tally.removed.append(f"{dirs.key}/{earlier}")
    if held is not None:
        seen.record(
            plan,
            kind,
            row,
            source=source_stat,
            exported_name=exported_name,
            exported=held,
            settled_before=settled_before,
        )


def _title(text: str, key: str) -> str:
    """The plan's title: its first `# ` heading, less a leading `Plan:` or `Feedback plan:` and the ticket's key.

    Returns:
        The title, or "" when the plan has no such heading or nothing past its prefix.
    """
    heading = next((line[2:] for line in text.splitlines() if line.startswith("# ")), "")
    title = _HEADING_PREFIX.sub("", heading.strip().rstrip("#").strip(), count=1)
    # The key alone, never the start of a longer one: `PROJ-1` stays in `PROJ-12`.
    return re.sub(rf"^{re.escape(key)}(?![A-Za-z0-9])", "", title, flags=re.IGNORECASE)


def _slug(title: str) -> str:
    """`title` in lowercase ASCII letters and digits, each run of anything else one hyphen, at most `_MAX_SLUG` long.

    Returns:
        The slug, cut at a hyphen where it is too long; "" when nothing of the title is a letter or digit.
    """
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")
    if len(slug) > _MAX_SLUG:
        cut = slug[: _MAX_SLUG + 1]
        slug = cut[: cut.rfind("-")] if "-" in cut else slug[:_MAX_SLUG]
    return slug


def _is_name_of(run_id: int, file_name: str) -> bool:
    """Whether `file_name` is one an export could have given the plan of run `run_id`, now or in an earlier format.

    Returns:
        True for `<run>.md`, and for `<run>-<status>.md` with anything `name` adds after the status.
    """
    statuses = "|".join(s.value for s in PlanStatus)
    return re.fullmatch(rf"{run_id}(?:-(?:{statuses})(?:-[a-z0-9]+)*)?\.md", file_name) is not None


class _Seen:
    """The fingerprints of what an export found exported as it stands in one destination, kept between exports.

    A fingerprint is of a plan's row and the stat of its file and of the file exported from it, taken before either was
    read. One that still matches spares an export both reads; one that is missing or does not match is read and
    compared as if none were kept, so this file only ever spares work. It lives in the operator-only state directory,
    written whole under a temporary name.
    """

    def __init__(self, path: Path, dest: Path, fingerprints: Mapping[str, str]) -> None:
        self.path = path
        self.dest = dest
        self.fingerprints = dict(fingerprints)
        self.changed = False

    @classmethod
    @contextlib.contextmanager
    def of(cls, state_dir: Path, dest: Path) -> Iterator[Self]:
        """Read the fingerprints kept for `dest`, and keep what changed when the block ends, however it ends.

        Yields:
            The fingerprints, none when the file is missing, unreadable, or from another format.
        """
        dest = dest.resolve()
        path = state_dir / SEEN_DIR / f"{hashlib.sha256(os.fsencode(dest)).hexdigest()[:32]}.json"
        seen = cls(path, dest, _load(path))
        try:
            yield seen
        finally:
            seen.save()

    def matches(
        self,
        plan: str,
        kind: Kind,
        row: records.Plan | records.FeedbackPlan,
        *,
        source: os.stat_result | None,
        exported_name: str,
        exported: os.stat_result | None,
    ) -> bool:
        """Whether `plan`, `KEY/RUN`, was found exported as it stands under `exported_name`, and nothing changed since.

        Returns:
            False when either file is missing, or nothing was kept for `plan`.
        """
        kept = self.fingerprints.get(plan)
        return (
            kept is not None
            and source is not None
            and exported is not None
            and (kept == _fingerprint(kind, row, source, exported_name, exported))
        )

    def record(
        self,
        plan: str,
        kind: Kind,
        row: records.Plan | records.FeedbackPlan,
        *,
        source: os.stat_result | None,
        exported_name: str,
        exported: os.stat_result,
        settled_before: int,
    ) -> None:
        """Keep that `plan` was found exported as it stands, unless a file changed too recently to tell by its stat.

        A plan's file that could not be statted before it was read is not kept either.
        """
        if source is not None and all(max(s.st_mtime_ns, s.st_ctime_ns) < settled_before for s in (source, exported)):
            fingerprint = _fingerprint(kind, row, source, exported_name, exported)
            self.changed |= self.fingerprints.get(plan) != fingerprint
            self.fingerprints[plan] = fingerprint

    def save(self) -> None:
        """Write the fingerprints if any changed. A file that cannot be written costs the next export its reads only."""
        if not self.changed:
            return
        data = json.dumps({"format": _FORMAT, "dest": str(self.dest), "plans": self.fingerprints}).encode()
        temporary = self.path.with_name(f".{self.path.name}.{secrets.token_hex(8)}.tmp")
        try:
            self.path.parent.mkdir(mode=_DIR_MODE, exist_ok=True)
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, _FILE_MODE)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            temporary.replace(self.path)
        except OSError:
            with contextlib.suppress(OSError):
                temporary.unlink()


def _load(path: Path) -> dict[str, str]:
    """The fingerprints kept at `path`.

    Returns:
        Each plan's fingerprint by its `KEY/RUN`; none when the file is missing, unreadable, not
        canopy's, or from another format.
    """
    try:
        kept: object = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return {}
    if not isinstance(kept, dict) or kept.get("format") != _FORMAT or not isinstance(kept.get("plans"), dict):
        return {}
    fingerprints: dict[object, object] = kept["plans"]
    return {k: v for k, v in fingerprints.items() if isinstance(k, str) and isinstance(v, str)}


def _fingerprint(
    kind: Kind,
    row: records.Plan | records.FeedbackPlan,
    source: os.stat_result,
    exported_name: str,
    exported: os.stat_result,
) -> str:
    """A plan's row, the stat of its file, and the name and stat of its export, as one digest.

    Returns:
        The digest, hex.
    """
    stats = [(s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns) for s in (source, exported)]
    # A row's repr names each column and its value, so it changes with either, and with a column added.
    digested = (_FORMAT, kind, row, exported_name, stats)
    return hashlib.blake2b(repr(digested).encode(), digest_size=16).hexdigest()


@contextlib.contextmanager
def _dest_dir(dest: Path) -> Iterator[int]:
    """Open `dest`, made operator-only if it is missing.

    Yields:
        The directory's descriptor, closed when the block ends.

    Raises:
        ExportError: it is not a directory, or cannot be made.
    """
    try:
        dest.mkdir(mode=_DIR_MODE, parents=True, exist_ok=True)
        dest_fd = os.open(dest, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as e:
        raise ExportError(f"{dest} is not a directory canopy can export into: {e.strerror}") from None
    try:
        yield dest_fd
    finally:
        os.close(dest_fd)


@contextlib.contextmanager
def _ticket_dir(dest_fd: int, path: Path) -> Iterator[int]:
    """Open a ticket's directory in the destination `dest_fd`, made if it is missing, never through a link.

    Yields:
        The directory's descriptor, closed when the block ends.

    Raises:
        ExportError: it is a link or not a directory.
    """
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        try:
            dir_fd = os.open(path.name, flags, dir_fd=dest_fd)
        except FileNotFoundError:
            os.mkdir(path.name, _DIR_MODE, dir_fd=dest_fd)
            dir_fd = os.open(path.name, flags, dir_fd=dest_fd)
    except OSError as e:
        raise ExportError(f"{path} is not a directory canopy can export into: {e.strerror}") from None
    try:
        yield dir_fd
    finally:
        os.close(dir_fd)


@contextlib.contextmanager
def _source_dir(path: Path) -> Iterator[int | None]:
    """Open a ticket's directory of plans under the state directory, to stat its files, never through a link.

    Yields:
        The directory's descriptor, closed when the block ends; None when it cannot be opened so, and each of its plans
        is then read as if it had no fingerprint.
    """
    try:
        dir_fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        yield None
        return
    try:
        yield dir_fd
    finally:
        os.close(dir_fd)


def _list(dir_fd: int) -> list[str]:
    """The names in the directory `dir_fd`.

    Returns:
        Its names, in no order.

    Raises:
        ExportError: it cannot be listed.
    """
    try:
        return os.listdir(dir_fd)
    except OSError as e:
        raise ExportError(f"a ticket's directory could not be listed: {e.strerror}") from None


def _remove(dir_fd: int, path: Path) -> None:
    """Remove `path`, whose directory is `dir_fd`: the name itself, never what a link there names.

    Raises:
        ExportError: it could not be removed.
    """
    try:
        os.unlink(path.name, dir_fd=dir_fd)
    except FileNotFoundError:
        pass
    except OSError as e:
        raise ExportError(f"{path} was not removed: {e.strerror}") from None


def _stat(name: str, dir_fd: int) -> os.stat_result | None:
    """Stat `name` in the directory `dir_fd`, a link itself rather than what it names.

    Returns:
        Its stat, or None when it cannot be had.
    """
    try:
        return os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except OSError:
        return None


def _write(dir_fd: int, path: Path, data: bytes) -> None:
    """Write `data` to `path`, whose directory is `dir_fd`, under a temporary name first.

    Raises:
        ExportError: the file could not be written.
    """
    temporary = f".{path.name}.{secrets.token_hex(8)}.tmp"
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, _FILE_MODE, dir_fd=dir_fd)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        # A rename replaces the name itself, never what a link there names.
        os.rename(temporary, path.name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    except OSError as e:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=dir_fd)
        raise ExportError(f"{path} was not written: {e.strerror}") from None


def _held(dir_fd: int, name: str, data: bytes) -> os.stat_result | None:
    """Whether `name` in the directory `dir_fd` is a regular file holding exactly `data`, read without following a link.

    Returns:
        The file's stat, taken before it was read, when it holds `data`; None when it is missing, a link, not a regular
        file, unreadable, or holds anything else.
    """
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        held = os.fstat(f.fileno())
        if not stat.S_ISREG(held.st_mode):
            return None
        # One byte past `data` tells a longer file apart without reading the rest of it.
        return held if f.read(len(data) + 1) == data else None
