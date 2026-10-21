"""Plans exported into a directory of the operator's, each with what the journal records of it (DESIGN §25).

`export` writes every plan and feedback plan the journal records, superseded ones included, to `<dest>/<KEY>/`: a front
matter of its row, then its file as it stands now. The row is what a copy of `plans/` alone would lose: whether the plan
was approved, by whom, and as which hash. The file's name says which plan it is and where it stands, so a listing reads
without opening one: its run, its status capitalized so it stands out, then its title as a slug (`name`), as
`412-Approved-export-reports-as-csv.md`.

An export is the same bytes for the same plan and row, so a file is rewritten only when its plan's file or row changed,
and a git repository at `dest` sees a change only where there is one. When a plan's status or title changes, so does its
name: the export writes the new name, then removes the plan's file under any name it had before, and nothing else, so
git sees a rename. A plan whose file is missing or no plan is left as it was exported before, if it was. A file is
written under a temporary name, then renamed into place, so no reader sees half of one and a link at its name is
replaced, never followed.

Beside each plan goes the prompt its planner was given, unless `prompts` is off: `<run>-prompt.md`, its bytes as canopy
wrote them beside the run's log. It never changes, so its name never does. A plan whose run has no prompt there, as one
from before prompts were kept, has none exported, and one exported before is left.

A history of thousands of plans is exported each tick, so an export reads only what may have changed: for each plan it
found exported as it stands, it keeps a fingerprint of its row and of every file's stat in the state directory, and
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
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Self

from canopy.core import plans, records, sql
from canopy.core.vocab import PlanStatus

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator, Mapping, Sequence

#: Which of a ticket's plans a file is: the plan before its implement (§25), or one before a resume (§32).
type Kind = Literal["plan", "feedback plan"]

#: Where, under the state directory, each destination's fingerprints are kept (`_Seen`), one file for each.
SEEN_DIR = "plan-exports"
_DIR_MODE = 0o700
_FILE_MODE = 0o600
_FRONT_MATTER = "---\n"
# Bumped whenever `document` or `name` changes, so every plan exported before is read and compared again.
_FORMAT = 3
# The most characters of a title a file's name carries.
_MAX_SLUG = 60
# A prompt's name in an export, `<run>-prompt.md`: never a plan's, which always has a status after its run.
_PROMPT_NAME_RE = re.compile(r"\d+-prompt\.md")
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


def export(
    conn: sqlite3.Connection,
    state_dir: Path,
    dest: Path,
    *,
    limit: int | None = None,
    prompts: bool = True,
) -> Exported:
    """Export every plan and feedback plan in the journal into `dest`, made operator-only if it is missing.

    With `limit`, stop once that many files are written; the plans after them are left for the next export. With
    `prompts`, each plan's prompt goes beside it.

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
    prompt_paths = _prompt_paths(conn, state_dir) if prompts else None
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
                    prompt = None if prompt_paths is None else _Prompt(prompt_paths.get(row.run_id))
                    _export_plan(kind, row, dirs, seen, tally, prompt=prompt, settled_before=settled_before)
    return Exported(
        written=tally.written,
        unchanged=tally.unchanged,
        skipped=tally.skipped,
        left=len(rows) - checked,
        removed=tally.removed,
    )


def name(kind: Kind, row: records.Plan | records.FeedbackPlan, text: str) -> str:
    """A plan's file name in an export: its run, its status capitalized, `feedback` for a feedback plan, and a slug.

    The title is the plan's first `# ` heading, less the `Plan: KEY` the planner opens it with. A plan is model text
    (TRUST_MODEL T1), so its slug holds only lowercase letters, digits, and single hyphens, and is cut short; a plan
    with no title past that prefix has none in its name.

    Returns:
        The name, as `412-Approved-export-reports-as-csv.md`.
    """
    parts = [str(row.run_id), row.status.value.capitalize()]
    if kind == "feedback plan":
        parts.append("feedback")
    slug = _slug(_title(text, row.ticket_key))
    if slug:
        parts.append(slug)
    return "-".join(parts) + ".md"


def prompt_name(run_id: int) -> str:
    """The name of the prompt of run `run_id` in an export.

    Returns:
        The name, as `412-prompt.md`.
    """
    return f"{run_id}-prompt.md"


def is_prompt(file_name: str) -> bool:
    """Whether `file_name` in an export is a plan's prompt rather than a plan.

    Returns:
        True for a name `prompt_name` gives.
    """
    return _PROMPT_NAME_RE.fullmatch(file_name) is not None


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


