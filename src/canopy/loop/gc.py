"""What canopy keeps of its own history and caches, measured for `canopy gc --dry-run` (DESIGN §26, ROADMAP M47).

`measure` reports each kind of §26's table that M47 changes: how many there are, their bytes, and what a pass with
the configured `[retention]` would remove of them, then the remote branches canopy made that nothing names any more
(`gc_branches.py`), which no pass removes. It removes nothing, and runs nothing but `git count-objects` and
`git for-each-ref`.
`file_kinds` finds the files a pass removes, and `row_kinds` the journal's rows, for the pass (`gc_pass.py`) and the
dry run alike, so the two agree.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from canopy.chores import start as chore_start
from canopy.core import db, hostgit, review_diff, sql
from canopy.core.context import db_path
from canopy.core.vocab import MemoryScope, MemoryStatus, TickStatus
from canopy.infra import lock, logs, procs
from canopy.loop import attention, gc_branches
from canopy.reviews import start as review_start
from canopy.runs import dispatch

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import datetime

    from canopy.core.config import Retention
    from canopy.core.context import Context

TICKS_DIR = "ticks"
# A file under the run directories that no journal row names goes only once it is this old: a review run writes its
# prompt before its row (DESIGN §26).
UNRECORDED_AGE = timedelta(hours=1)
KIB = 1024
MIB = KIB * KIB
_COUNT_OBJECTS_TIMEOUT_SECONDS = 60
#: A table of the journal a pass removes rows of (DESIGN §26, The journal).
type RowTable = Literal["decisions", "connector_runs", "derivations"]
# The bytes of each row's text, in each table a pass removes rows of: what it holds, not the pages it fills.
_DECISION_BYTES = sql.frag(
    "length(CAST(action AS BLOB)) + length(CAST(rationale AS BLOB)) + length(CAST(created_at AS BLOB)) + "
    "coalesce(length(CAST(ticket_key AS BLOB)), 0) + coalesce(length(CAST(repo AS BLOB)), 0) + "
    "coalesce(length(CAST(chore AS BLOB)), 0) + coalesce(length(CAST(pr AS BLOB)), 0)",
)
_RUN_BYTES = sql.frag(
    "length(CAST(request AS BLOB)) + length(CAST(recorded AS BLOB)) + length(CAST(refused AS BLOB)) + "
    "length(CAST(stderr AS BLOB)) + coalesce(length(CAST(missed AS BLOB)), 0) + "
    "coalesce(length(CAST(query_result AS BLOB)), 0) + coalesce(length(CAST(review_query_result AS BLOB)), 0)",
)
_DERIVED_BYTES = sql.frag(
    "length(CAST(ticket_key AS BLOB)) + coalesce(length(CAST(repo AS BLOB)), 0) + length(CAST(phases AS BLOB)) + "
    "coalesce(length(CAST(stale AS BLOB)), 0) + coalesce(length(CAST(overseer_phase AS BLOB)), 0)",
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
class Found:
    """A file of one kind: where it is, its bytes, and whether a pass removes it."""

    path: Path
    size: int
    removable: bool


@dataclass(frozen=True)
class FileKind:
    """A kind of file a pass removes, as the dry run names it, with the rule that removes it and each file found."""

    name: str
    rule: str
    files: Sequence[Found]

    def kind(self) -> Kind:
        """Tally the files as the dry run reports them.

        Returns:
            The kind, its count the files found.
        """
        tally = _Tally()
        for found in self.files:
            tally.add(found.size, removable=found.removable)
        return tally.kind(self.name, "files", self.rule)


@dataclass(frozen=True)
class RowKind:
    """A kind of row in the journal, as the dry run names it, with the conditions that pick its rows.

    The dry run counts the rows `removable` picks, and the pass deletes those same rows, so the two agree.
    """

    name: str
    table: RowTable
    #: Which of the table's rows are of this kind.
    rows: sql.Fragment
    #: A row's bytes: what it holds, not the pages it fills.
    size: sql.Fragment
    #: Which of the kind's rows a pass removes.
    removable: sql.Fragment
    rule: str

    def kind(self, conn: sqlite3.Connection) -> Kind:
        """Tally the rows as the dry run reports them.

        Returns:
            The kind, its count the rows of it.
        """
        found = sql.execute(
            conn,
            sql.select(
                "count(*), sum({}), sum(coalesce({}, 0)), sum(CASE WHEN {} THEN {} END)",
                self.size,
                self.removable,
                self.removable,
                self.size,
            )
            .from_(self.table)
            .where("{}", self.rows),
        ).fetchone()
        count, size, removable, removable_size = (int(v or 0) for v in found)
        return Kind(self.name, "rows", count, size, removable, removable_size, self.rule)

    def delete(self) -> sql.Delete:
        """The statement that deletes the rows the dry run counts as removable.

        Returns:
            The DELETE.
        """
        return sql.delete(self.table).where("{}", self.rows).where("{}", self.removable)


@dataclass(frozen=True)
class Report:
    """What `canopy gc --dry-run` reports: each kind, the journal's size in bytes, and what could not be read."""

    at: str
    kinds: Sequence[Kind]
    journal_size: int
    notes: Sequence[str]
    #: The remote branches canopy made that nothing names any more, for the operator to delete: canopy deletes none.
    branches: Sequence[gc_branches.Branch] = ()


