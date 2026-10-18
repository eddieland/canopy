"""What canopy keeps of its own history and caches, measured for `canopy gc --dry-run` (DESIGN §26, ROADMAP M47).

`measure` reports each kind of §26's table that M47 changes: how many there are, their bytes, and what a pass with
the configured `[retention]` would remove of them. It removes nothing, and runs nothing but `git count-objects`.
"""

from __future__ import annotations

import os
import re
import sqlite3
import stat
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.chores import start as chore_start
from canopy.core import db, hostgit, review_diff
from canopy.core.context import db_path
from canopy.core.vocab import MemoryScope, MemoryStatus, TickStatus
from canopy.infra import lock, logs, procs
from canopy.loop import attention
from canopy.reviews import start as review_start
from canopy.runs import dispatch

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from canopy.core.config import Retention
    from canopy.core.context import Context

TICKS_DIR = "ticks"
# A file under the run directories that no journal row names goes only once it is this old: a review run writes its
# prompt before its row (DESIGN §26).
UNRECORDED_AGE = timedelta(hours=1)
KIB = 1024
MIB = KIB * KIB
_ROTATED_RE = re.compile(rf"{re.escape(logs.LOG_FILE_NAME)}\.(\d+)")
_COUNT_OBJECTS_TIMEOUT_SECONDS = 60
# The bytes of an attention row's text: what it holds, not the pages it fills.
_ROW_BYTES = (
    "length(CAST(action AS BLOB)) + length(CAST(rationale AS BLOB)) + length(CAST(created_at AS BLOB)) + "
    "coalesce(length(CAST(ticket_key AS BLOB)), 0) + coalesce(length(CAST(repo AS BLOB)), 0) + "
    "coalesce(length(CAST(chore AS BLOB)), 0) + coalesce(length(CAST(pr AS BLOB)), 0)"
)


@dataclass(frozen=True)
class Kind:
    """One kind canopy keeps: how many there are, their bytes, what a pass would remove of them, and by what rule.

    `unit` says what `count` counts: files, rows, pages, objects, packs, or directories. Sizes are in bytes.
    """

    name: str
    unit: str
    count: int
    size: int
    removable: int
    removable_size: int
    rule: str


@dataclass(frozen=True)
class Report:
    """What `canopy gc --dry-run` reports: each kind, the journal's size in bytes, and what could not be read."""

    at: str
    kinds: list[Kind]
    journal_size: int
    notes: list[str]


def measure(ctx: Context, now: datetime) -> Report:
    """Count what canopy keeps in the workspace, and what a pass at `now` would remove, changing nothing.

    Returns:
        The report, each kind in the order of §26's table.
    """
    retention = ctx.config.retention
    journal = db_path(ctx.ws)
    files = _Files(ctx.state_dir.absolute())
    runs = _cutoff(now, retention.run_files_days)
    by_runs = f"run_files_days = {retention.run_files_days}"
    notes: list[str] = []
    kinds = [
        files.kind("run files", _run_files(ctx.conn, runs), by_runs),
        files.kind(
            "tick files",
            _tick_files(ctx.conn, files.root, _cutoff(now, retention.tick_files_days), runs),
            f"tick_files_days = {retention.tick_files_days}, not ok: run_files_days",
        ),
        files.kind("chore run files", _logged(ctx.conn, "chore_runs", runs, ".prompt"), by_runs),
        files.kind("review files", _logged(ctx.conn, "review_runs", runs, ".prompt", ".diff"), by_runs),
        files.unrecorded(now),
        _log_files(ctx.state_dir, retention),
        *_attention(ctx.conn, now, retention),
        *_journal_space(ctx.conn, journal),
        *_git_objects(ctx, notes),
        _sandbox_caches(),
        _memory_text(ctx.conn, now, retention),
    ]
    return Report(at=db.format_time(now), kinds=kinds, journal_size=_regular_size(journal) or 0, notes=notes)


def _cutoff(now: datetime, days: int) -> str:
    """The journal time before which a kind kept `days` is past its retention.

    Returns:
        The time as the journal stores it; for `days` 0, which keeps the kind forever, "", which no time is before.
    """
    return db.format_time(now - timedelta(days=days)) if days else ""


@dataclass(frozen=True)
class _Owned:
    """The files a journal row names, when its run or tick ended, and the time before which that is past retention.

    `ended_at` is None while it has not ended. `lifelock`, when set, is the lock its run holds while it lives.
    """

    paths: tuple[Path, ...]
    ended_at: str | None
    cutoff: str
    lifelock: Path | None = None

    @property
    def expired(self) -> bool:
        """Whether the row ended before its cutoff, and its run, if it has one, holds no lifelock."""
        if self.ended_at is None or not self.ended_at < self.cutoff:
            return False
        return self.lifelock is None or not lock.held(self.lifelock)


