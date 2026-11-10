"""How large the runtime's record of every session is, and what an index of its text would cost (ROADMAP M72, stage 0).

`canopy sessions --sizes` reads the runtime's whole record (`canopy.runtime.session_text`) and measures it before
anything is built on it: its sessions, canopy's by kind of run and the rest by directory, as `canopy spend` tells them
apart (`canopy.core.runtime_sessions`); the characters of its text by part; and, for each cut of the text a search
could index, a trial full-text index built in a temporary directory under the state directory and removed when the
measurement ends: its size with word positions and without, how long it took to build, and how long it takes to find
the words the operator gave, beside the time a plain scan of the record takes to find them with no index.

A trial index is what stage 2 would build: FTS5, holding no text of its own, a row per part of a session, with
memory's tokenizer (DESIGN §28). Of canopy's own sessions it leaves out what each was sent, a run's prompt being the
journal's text rendered, as stage 2 would. The measurement writes nothing to the journal, and nothing outside its
temporary directory.
"""

from __future__ import annotations

import contextlib
import sqlite3
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from canopy.core import memory_search, spend, sql
from canopy.runtime import session_text
from canopy.runtime.report import TEXT_PARTS

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterable, Iterator, Mapping, Sequence
    from collections.abc import Set as AbstractSet

    from canopy.runtime.implementation import Version
    from canopy.runtime.report import KeptSession, RecordRead, TextPart, TextRow

#: A cut of a session's text a search could index (ROADMAP M72): what it said, what it did too, and what it read too.
type Cut = Literal["said", "did", "read"]
#: Whose a session is: one of `canopy spend`'s kinds of run, an epic's run, a session that ran in the state directory,
#: which only canopy runs agents in, or, for None, a session outside canopy.
type Owner = spend.Kind | Literal["epics", "state_dir"]

#: The parts of a session's text each cut indexes, each wider than the one before.
CUTS: Mapping[Cut, AbstractSet[TextPart]] = {
    "said": frozenset({"title", "sent", "wrote", "summary"}),
    "did": frozenset({"title", "sent", "wrote", "summary", "given"}),
    "read": frozenset({"title", "sent", "wrote", "summary", "given", "reasoning", "returned"}),
}
#: The parts of canopy's own sessions no cut indexes: what a run was sent, the journal's text rendered, which §22's
#: search finds already.
CANOPY_UNINDEXED: AbstractSet[TextPart] = frozenset({"sent"})
#: Each kind of canopy's sessions, in the order the measurement lists them.
OWNERS: tuple[Owner, ...] = (*spend.KINDS, "epics", "state_dir")
#: How many directories of the sessions outside canopy are listed, those with the most sessions first; the rest are
#: counted together, under `OTHER_DIRECTORIES`.
DIRECTORIES = 10
OTHER_DIRECTORIES = "(other directories)"
#: How a trial index splits text into words: memory's tokenizer (`memories_fts`), so a word matches as memory's search
#: matches it.
TOKENIZER = "porter unicode61"
#: The first SQLite that can delete a row from an index that holds no text, which stage 2's index needs.
CONTENTLESS_DELETE = (3, 43, 0)
#: How many rows a trial index takes in one transaction.
BATCH = 1000
# Each trial index's table, by whether it keeps word positions and whether rows can be deleted from it. Literal, as
# every statement canopy runs is: the temporary file is not the journal, but nothing in it is built from input.
_CREATE: Mapping[tuple[bool, bool], str] = {
    (
        True,
        True,
    ): f"CREATE VIRTUAL TABLE idx USING fts5(text, content='', contentless_delete=1, tokenize='{TOKENIZER}')",
    (True, False): f"CREATE VIRTUAL TABLE idx USING fts5(text, content='', tokenize='{TOKENIZER}')",
    (False, True): (
        "CREATE VIRTUAL TABLE idx USING fts5(text, content='', contentless_delete=1, detail=none,"
        f" tokenize='{TOKENIZER}')"
    ),
    (False, False): f"CREATE VIRTUAL TABLE idx USING fts5(text, content='', detail=none, tokenize='{TOKENIZER}')",
}
_INSERT = "INSERT INTO idx (rowid, text) VALUES (?, ?)"
_OPTIMIZE = "INSERT INTO idx (idx) VALUES ('optimize')"
_MATCH = "SELECT rowid FROM idx WHERE idx MATCH ?"