@dataclass(frozen=True)
class _Prompt:
    """A plan run's prompt, to export beside its plan."""

    #: Where it is, under the state directory; None when the run has none canopy can export.
    path: Path | None


#: The stat of a plan run's prompt and of the file exported from it, each None where it is missing.
type _PromptStats = tuple[os.stat_result | None, os.stat_result | None]


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
    prompt: _Prompt | None,
    settled_before: int,
) -> None:
    """Export one plan into its ticket's directory, unless it is there as it stands, and remove its earlier names.

    With `prompt`, its run's prompt goes beside it too, unless that is there as it stands.

    Raises:
        ExportError: its file, or its prompt, could not be written, or an earlier one removed.
    """
    plan = f"{dirs.key}/{row.run_id}"
    source_name = plans.file_name(row.run_id)
    # Every name this plan's file has in `dest`: one, unless its status or title changed since.
    names = [n for n in dirs.listing if _is_name_of(row.run_id, n)]
    # Each stat before its file is read, so a change after the read shows on the next export.
    source_stat = None if dirs.source_fd is None else _stat(source_name, dirs.source_fd)
    prompt_stats = None if prompt is None else _prompt_stats(prompt, row.run_id, dirs.dest_fd)
    if len(names) == 1:
        exported = _stat(names[0], dirs.dest_fd)
        if seen.matches(
            plan,
            kind,
            row,
            source=source_stat,
            exported_name=names[0],
            exported=exported,
            prompt=prompt_stats,
        ):
            tally.unchanged += 1
            return
    reading = plans.read(dirs.source / source_name)
    if reading.text is None:
        # A reading without text always says why; "unreadable" only satisfies the type.
        tally.skipped.append(Skipped(kind, dirs.key, row.run_id, reading.problem or "unreadable"))
        return
    exported_name = name(kind, row, reading.text)
    data = document(kind, row, reading.text)
    # Only a name listed as it is: a filesystem that ignores case would find the plan under an earlier name that
    # differs in case alone, and the name would never change to the new one.
    held = _held(dirs.dest_fd, exported_name, data) if exported_name in dirs.listing else None
    if held is None:
        _write(dirs.dest_fd, dirs.dest / exported_name, data)
        tally.written.append(f"{dirs.key}/{exported_name}")
    else:
        tally.unchanged += 1
    # Only once the plan is in place under its name, so a failed write leaves it under the earlier one.
    for earlier in names:
        # A filesystem that ignores case finds the plan's new file under an earlier name that differs in case alone.
        if earlier != exported_name and not _same_file(dirs.dest_fd, earlier, exported_name):
            _remove(dirs.dest_fd, dirs.dest / earlier)
            tally.removed.append(f"{dirs.key}/{earlier}")
    prompt_held = None if prompt is None else _export_prompt(prompt, row.run_id, dirs, tally)
    # Kept only when the plan, and its prompt if it has one, were found as they stand.
    if held is not None and (prompt is None or prompt_held is not None):
        seen.record(
            plan,
            kind,
            row,
            source=source_stat,
            exported_name=exported_name,
            exported=held,
            prompt=prompt_held,
            settled_before=settled_before,
        )


def _prompt_paths(conn: sqlite3.Connection, state_dir: Path) -> dict[int, Path]:
    """Where each plan run's prompt is: beside its log, as the run wrote it, and only inside the state directory.

    Returns:
        The path of each plan run's prompt, by its run's id; a run whose log is outside the state directory has none.
    """
    planned = sql.union(sql.select("run_id").from_("plans"), sql.select("run_id").from_("feedback_plans"))
    runs = sql.select("id, log_path").from_("runs").where("id IN ({})", planned)
    root = os.path.realpath(state_dir)
    # Resolved once for each directory: every plan run logs to the same one.
    inside: dict[Path, bool] = {}
    paths: dict[int, Path] = {}
    for r in sql.execute(conn, runs):
        prompt = Path(r["log_path"]).with_suffix(".prompt")
        if prompt.parent not in inside:
            inside[prompt.parent] = Path(os.path.realpath(prompt.parent)).is_relative_to(root)
        if inside[prompt.parent]:
            paths[int(r["id"])] = prompt
    return paths