def measure(ctx: Context, now: datetime) -> Report:
    """Count what canopy keeps in the workspace, and what a pass at `now` would remove, changing nothing.

    Returns:
        The report, each kind in the order of §26's table.
    """
    retention = ctx.config.retention
    journal = db_path(ctx.ws)
    notes: list[str] = []
    kinds = [
        *(k.kind() for k in file_kinds(ctx, now)),
        _log_files(ctx.state_dir, retention),
        *(k.kind(ctx.conn) for k in row_kinds(ctx.conn, now, retention)),
        _overseer_attention(ctx.conn),
        *_journal_space(ctx.conn, journal),
        *_git_objects(ctx, notes),
        _sandbox_caches(),
        _memory_text(ctx.conn, now, retention),
    ]
    branches = gc_branches.unnamed(ctx, notes)
    size = _regular_size(journal) or 0
    return Report(at=db.format_time(now), kinds=kinds, journal_size=size, notes=notes, branches=branches)


def file_kinds(ctx: Context, now: datetime) -> list[FileKind]:
    """The files of runs, ticks, chore runs, and reviews, then the unrecorded, each removable as a pass at `now` would.

    A file is removable only when it is a regular file inside the state directory, through no link, and its row ended
    before its retention while its run, if it has one, holds no lifelock; a file no row names, once an hour old.

    Returns:
        The kinds, in the order of §26's table.
    """
    retention = ctx.config.retention
    files = _Files(ctx.state_dir.absolute())
    runs = retention_cutoff(now, retention.run_files_days)
    by_runs = f"run_files_days = {retention.run_files_days}"
    return [
        files.kind("run files", _run_files(ctx.conn, runs), by_runs),
        files.kind(
            "tick files",
            _tick_files(ctx.conn, files.root, retention_cutoff(now, retention.tick_files_days), runs),
            f"tick_files_days = {retention.tick_files_days}, not ok: run_files_days",
        ),
        files.kind("chore run files", _logged(ctx.conn, "chore_runs", runs, ".prompt"), by_runs),
        files.kind("review files", _logged(ctx.conn, "review_runs", runs, ".prompt", ".diff"), by_runs),
        # Last: a file is unrecorded only once every row's files have been read.
        files.unrecorded(now),
    ]


def retention_cutoff(now: datetime, days: int) -> str:
    """The journal time before which a kind kept `days` is past its retention.

    Returns:
        The time as the journal stores it; for `days` 0, which keeps the kind forever, "", which no time is before.
    """
    return db.format_time(now - timedelta(days=days)) if days else ""