@dataclass
class _Tally:
    count: int = 0
    size: int = 0
    removable: int = 0
    removable_size: int = 0

    def add(self, size: int, *, removable: bool) -> None:
        self.count += 1
        self.size += size
        if removable:
            self.removable += 1
            self.removable_size += size

    def kind(self, name: str, unit: str, rule: str) -> Kind:
        return Kind(name, unit, self.count, self.size, self.removable, self.removable_size, rule)


@dataclass
class _Files:
    """The files of every journal row read so far, in the state directory `root`, for the unrecorded ones after."""

    root: Path
    recorded: set[Path] = field(default_factory=set[Path])

    def kind(self, name: str, owned: Iterable[_Owned], rule: str) -> Kind:
        """Tally the files `owned` names, each removable once its row is past its retention.

        Returns:
            The kind, its count the files that are there.
        """
        tally = _Tally()
        for row in owned:
            sizes = [_regular_size(p) if self._inside(p) else None for p in row.paths]
            self.recorded.update(p.with_suffix("").absolute() for p in row.paths)
            present = [s for s in sizes if s is not None]
            expired = bool(present) and row.expired
            for size in present:
                tally.add(size, removable=expired)
        return tally.kind(name, "files", rule)

    def unrecorded(self, now: datetime) -> Kind:
        """Tally the files under the run directories that no row read so far names: removable once an hour old.

        Lifelocks are left out: reconcile removes them (DESIGN §26's table, unchanged).

        Returns:
            The kind.
        """
        tally = _Tally()
        before = (now - UNRECORDED_AGE).timestamp()
        for directory in self._run_dirs():
            for path in sorted(directory.iterdir()):
                if path.suffix == ".lock" or path.with_suffix("").absolute() in self.recorded:
                    continue
                found = _regular_stat(path)
                if found is not None:
                    tally.add(found.st_size, removable=found.st_mtime < before)
        return tally.kind("unrecorded files", "files", "an hour old")

    def _run_dirs(self) -> list[Path]:
        dirs = [self.root / d for d in (dispatch.RUNS_DIR, TICKS_DIR, review_start.REVIEWS_DIR)]
        chores = self.root / chore_start.RUNS_DIR
        if _is_dir(chores):
            dirs.extend(sorted(chores.iterdir()))
        return [d for d in dirs if _is_dir(d)]

    def _inside(self, path: Path) -> bool:
        # Only a file the state directory holds, through no link: a row's path is the journal's word for it.
        return Path(os.path.realpath(path.parent)).is_relative_to(os.path.realpath(self.root))


def _logged(conn: sqlite3.Connection, table: str, cutoff: str, *suffixes: str) -> list[_Owned]:
    """Each run's log in `table`, the files beside it named by `suffixes`, and the lifelock it holds while it lives.

    Returns:
        What each row owns, oldest first.
    """
    # `table` is one of the three names `measure` passes, never input.
    rows = conn.execute(f"SELECT ended_at, log_path FROM {table} ORDER BY id").fetchall()  # noqa: S608
    owned: list[_Owned] = []
    for r in rows:
        log = Path(r["log_path"])
        paths = (log, *(log.with_suffix(s) for s in suffixes))
        owned.append(_Owned(paths, r["ended_at"], cutoff, lifelock=procs.lifelock(log)))
    return owned


def _run_files(conn: sqlite3.Connection, cutoff: str) -> list[_Owned]:
    """Each worker run's log, its prompt, and the diffs it kept, with the lifelock it holds while it lives.

    A run under `approve` keeps a diff and its head for each repository it leased (DESIGN §29).

    Returns:
        What each run owns, oldest first.
    """
    repos: dict[int, list[str]] = {}
    for r in conn.execute("SELECT run_id, repo FROM run_slots WHERE repo IS NOT NULL ORDER BY run_id, repo"):
        repos.setdefault(int(r["run_id"]), []).append(str(r["repo"]))
    owned: list[_Owned] = []
    for r in conn.execute("SELECT id, ended_at, log_path FROM runs ORDER BY id"):
        log = Path(r["log_path"])
        kept = [review_diff.run_path_for(log, repo) for repo in repos.get(int(r["id"]), [])]
        paths = (log, log.with_suffix(".prompt"), *kept, *(p.with_suffix(".head") for p in kept))
        owned.append(_Owned(paths, r["ended_at"], cutoff, lifelock=procs.lifelock(log)))
    return owned