def _prompt_stats(prompt: _Prompt, run_id: int, dest_fd: int) -> _PromptStats:
    """The stat of a plan run's prompt and of its export, neither read.

    Returns:
        Each stat, None where its file is missing; the prompt's also where it is not a regular file, as
        `_export_prompt` finds it, so a fingerprint taken there matches.
    """
    source = None if prompt.path is None else _lstat(prompt.path)
    if source is not None and not stat.S_ISREG(source.st_mode):
        source = None
    return source, _stat(prompt_name(run_id), dest_fd)


def _export_prompt(prompt: _Prompt, run_id: int, dirs: _Dirs, tally: _Tally) -> _PromptStats | None:
    """Export a plan run's prompt beside its plan, unless it is there as it stands or the run has none.

    Returns:
        The stat of the prompt and of its export, each taken before it was read, when nothing was written; None when
        the prompt was written.

    Raises:
        ExportError: it could not be written.
    """
    exported_name = prompt_name(run_id)
    found = None if prompt.path is None else _read_regular(prompt.path)
    if found is None:
        return None, _stat(exported_name, dirs.dest_fd)
    source, data = found
    held = _held(dirs.dest_fd, exported_name, data) if exported_name in dirs.listing else None
    if held is None:
        _write(dirs.dest_fd, dirs.dest / exported_name, data)
        tally.written.append(f"{dirs.key}/{exported_name}")
        return None
    return source, held


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
        True for `<run>.md`, and for `<run>-<status>.md`, the status lowercase or capitalized, with anything `name`
        adds after it.
    """
    statuses = "|".join(f"{s.value}|{s.value.capitalize()}" for s in PlanStatus)
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
        prompt: _PromptStats | None,
    ) -> bool:
        """Whether `plan`, `KEY/RUN`, was found exported as it stands under `exported_name`, and nothing changed since.

        `prompt` is the stat of its prompt and of that prompt's export, None while prompts are not exported.

        Returns:
            False when either of the plan's files is missing, or nothing was kept for `plan`.
        """
        kept = self.fingerprints.get(plan)
        return (
            kept is not None
            and source is not None
            and exported is not None
            and (kept == _fingerprint(kind, row, source, exported_name, exported, prompt=prompt))
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
        prompt: _PromptStats | None,
        settled_before: int,
    ) -> None:
        """Keep that `plan` was found exported as it stands, unless a file changed too recently to tell by its stat.

        A plan's file that could not be statted before it was read is not kept either.
        """
        stats = [source, exported, *(prompt or ())]
        if source is not None and all(
            max(s.st_mtime_ns, s.st_ctime_ns) < settled_before for s in stats if s is not None
        ):
            fingerprint = _fingerprint(kind, row, source, exported_name, exported, prompt=prompt)
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
    *,
    prompt: _PromptStats | None,
) -> str:
    """A plan's row, the stat of its file, the name and stat of its export, and those of its prompt, as one digest.

    Returns:
        The digest, hex.
    """
    stats = [_identity(s) for s in (source, exported)]
    prompt_stats = None if prompt is None else [None if s is None else _identity(s) for s in prompt]
    # A row's repr names each column and its value, so it changes with either, and with a column added.
    digested = (_FORMAT, kind, row, exported_name, stats, prompt_stats)
    return hashlib.blake2b(repr(digested).encode(), digest_size=16).hexdigest()


def _identity(s: os.stat_result) -> tuple[int, ...]:
    """What of a file's stat changes when the file does.

    Returns:
        Its device, inode, mode, size, and times.
    """
    return (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


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


def _lstat(path: Path) -> os.stat_result | None:
    """Stat `path`, a link itself rather than what it names.

    Returns:
        Its stat, or None when it cannot be had.
    """
    try:
        return path.lstat()
    except OSError:
        return None


def _read_regular(path: Path) -> tuple[os.stat_result, bytes] | None:
    """Read `path` whole when it is a regular file, never through a link.

    Returns:
        Its stat, taken before it was read, and its bytes; None when it is missing, a link, not a regular file, or
        unreadable.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        found = os.fstat(f.fileno())
        if not stat.S_ISREG(found.st_mode):
            return None
        try:
            return found, f.read()
        except OSError:
            return None


def _same_file(dir_fd: int, name: str, other: str) -> bool:
    """Whether `name` and `other` in the directory `dir_fd` are one file, as on a filesystem that ignores case.

    Returns:
        True when both stat, without following a link, as the same file.
    """
    first, second = _stat(name, dir_fd), _stat(other, dir_fd)
    return first is not None and second is not None and os.path.samestat(first, second)


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