def row_kinds(conn: sqlite3.Connection, now: datetime, retention: Retention) -> list[RowKind]:
    """The rows a pass removes from the journal: the harness's attention items, connector runs, and derivations.

    A row goes once it is older than `journal_days` and outside the attention list's window, the newest
    `attention.HISTORY_TICKS` ticks that closed `ok`, so the list, each item's open-since, and what the sinks are told
    stay as they were; a journal with fewer `ok` ticks than the window has none outside it. A poll's connector run,
    made between ticks, is outside once it started before the window's oldest tick. Each source's newest run and its
    newest that recorded the query's result stay whatever their age (DESIGN §26, §30).

    Returns:
        The kinds, in the order of §26's table.
    """
    cutoff = retention_cutoff(now, retention.journal_days)
    window = _window(conn)
    rule = f"journal_days = {retention.journal_days}, outside {attention.HISTORY_TICKS} ok ticks"
    return [
        RowKind(
            "harness attention",
            "decisions",
            sql.in_("action", _harness()),
            _DECISION_BYTES,
            sql.frag("tick_id < ? AND created_at < ?", window.tick_id, cutoff),
            rule,
        ),
        RowKind(
            "connector runs",
            "connector_runs",
            sql.frag("1"),
            _RUN_BYTES,
            sql.all_of(
                sql.frag("coalesce(tick_id < ?, started_at < ?)", window.tick_id, window.started_at),
                sql.frag("started_at < ?", cutoff),
                sql.not_in("id", _newest_runs(conn)),
            ),
            f"{rule}, newest kept",
        ),
        RowKind(
            "derivations",
            "derivations",
            sql.frag("1"),
            _DERIVED_BYTES,
            sql.frag("tick_id < ? AND tick_id IN (SELECT id FROM ticks WHERE started_at < ?)", window.tick_id, cutoff),
            rule,
        ),
    ]


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

    def kind(self, name: str, owned: Iterable[_Owned], rule: str) -> FileKind:
        """Find the files `owned` names, each removable once its row is past its retention.

        Returns:
            The kind, holding the files that are there.
        """
        files: list[Found] = []
        for row in owned:
            sizes = [(p, _regular_size(p) if self._inside(p) else None) for p in row.paths]
            self.recorded.update(p.with_suffix("").absolute() for p in row.paths)
            present = [(p, size) for p, size in sizes if size is not None]
            expired = bool(present) and row.expired
            files.extend(Found(p, size, removable=expired) for p, size in present)
        return FileKind(name, rule, files)

    def unrecorded(self, now: datetime) -> FileKind:
        """Find the files under the run directories that no row read so far names: removable once an hour old.

        Lifelocks are left out: reconcile removes them (DESIGN §26's table, unchanged).

        Returns:
            The kind.
        """
        files: list[Found] = []
        before = (now - UNRECORDED_AGE).timestamp()
        for directory in self._run_dirs():
            for path in sorted(directory.iterdir()):
                if path.suffix == ".lock" or path.with_suffix("").absolute() in self.recorded:
                    continue
                found = _regular_stat(path)
                if found is not None:
                    files.append(Found(path, found.st_size, removable=found.st_mtime < before))
        return FileKind("unrecorded files", "an hour old", files)

    def _run_dirs(self) -> list[Path]:
        dirs = [self.root / d for d in (dispatch.RUNS_DIR, TICKS_DIR, review_start.REVIEWS_DIR)]
        chores = self.root / chore_start.RUNS_DIR
        if _is_dir(chores):
            dirs.extend(sorted(chores.iterdir()))
        return [d for d in dirs if _is_dir(d)]

    def _inside(self, path: Path) -> bool:
        # Only a file the state directory holds, through no link: a row's path is the journal's word for it.
        return Path(os.path.realpath(path.parent)).is_relative_to(os.path.realpath(self.root))