def _tick_files(conn: sqlite3.Connection, state_dir: Path, ok_cutoff: str, other_cutoff: str) -> list[_Owned]:
    # A tick that did not close `ok` is one the operator debugs, so it keeps its files as long as a run's.
    rows = conn.execute("SELECT id, status, ended_at FROM ticks ORDER BY id").fetchall()
    return [
        _Owned(
            tuple(state_dir / TICKS_DIR / f"{r['id']}{suffix}" for suffix in (".log", ".prompt")),
            r["ended_at"],
            cutoff=ok_cutoff if TickStatus(r["status"]) is TickStatus.OK else other_cutoff,
        )
        for r in rows
    ]


def _log_files(state_dir: Path, retention: Retention) -> Kind:
    """`canopy.log` and its rotated files, and the rotated ones a rotation now would shift past `log_keep`.

    Returns:
        The kind. Nothing is removable while `log_max_mib` or `log_keep` is 0, or the log is under the limit.
    """
    current = state_dir / logs.LOG_FILE_NAME
    size = _regular_size(current)
    rotates = size is not None and retention.log_max_mib > 0 and size > retention.log_max_mib * MIB
    tally = _Tally()
    if size is not None:
        tally.add(size, removable=False)
    rotated = [(int(m[1]), p) for p in _listing(state_dir) if (m := _ROTATED_RE.fullmatch(p.name)) is not None]
    for index, path in sorted(rotated):
        found = _regular_size(path)
        if found is not None:
            after = index + 1 if rotates else index
            tally.add(found, removable=retention.log_keep > 0 and after > retention.log_keep)
    rule = f"log_max_mib = {retention.log_max_mib}, log_keep = {retention.log_keep}"
    return tally.kind("canopy.log", "files", rule + (", due to rotate" if rotates else ""))


def _attention(conn: sqlite3.Connection, now: datetime, retention: Retention) -> list[Kind]:
    """The attention rows the harness raised, and the overseer's, which a pass keeps (DESIGN §26, Open).

    A harness row is removable once its tick is older than the attention list's window, the newest
    `attention.HISTORY_TICKS` ticks that closed `ok`, and it was recorded before `journal_days`. A journal with fewer
    ticks than the window has none.

    Returns:
        The harness's kind, then the overseer's.
    """
    oldest = conn.execute(
        "SELECT id FROM ticks WHERE status = ? ORDER BY id DESC LIMIT 1 OFFSET ?",
        (TickStatus.OK, attention.HISTORY_TICKS - 1),
    ).fetchone()
    window = int(oldest[0]) if oldest is not None else 0
    cutoff = _cutoff(now, retention.journal_days)
    harness = [f"{attention.ACTION_PREFIX}{reason}" for reason in sorted(attention.HARNESS_REASONS)]
    marks = ",".join("?" * len(harness))
    rows = conn.execute(
        f"SELECT action IN ({marks}) AS harness, count(*) AS n, sum(bytes) AS b, "  # noqa: S608
        "sum(tick_id < ? AND created_at < ?) AS rn, sum(CASE WHEN tick_id < ? AND created_at < ? THEN bytes END) AS rb "
        f"FROM (SELECT action, tick_id, created_at, {_ROW_BYTES} AS bytes FROM decisions WHERE action LIKE ?) "
        "GROUP BY harness",
        (*harness, window, cutoff, window, cutoff, f"{attention.ACTION_PREFIX}%"),
    ).fetchall()
    by = {bool(r["harness"]): r for r in rows}
    found = by.get(True)
    raised = Kind(
        "harness attention",
        "rows",
        int(found["n"]) if found is not None else 0,
        int(found["b"] or 0) if found is not None else 0,
        int(found["rn"] or 0) if found is not None else 0,
        int(found["rb"] or 0) if found is not None else 0,
        f"journal_days = {retention.journal_days}, outside {attention.HISTORY_TICKS} ok ticks",
    )
    kept = by.get(False)
    overseer = Kind(
        "overseer attention",
        "rows",
        int(kept["n"]) if kept is not None else 0,
        int(kept["b"] or 0) if kept is not None else 0,
        0,
        0,
        "kept: the evaluation corpus",
    )
    return [raised, overseer]


def _journal_space(conn: sqlite3.Connection, journal: Path) -> list[Kind]:
    """The journal's free pages, which only `--vacuum` gives back, and its WAL, which each pass checkpoints.

    Returns:
        The free pages' kind, then the WAL's.
    """
    page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
    free = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
    wal = _regular_size(journal.with_name(f"{journal.name}-wal"))
    wal_count, wal_bytes = (1, wal) if wal is not None else (0, 0)
    return [
        Kind("journal free pages", "pages", free, free * page_size, 0, 0, "--vacuum"),
        Kind("journal WAL", "files", wal_count, wal_bytes, wal_count, wal_bytes, "checkpointed"),
    ]