@dataclass(frozen=True)
class Group:
    """The sessions of one kind of canopy's runs, or of one directory outside canopy."""

    #: The kind, an `Owner`, or the directory.
    name: str
    #: How many are sessions of their own, and how many ran for another as subagents.
    sessions: int
    subagents: int
    #: How many of them all the runtime archived.
    archived: int


@dataclass(frozen=True)
class PartSize:
    """How much text one part of the sessions holds: how many rows of it, and how many characters, by whose."""

    part: TextPart
    canopy_rows: int
    canopy_chars: int
    outside_rows: int
    outside_chars: int


@dataclass(frozen=True)
class Found:
    """How long one way of finding the words took, and how many sessions it found them in."""

    seconds: float
    sessions: int


@dataclass(frozen=True)
class TrialIndex:
    """A trial index of one cut, as it was built and searched."""

    #: Whether it kept each word's positions, which a search for a phrase needs, or only which rows hold it.
    positions: bool
    #: Its file's size once built and optimized, and how long building it took.
    size_bytes: int
    build_seconds: float
    #: Finding the words in it; None when no word was given.
    found: Found | None


@dataclass(frozen=True)
class CutSize:
    """One cut of the text: what it holds, what indexing it costs, and what finding words in it takes without one."""

    cut: Cut
    #: Its parts, in `TEXT_PARTS`' order.
    parts: Sequence[TextPart]
    #: How many rows and characters it indexes, canopy's sessions' unindexed parts left out.
    rows: int
    chars: int
    #: Its trial indexes: with positions, then without.
    indexes: Sequence[TrialIndex]
    #: Finding the words by a plain scan of the record; None when no word was given.
    scan: Found | None


@dataclass(frozen=True)
class Sizes:
    """What `canopy sessions --sizes` measured of the runtime's record, or why it measured nothing."""

    #: How reading the record ended; nothing else is measured unless `found`.
    status: RecordRead
    #: Why it `failed` or is `unsupported`, in canopy's words.
    error: str | None = None
    #: The SQLite the trial indexes were built with, and whether it can delete from one that holds no text.
    sqlite_version: str = sqlite3.sqlite_version
    contentless_delete: bool = sqlite3.sqlite_version_info >= CONTENTLESS_DELETE
    #: How many databases the record is, and their size.
    databases: int = 0
    record_bytes: int = 0
    #: Canopy's sessions by kind, in `OWNERS`' order, every kind listed.
    canopy: Sequence[Group] = ()
    #: The sessions outside canopy by directory, the most first, at most `DIRECTORIES` and the rest together.
    outside: Sequence[Group] = ()
    #: How many sessions only the runtime's earlier version's tables hold, which are not read.
    earlier_only: int = 0
    #: How many sessions, and rows of their text, canopy passed over as ones it cannot read.
    skipped_sessions: int = 0
    skipped_rows: int = 0
    #: How many sandbox roles' databases could not be read.
    passed_over: int = 0
    #: The text by part, in `TEXT_PARTS`' order.
    text: Sequence[PartSize] = ()
    #: The words each search looked for, as memory's search reads them.
    words: Sequence[str] = ()
    #: Each cut, the narrowest first.
    cuts: Sequence[CutSize] = ()


def measure(
    conn: sqlite3.Connection,
    *,
    version: Version,
    state_dir: Path,
    query: str = "",
    clock: Callable[[], float] = time.perf_counter,
) -> Sizes:
    """Measure the record of the runtime `version` runs: its sessions, its text, and a trial index of each cut.

    `conn` is the workspace's journal, which says which sessions are canopy's runs, and `state_dir` its state
    directory, where a session that ran is canopy's too, and where the trial indexes are built and removed. The words
    of `query`, if any, are found in each index and by a plain scan, each timed on `clock`.

    Returns:
        What was measured, or, unless the record was `found`, why nothing was.
    """
    kept = session_text.record(version=version)
    if kept.outcome != "found":
        return Sizes(kept.outcome, error=kept.error, passed_over=kept.passed_over)
    owners = owners_of(conn, kept.sessions, state_dir)
    words = memory_search.words(query)
    try:
        text, cuts, skipped = _indexed(session_text.rows(version=version), owners, words, state_dir, clock)
        scans = {cut: _scan(words, cut, owners, version, clock) for cut in CUTS} if words else {}
    except sqlite3.Error as e:
        return Sizes("failed", error=f"the runtime's record could not be read: {str(e)[:200]}")
    canopy, outside = _groups(kept.sessions, owners)
    return Sizes(
        "found",
        databases=kept.databases,
        record_bytes=kept.size_bytes,
        canopy=canopy,
        outside=outside,
        earlier_only=kept.earlier_only,
        skipped_sessions=kept.skipped,
        skipped_rows=skipped,
        passed_over=kept.passed_over,
        text=text,
        words=words,
        cuts=[
            CutSize(
                cut=cut,
                parts=[p for p in TEXT_PARTS if p in CUTS[cut]],
                rows=built.rows,
                chars=built.chars,
                indexes=built.indexes,
                scan=scans.get(cut),
            )
            for cut, built in cuts.items()
        ],
    )