def _logged(conn: sqlite3.Connection, table: db.RunTable, cutoff: str, *suffixes: str) -> list[_Owned]:
    """Each run's log in `table`, the files beside it named by `suffixes`, and the lifelock it holds while it lives.

    Returns:
        What each row owns, oldest first.
    """
    rows = sql.execute(conn, sql.select("ended_at, log_path").from_(table).order_by("id")).fetchall()
    owned: list[_Owned] = []
    for r in rows:
        log = Path(r["log_path"])
        paths = (log, *(log.with_suffix(s) for s in suffixes))
        owned.append(_Owned(paths, r["ended_at"], cutoff, lifelock=procs.lifelock(log)))
    return owned


def _run_files(conn: sqlite3.Connection, cutoff: str) -> list[_Owned]:
    """Each worker run's log, its prompt, and the diffs it kept, with the lifelock it holds while it lives.

    A run under `approve` keeps a diff and its head for each repository it leased (DESIGN §29). A run that wrote a
    plan keeps its prompt as long as the plan, forever, so the plan's archive can say what its planner was given (§25).

    Returns:
        What each run owns, oldest first.
    """
    repos: dict[int, list[str]] = {}
    slots = sql.select("run_id, repo").from_("run_slots").where("repo IS NOT NULL").order_by("run_id, repo")
    for r in sql.execute(conn, slots):
        repos.setdefault(int(r["run_id"]), []).append(str(r["repo"]))
    planned = sql.union(sql.select("run_id").from_("plans"), sql.select("run_id").from_("feedback_plans"))
    planned_ids = {int(r[0]) for r in sql.execute(conn, planned)}
    owned: list[_Owned] = []
    for r in sql.execute(conn, sql.select("id, ended_at, log_path").from_("runs").order_by("id")):
        log = Path(r["log_path"])
        kept = [review_diff.run_path_for(log, repo) for repo in repos.get(int(r["id"]), [])]
        prompt = log.with_suffix(".prompt")
        lifelock = procs.lifelock(log)
        if int(r["id"]) in planned_ids:
            # A cutoff of "" is one no time is before: kept forever.
            owned.append(_Owned((prompt,), r["ended_at"], "", lifelock=lifelock))
            paths = (log, *kept, *(p.with_suffix(".head") for p in kept))
        else:
            paths = (log, prompt, *kept, *(p.with_suffix(".head") for p in kept))
        owned.append(_Owned(paths, r["ended_at"], cutoff, lifelock=lifelock))
    return owned


def _tick_files(conn: sqlite3.Connection, state_dir: Path, ok_cutoff: str, other_cutoff: str) -> list[_Owned]:
    # A tick that did not close `ok` is one the operator debugs, so it keeps its files as long as a run's.
    rows = sql.execute(conn, sql.select("id, status, ended_at").from_("ticks").order_by("id")).fetchall()
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
    rotated = [(int(m[1]), p) for p in _listing(state_dir) if (m := logs.ROTATED_RE.fullmatch(p.name)) is not None]
    for index, path in sorted(rotated):
        found = _regular_size(path)
        if found is not None:
            after = index + 1 if rotates else index
            tally.add(found, removable=retention.log_keep > 0 and after > retention.log_keep)
    rule = f"log_max_mib = {retention.log_max_mib}, log_keep = {retention.log_keep}"
    return tally.kind("canopy.log", "files", rule + (", due to rotate" if rotates else ""))


def _overseer_attention(conn: sqlite3.Connection) -> Kind:
    """The attention rows the overseer recorded, which a pass keeps: the evaluation corpus (DESIGN §26, Open).

    Returns:
        The kind, nothing of it removable.
    """
    recorded = sql.all_of(sql.frag("action LIKE ?", f"{attention.ACTION_PREFIX}%"), sql.not_in("action", _harness()))
    return RowKind(
        "overseer attention",
        "decisions",
        recorded,
        _DECISION_BYTES,
        sql.frag("0"),
        "kept: the evaluation corpus",
    ).kind(conn)