def _git_objects(ctx: Context, notes: list[str]) -> list[Kind]:
    """The loose objects and the packs in each primary clone, from `git count-objects -v`, which changes nothing.

    A clone git cannot read is left out, with a note saying so.

    Returns:
        The loose objects' kind, then the packs'.
    """
    loose, packs = _Tally(), _Tally()
    for repo in ctx.workspace.repos:
        if not _is_dir(repo.path):
            notes.append(f"{repo.name}: no primary clone at {repo.path}")
            continue
        counts = _count_objects(ctx.runner, repo.path)
        if counts is None:
            notes.append(f"{repo.name}: git count-objects failed in {repo.path}")
            continue
        loose.count += counts.get("count", 0)
        loose.size += counts.get("size", 0) * KIB
        packs.count += counts.get("packs", 0)
        packs.size += counts.get("size-pack", 0) * KIB
    return [loose.kind("git loose objects", "objects", "--git"), packs.kind("git packs", "packs", "--git")]


def _count_objects(runner: procs.Runner, clone: Path) -> dict[str, int] | None:
    """`git count-objects -v` in `clone`, each line's number by its name; sizes are in KiB.

    Returns:
        The numbers, or None when git could not run or failed.
    """
    try:
        done = runner.run(hostgit.argv("count-objects", "-v"), cwd=clone, timeout=_COUNT_OBJECTS_TIMEOUT_SECONDS)
    except procs.ProcError:
        return None
    if done.returncode != 0 or done.timed_out:
        return None
    counts: dict[str, int] = {}
    for line in done.stdout.splitlines():
        name, _, value = line.partition(":")
        if value.strip().isdigit():
            counts[name.strip()] = int(value)
    return counts


def _sandbox_caches() -> Kind:
    """Each role's cache under `$XDG_CACHE_HOME/canopy/sandbox/`, which only `--caches` empties (DESIGN §24).

    Returns:
        The kind, counting role directories and the bytes of the regular files in them.
    """
    xdg = Path(os.environ.get("XDG_CACHE_HOME", ""))
    root = (xdg if xdg.is_absolute() else Path.home() / ".cache") / "canopy" / "sandbox"
    tally = _Tally()
    for role in _listing(root):
        if _is_dir(role):
            tally.add(_tree_size(role), removable=False)
    return tally.kind("sandbox caches", "directories", "--caches")


def _memory_text(conn: sqlite3.Connection, now: datetime, retention: Retention) -> Kind:
    """The text of notes and proposals no longer in force (DESIGN §28), removable `memory_days` after they left it.

    A memory leaves force when it is invalidated, or when a newer one supersedes it. A lesson's text is never removed.

    Returns:
        The kind, counting rows that still hold text.
    """
    cutoff = _cutoff(now, retention.memory_days)
    found = conn.execute(
        "SELECT count(*), sum(length(CAST(body AS BLOB))), sum(gone < ?), "
        "sum(CASE WHEN gone < ? THEN length(CAST(body AS BLOB)) END) FROM ("
        "SELECT m.body, coalesce(m.invalidated_at, "
        "(SELECT min(n.created_at) FROM memories n WHERE n.supersedes = m.id)) AS gone "
        "FROM memories m WHERE m.scope != ? AND m.status IN (?, ?) AND m.body IS NOT NULL)",
        (cutoff, cutoff, MemoryScope.LESSON, MemoryStatus.SUPERSEDED, MemoryStatus.INVALID),
    ).fetchone()
    count, size, removable, removable_bytes = (int(v or 0) for v in found)
    return Kind(
        "memory text", "rows", count, size, removable, removable_bytes, f"memory_days = {retention.memory_days}"
    )


def _regular_stat(path: Path) -> os.stat_result | None:
    try:
        found = path.lstat()
    except OSError:
        return None
    return found if stat.S_ISREG(found.st_mode) else None


def _regular_size(path: Path) -> int | None:
    found = _regular_stat(path)
    return found.st_size if found is not None else None


def _is_dir(path: Path) -> bool:
    try:
        return stat.S_ISDIR(path.lstat().st_mode)
    except OSError:
        return False


def _listing(directory: Path) -> list[Path]:
    try:
        return sorted(directory.iterdir())
    except OSError:
        return []


def _tree_size(root: Path) -> int:
    """The bytes of the regular files under `root`, following no link.

    Returns:
        Their sum; a file that cannot be read counts nothing.
    """
    total = 0
    for parent, _dirs, names in os.walk(root):
        for name in names:
            total += _regular_size(Path(parent) / name) or 0
    return total