def owners_of(conn: sqlite3.Connection, kept: Iterable[KeptSession], state_dir: Path) -> dict[str, Owner | None]:
    """Whose each session is, as `canopy spend` tells canopy's apart (`canopy.core.runtime_sessions`).

    A session is canopy's when one of the journal's runs names it, when it ran in the state directory, or when it ran,
    as a subagent, for one that is, however deep; a subagent's is its nearest such session's kind.

    Returns:
        Each session's kind of canopy run, or None for one outside canopy.
    """
    named = _named(conn)
    by_id = {k.session_id: k for k in kept}
    home = str(state_dir.resolve())
    below = f"{home.rstrip('/')}/"

    def own(session_id: str) -> Owner | None:
        if session_id in named:
            return named[session_id]
        session = by_id.get(session_id)
        if session is not None and (session.directory == home or session.directory.startswith(below)):
            return "state_dir"
        return None

    found: dict[str, Owner | None] = {}
    for start in by_id:
        chain: list[str] = []
        at: str | None = start
        owner: Owner | None = None
        while at is not None and at not in found and at not in chain:
            chain.append(at)
            owner = own(at)
            if owner is not None:
                break
            parent = by_id.get(at)
            at = parent.parent_id if parent is not None else None
        else:
            owner = found.get(at) if at is not None else None
        found.update(dict.fromkeys(chain, owner))
    return found


# Each session one of the journal's runs names, by the kind of the run, as `canopy spend` tells them apart.
def _named(conn: sqlite3.Connection) -> dict[str, Owner]:
    found: dict[str, Owner] = {}
    selects: list[tuple[Owner, sql.Select]] = [
        (kind, sql.select("session_id").from_("{}", sql.name(table)).where("{}", condition))
        for kind, (table, condition) in spend.KIND_TABLES.items()
    ]
    selects.append(("epics", sql.select("session_id").from_("epic_runs")))
    for kind, select in selects:
        found.update((str(row[0]), kind) for row in sql.execute(conn, select.where("session_id IS NOT NULL")))
    return found


@dataclass
class _Built:
    """A cut's trial indexes as they are built: what each holds, and how long each took."""

    rows: int = 0
    chars: int = 0
    indexes: list[TrialIndex] = field(default_factory=list)


@dataclass
class _Trial:
    """One trial index being built: its file, its connection, the rows not yet written, and the time taken so far."""

    path: Path
    conn: sqlite3.Connection
    positions: bool
    pending: list[tuple[int, str]] = field(default_factory=list)
    seconds: float = 0.0


# Read every row of the text, count it by part and by whose, and build each cut's trial indexes in a temporary
# directory under the state directory, removed when they are measured. Returns the text by part, each cut's indexes,
# and how many rows could not be read.
def _indexed(
    stream: Generator[TextRow | None],
    owners: Mapping[str, Owner | None],
    words: Sequence[str],
    state_dir: Path,
    clock: Callable[[], float],
) -> tuple[list[PartSize], dict[Cut, _Built], int]:
    rows: Counter[tuple[TextPart, bool]] = Counter()
    chars: Counter[tuple[TextPart, bool]] = Counter()
    built: dict[Cut, _Built] = {cut: _Built() for cut in CUTS}
    session_of: list[str] = []
    skipped = 0
    with (
        contextlib.closing(stream),
        tempfile.TemporaryDirectory(prefix="sessions-sizes-", dir=state_dir) as tmp,
        contextlib.ExitStack() as stack,
    ):
        trials = {
            (cut, positions): stack.enter_context(_trial(tmp, cut, positions=positions))
            for cut in CUTS
            for positions in (True, False)
        }
        for row in stream:
            if row is None:
                skipped += 1
                continue
            ours = owners.get(row.session_id) is not None
            rows[row.part, ours] += 1
            chars[row.part, ours] += len(row.text)
            if ours and row.part in CANOPY_UNINDEXED:
                continue
            session_of.append(row.session_id)
            for cut, parts in CUTS.items():
                if row.part not in parts:
                    continue
                built[cut].rows += 1
                built[cut].chars += len(row.text)
                for positions in (True, False):
                    _add(trials[cut, positions], len(session_of), row.text, clock)
        for (cut, _), trial in trials.items():
            built[cut].indexes.append(_finished(trial, words, session_of, clock))
    text = [
        PartSize(
            part=part,
            canopy_rows=rows[part, True],
            canopy_chars=chars[part, True],
            outside_rows=rows[part, False],
            outside_chars=chars[part, False],
        )
        for part in TEXT_PARTS
    ]
    return text, built, skipped