def _harness() -> list[str]:
    """The actions of the attention items the harness raises itself.

    Returns:
        Each `attention:<reason>`, in order.
    """
    return [f"{attention.ACTION_PREFIX}{reason}" for reason in sorted(attention.HARNESS_REASONS)]


@dataclass(frozen=True)
class _Window:
    """The oldest tick inside the attention list's window, and when it started; 0 and None while there is none."""

    tick_id: int
    started_at: str | None


def _window(conn: sqlite3.Connection) -> _Window:
    """The oldest tick inside the attention list's window, the newest `attention.HISTORY_TICKS` that closed `ok`.

    Returns:
        It, or tick 0, which no tick is before, when the journal has fewer `ok` ticks than the window.
    """
    oldest = sql.execute(
        conn,
        sql.select("id, started_at")
        .from_("ticks")
        .where("status = ?", TickStatus.OK)
        .order_by("id DESC")
        .limit(1, offset=attention.HISTORY_TICKS - 1),
    ).fetchone()
    return _Window(0, None) if oldest is None else _Window(int(oldest["id"]), str(oldest["started_at"]))


def _newest_runs(conn: sqlite3.Connection) -> list[int]:
    """Each source's newest run, and its newest that recorded the query's result, which a pass keeps.

    `canopy status` and `connector_failed` read the first, and the derivation the second (DESIGN §30).

    Returns:
        Their ids.
    """
    newest = sql.union(
        sql.select("max(id)").from_("connector_runs").group_by("source"),
        sql.select("max(id)").from_("connector_runs").where("query_result IS NOT NULL").group_by("source"),
    )
    return [int(r[0]) for r in sql.execute(conn, newest)]


def _journal_space(conn: sqlite3.Connection, journal: Path) -> list[Kind]:
    """The journal's free pages, which only `--vacuum` gives back, and its WAL, which each pass checkpoints.

    Returns:
        The free pages' kind, then the WAL's.
    """
    page_size = int(sql.execute(conn, sql.frag("PRAGMA page_size")).fetchone()[0])
    free = int(sql.execute(conn, sql.frag("PRAGMA freelist_count")).fetchone()[0])
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
        counts = count_objects(ctx.runner, repo.path)
        if counts is None:
            notes.append(f"{repo.name}: git count-objects failed in {repo.path}")
            continue
        loose.count += counts.get("count", 0)
        loose.size += counts.get("size", 0) * KIB
        packs.count += counts.get("packs", 0)
        packs.size += counts.get("size-pack", 0) * KIB
    return [loose.kind("git loose objects", "objects", "--git"), packs.kind("git packs", "packs", "--git")]


def count_objects(runner: procs.Runner, clone: Path) -> dict[str, int] | None:
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
    cutoff = retention_cutoff(now, retention.memory_days)
    superseded = sql.select("min(n.created_at)").from_("memories n").where("n.supersedes = m.id")
    gone = (
        sql.select("m.body, coalesce(m.invalidated_at, ({})) AS gone", superseded)
        .from_("memories m")
        .where("m.scope != ?", MemoryScope.LESSON)
        .where_in("m.status", (MemoryStatus.SUPERSEDED, MemoryStatus.INVALID))
        .where("m.body IS NOT NULL")
    )
    found = sql.execute(
        conn,
        sql.select(
            "count(*), sum(length(CAST(body AS BLOB))), sum(gone < ?), "
            "sum(CASE WHEN gone < ? THEN length(CAST(body AS BLOB)) END)",
            cutoff,
            cutoff,
        ).from_("({})", gone),
    ).fetchone()
    count, size, removable, removable_bytes = (int(v or 0) for v in found)
    return Kind(
        "memory text",
        "rows",
        count,
        size,
        removable,
        removable_bytes,
        f"memory_days = {retention.memory_days}",
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