@contextlib.contextmanager
def _trial(directory: str, cut: Cut, *, positions: bool) -> Iterator[_Trial]:
    path = Path(directory) / f"{cut}-{'positions' if positions else 'rows'}.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute(_CREATE[positions, sqlite3.sqlite_version_info >= CONTENTLESS_DELETE])
        conn.commit()
        yield _Trial(path, conn, positions)
    finally:
        conn.close()


# Add a row to a trial index, writing a batch once it is full.
def _add(trial: _Trial, rowid: int, text: str, clock: Callable[[], float]) -> None:
    trial.pending.append((rowid, text))
    if len(trial.pending) >= BATCH:
        _flush(trial, clock)


def _flush(trial: _Trial, clock: Callable[[], float]) -> None:
    if not trial.pending:
        return
    start = clock()
    with trial.conn:
        trial.conn.executemany(_INSERT, trial.pending)
    trial.seconds += clock() - start
    trial.pending.clear()


# Finish a trial index: write what is left, merge it into one segment as a built index would be, find the words in it,
# and measure its file.
def _finished(trial: _Trial, words: Sequence[str], session_of: Sequence[str], clock: Callable[[], float]) -> TrialIndex:
    _flush(trial, clock)
    start = clock()
    with trial.conn:
        trial.conn.execute(_OPTIMIZE)
    seconds = trial.seconds + clock() - start
    found: Found | None = None
    if words:
        start = clock()
        hits = trial.conn.execute(_MATCH, (" AND ".join(f'"{w}"' for w in words),)).fetchall()
        took = clock() - start
        found = Found(seconds=_seconds(took), sessions=len({session_of[int(r[0]) - 1] for r in hits}))
    return TrialIndex(
        positions=trial.positions,
        size_bytes=trial.path.stat().st_size,
        build_seconds=_seconds(seconds),
        found=found,
    )


# Find the words by a plain scan of the record's parts in a cut, with no index, as the index would find them: canopy's
# sessions' unindexed parts left out.
def _scan(
    words: Sequence[str],
    cut: Cut,
    owners: Mapping[str, Owner | None],
    version: Version,
    clock: Callable[[], float],
) -> Found:
    start = clock()
    hits = session_text.scan(words, CUTS[cut], version=version)
    took = clock() - start
    found = {s for s, part in hits if not (owners.get(s) is not None and part in CANOPY_UNINDEXED)}
    return Found(seconds=_seconds(took), sessions=len(found))


# Canopy's sessions by kind, every kind listed, and the rest by directory, the most first.
def _groups(kept: Iterable[KeptSession], owners: Mapping[str, Owner | None]) -> tuple[list[Group], list[Group]]:
    ours: dict[Owner, Counter[str]] = {kind: Counter() for kind in OWNERS}
    theirs: dict[str, Counter[str]] = {}
    for session in kept:
        owner = owners.get(session.session_id)
        tally = ours[owner] if owner is not None else theirs.setdefault(session.directory, Counter())
        tally["subagents" if session.parent_id is not None else "sessions"] += 1
        tally["archived"] += int(session.archived)
    ranked = sorted(theirs, key=lambda d: (-(theirs[d]["sessions"] + theirs[d]["subagents"]), d))
    outside = [_group(d, theirs[d]) for d in ranked[:DIRECTORIES]]
    rest: Counter[str] = Counter()
    for d in ranked[DIRECTORIES:]:
        rest.update(theirs[d])
    if rest:
        outside.append(_group(OTHER_DIRECTORIES, rest))
    return [_group(kind, ours[kind]) for kind in OWNERS], outside


def _group(name: str, tally: Mapping[str, int]) -> Group:
    return Group(
        name=name,
        sessions=tally.get("sessions", 0),
        subagents=tally.get("subagents", 0),
        archived=tally.get("archived", 0),
    )


# A time in seconds, to the tenth of a millisecond: finer is noise.
def _seconds(took: float) -> float:
    return round(max(took, 0.0), 4)
