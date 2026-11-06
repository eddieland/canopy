"""How much of each run goes to finding its way before it reaches its work (ROADMAP M70, stage 0's gate).

From the transcripts canopy keeps (§13), per run: its tool calls, and of them, the calls, the searches, and the spend
before its anchor, the first read of the file its work is about, with the share of its calls that went before it. A
search is a `grep` or `glob` call, or a shell command that searches (`report.shell_searches`). The anchor is, for:

- a worker's run and a task's: the first read of a file the run's first edit changed, or that edit itself, when the run
  read none of them first;
- a plan run: the first read of a file the plan it wrote names, as a path with a directory, or a name with an
  extension;
- a review: the first read of a file the review's kept diff changes (§21).

Paths are compared by their end, a read of `/slot/src/a.py` matching `src/a.py`, since a run names files from its
slot and a plan or a diff from the repository's root. A feedback plan's run, and any run whose anchor is not found,
counts as read but not anchored. `canopy orientation` prints the medians per role and repository, and whether the
worker runs of each repository pass the gate the milestone names: the median spends more than a quarter of its calls,
or more than three searches, before its anchor. Read only, over the runs that ended and started in a window of local
days (`spend.window`); a run whose log is gone, refused, or holds no tool call is counted, and not read.
"""

from __future__ import annotations

import dataclasses
import re
import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, LiteralString

from canopy.core import db, plans, records, review_diff, spend, sql
from canopy.core.vocab import RunKind
from canopy.runtime import transcript

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Collection, Iterable, Mapping
    from datetime import datetime

    from canopy.runtime.implementation import Version
    from canopy.runtime.transcript import Use

#: The roles that are not a run kind: a review's run, and a one-off task's.
REVIEW = "review"
TASK = "task"
#: The run kinds the gate reads as a worker's: those that edit a ticket's branch.
WORKER_KINDS: Sequence[RunKind] = (RunKind.IMPLEMENT, RunKind.RESUME, RunKind.FIX_CI, RunKind.SPLIT)
#: The gate: stage 1 starts if the median worker run spends more than this share of its calls before its anchor...
GATE_SHARE = 0.25
#: ...or more than this many searches.
GATE_SEARCHES = 3
#: How a run whose slots name no repository, one of a workspace of one, is listed.
NO_REPO = "-"
#: A word of a plan's text, and the shape of a file's name with an extension: `README.md`, not `e.g` or `1.5`.
_PLAN_WORD_RE = re.compile(r"[\w./-]+")
_FILE_NAME_RE = re.compile(r"[\w-]{2,}(?:\.[\w-]+)*\.[A-Za-z][A-Za-z0-9]*")

type Anchor = Literal["edit", "plan", "diff", "none"]


@dataclass(frozen=True)
class RunOrientation:
    """What one run spent before its anchor; every figure None when its anchor was not found."""

    #: Every tool call the run made.
    calls: int
    #: The calls before the anchor, the searches among them, and the share of the run's calls they are.
    before: int | None
    searches: int | None
    share: float | None
    #: What the run's model calls had cost before the anchor, in dollars.
    spent: float | None

    @property
    def anchored(self) -> bool:
        """Whether the run's anchor was found."""
        return self.before is not None


@dataclass(frozen=True)
class RoleOrientation:
    """The runs of one role in one repository, and the medians of those whose anchor was found."""

    #: A worker's or a planner's run kind, `review`, or `task`.
    role: str
    #: The repositories the runs' slots came from, joined by `+` for a joint run; `NO_REPO` in a workspace of one.
    repo: str
    #: The runs that ended in the window, those whose transcript was read, and those whose anchor was found.
    runs: int
    read: int
    anchored: int
    #: The medians: every tool call of the read runs, and of the anchored ones, the calls, searches, share, and spend
    #: before the anchor; None when no run gives one.
    calls: float | None
    before: float | None
    searches: float | None
    share: float | None
    spent: float | None

    def as_json(self) -> dict[str, object]:
        """Return the counts and medians as one JSON object.

        Returns:
            `role`, `repo`, `runs`, `read`, `anchored`, and the medians `calls`, `before`, `searches`, `share`, and
            `spent_usd`.
        """
        return {
            "role": self.role,
            "repo": self.repo,
            "runs": self.runs,
            "read": self.read,
            "anchored": self.anchored,
            "calls": self.calls,
            "before": self.before,
            "searches": self.searches,
            "share": self.share,
            "spent_usd": self.spent,
        }


@dataclass(frozen=True)
class Gate:
    """The worker runs of one repository against stage 1's gate."""

    repo: str
    #: The worker runs whose anchor was found, and their medians.
    anchored: int
    share: float | None
    searches: float | None

    @property
    def passed(self) -> bool:
        """Whether the median worker run spends more than the gate's share of its calls, or searches, before it."""
        return (self.share is not None and self.share > GATE_SHARE) or (
            self.searches is not None and self.searches > GATE_SEARCHES
        )

    def as_json(self) -> dict[str, object]:
        """Return the gate's reading as one JSON object.

        Returns:
            `repo`, `anchored`, `share`, `searches`, and `passed`.
        """
        return {
            "repo": self.repo,
            "anchored": self.anchored,
            "share": self.share,
            "searches": self.searches,
            "passed": self.passed,
        }


@dataclass(frozen=True)
class Orientation:
    """The runs that started in a window, `[since, until)`, and ended, by role and repository, and the gate."""

    since: str
    until: str
    days: int
    #: Each role and repository a run of the window had: the run kinds in their vocabulary's order, then `review`,
    #: then `task`, each by repository.
    roles: Sequence[RoleOrientation] = ()
    #: Each repository a worker run of the window had.
    gates: Sequence[Gate] = ()

    def as_json(self) -> dict[str, object]:
        """Return the report as one JSON object.

        Returns:
            `since`, `until`, `days`, `gate` (its share and searches), `roles`, and `gates`.
        """
        return {
            "since": self.since,
            "until": self.until,
            "days": self.days,
            "gate": {"share": GATE_SHARE, "searches": GATE_SEARCHES},
            "roles": [r.as_json() for r in self.roles],
            "gates": [g.as_json() for g in self.gates],
        }


def measure(conn: sqlite3.Connection, now: datetime, days: int, *, state_dir: Path, version: Version) -> Orientation:
    """Measure the runs that started in the last `days` local days, today's so far included, and have ended.

    Each run's log is read as the runtime `version` prints it, its plan from under `state_dir`.

    Returns:
        A count and medians per role and repository a run of the window had, and the gate per repository.
    """
    start, end = spend.window(now, days)
    since, until = db.format_time(start), db.format_time(end)
    ran = _ran(conn, since, until)
    measured: dict[tuple[str, str], list[RunOrientation | None]] = defaultdict(list)
    for r in ran:
        measured[r.role, r.repo].append(_measure(r, state_dir=state_dir, version=version))
    order = [str(k) for k in RunKind] + [REVIEW, TASK]
    keys = sorted(measured, key=lambda k: (order.index(k[0]) if k[0] in order else len(order), k[0], k[1]))
    roles = tuple(_summed(role, repo, measured[role, repo]) for role, repo in keys)
    return Orientation(since=since, until=until, days=days, roles=roles, gates=_gates(measured))


def orientation_of(uses: Sequence[Use], anchor: int | None) -> RunOrientation:
    """What a run's calls up to its anchor, the call at index `anchor` of `uses`, spent; None when none was found.

    Returns:
        The run's calls, and the calls, searches, share, and spend before the anchor.
    """
    if anchor is None:
        return RunOrientation(calls=len(uses), before=None, searches=None, share=None, spent=None)
    searches = sum(1 for u in uses[:anchor] if u.touch.act == "search")
    return RunOrientation(
        calls=len(uses),
        before=anchor,
        searches=searches,
        share=anchor / len(uses),
        spent=uses[anchor].spent,
    )


def edit_anchor(uses: Sequence[Use]) -> int | None:
    """The index of a worker's anchor: the first read of a file its first edit changed, or that edit if none came first.

    Only completed calls count: a read that failed read nothing, and an edit that failed changed nothing.

    Returns:
        The index, or None when the run edited nothing.
    """
    first = next((i for i, u in enumerate(uses) if u.completed and u.touch.act == "edit"), None)
    if first is None:
        return None
    edited = uses[first].touch.paths
    read = next((i for i, u in enumerate(uses[:first]) if _reads(u, edited)), None)
    return read if read is not None else first


def read_anchor(uses: Sequence[Use], named: Iterable[str]) -> int | None:
    """The index of the first completed read of a file among `named`, paths from the repository's root.

    Returns:
        The index, or None when the run read none of them.
    """
    wanted = tuple(n.strip("/") for n in named if n.strip("/"))
    if not wanted:
        return None
    return next((i for i, u in enumerate(uses) if _reads(u, wanted)), None)


def plan_paths(text: str) -> list[str]:
    """The paths a plan's text names: words with a directory, or a file's name with an extension, each once, in order.

    Returns:
        The paths, as written, without a leading `./` or `/`, a trailing `/`, or the full stop after one.
    """
    found: list[str] = []
    for m in _PLAN_WORD_RE.finditer(text):
        word = m.group().rstrip(".").removeprefix("./").strip("/")
        if word and not word.startswith(".") and ("/" in word or _FILE_NAME_RE.fullmatch(word)):
            found.append(word)
    return list(dict.fromkeys(found))


def same_file(a: str, b: str) -> bool:
    """Whether paths `a` and `b` name the same file, one ending as the other does at a directory's edge.

    Returns:
        True for `/slot/src/a.py` and `src/a.py`, False for `/slot/xsrc/a.py` and `src/a.py`.
    """
    a, b = a.strip().rstrip("/"), b.strip().rstrip("/")
    if not a or not b:
        return False
    short, long = sorted((a.lstrip("/"), b), key=len)
    return long == short or long.endswith("/" + short)


@dataclass(frozen=True)
class _Ran(records.View):
    """A run that ended in the window, with its role, its repositories, and what finds its anchor."""

    role: str
    #: The repositories its slots came from, joined by `+`; empty when they name none.
    repo: str
    log_path: str
    session_id: str | None
    #: A worker's or a planner's ticket, for a plan run's file; None for a review's or a task's run.
    ticket_key: str | None
    #: Its id in its own table.
    run_id: int
    #: Whether it is a worker's or a planner's run, whose repositories its slots name.
    slotted: bool


#: A run in the window, by when it started, that has ended.
_WINDOW: LiteralString = "started_at >= ? AND started_at < ? AND ended_at IS NOT NULL"


def _ran(conn: sqlite3.Connection, since: str, until: str) -> list[_Ran]:
    """Every run that started in `[since, until)` and has ended: a worker's or a planner's, a review's, and a task's.

    Returns:
        The runs, a worker's or a planner's named by the repositories of its slots, joined by name.
    """
    worker = (
        sql.select("kind AS role, '' AS repo, log_path, session_id, ticket_key, id AS run_id, 1 AS slotted")
        .from_("runs")
        .where(_WINDOW, since, until)
    )
    tables: Iterable[tuple[Literal["review_runs", "task_runs"], str]] = (("review_runs", REVIEW), ("task_runs", TASK))
    each = [worker]
    each += [
        sql.select(
            "? AS role, coalesce(repo, '') AS repo, log_path, session_id, NULL AS ticket_key, id AS run_id, "
            "0 AS slotted",
            role,
        )
        .from_(table)
        .where(_WINDOW, since, until)
        for table, role in tables
    ]
    ran = records.fetch_all(conn, _Ran, sql.union(*each, every=True))
    repos = _slot_repos(conn, [r.run_id for r in ran if r.slotted])
    return [dataclasses.replace(r, repo=repos.get(r.run_id, "")) if r.slotted else r for r in ran]


def _slot_repos(conn: sqlite3.Connection, run_ids: Collection[int]) -> dict[int, str]:
    """The repositories each of `run_ids`' slots came from, joined by `+` in order by name; none for a run without.

    Returns:
        A run's id to its repositories.
    """
    query = (
        sql.select("DISTINCT run_id, repo")
        .from_("run_slots")
        .where("repo IS NOT NULL")
        .where_in("run_id", run_ids)
        .order_by("run_id, repo")
    )
    found: dict[int, list[str]] = defaultdict(list)
    for row in sql.execute(conn, query):
        found[int(row[0])].append(str(row[1]))
    return {run: "+".join(names) for run, names in found.items()}


def _measure(ran: _Ran, *, state_dir: Path, version: Version) -> RunOrientation | None:
    """What one run spent before its anchor, or None when its transcript could not be read or holds no tool call.

    Returns:
        The run's orientation, or None.
    """
    if ran.session_id is None:
        return None
    read = transcript.uses(Path(ran.log_path), version=version)
    if read is None or not read.calls:
        return None
    return orientation_of(read.calls, _anchor(ran, read.calls, state_dir))


def _anchor(ran: _Ran, uses: Sequence[Use], state_dir: Path) -> int | None:
    """The index of the run's anchor among its calls, by its role; None when it has none or it was not found.

    Returns:
        The index, or None.
    """
    match _anchor_kind(ran.role):
        case "edit":
            return edit_anchor(uses)
        case "plan":
            if ran.ticket_key is None:
                return None
            text = plans.read(plans.path_for(state_dir, ran.ticket_key, ran.run_id)).text
            return read_anchor(uses, plan_paths(text)) if text is not None else None
        case "diff":
            diff = review_diff.read(review_diff.path_for(ran.log_path))
            return read_anchor(uses, [f.path for f in diff.files]) if diff is not None else None
        case "none":
            return None


def _anchor_kind(role: str) -> Anchor:
    """Which anchor a role's runs have.

    Returns:
        `edit`, `plan`, `diff`, or `none` for a role with no anchor.
    """
    if role == TASK or role in WORKER_KINDS:
        return "edit"
    if role == RunKind.PLAN:
        return "plan"
    if role == REVIEW:
        return "diff"
    return "none"


def _reads(use: Use, paths: Iterable[str]) -> bool:
    """Whether `use` is a completed read of a file among `paths`.

    Returns:
        True when it is.
    """
    return (
        use.completed
        and use.touch.act == "read"
        and any(same_file(read, path) for read in use.touch.paths for path in paths)
    )


def _summed(role: str, repo: str, runs: Sequence[RunOrientation | None]) -> RoleOrientation:
    """The counts and medians of one role's runs in one repository.

    Returns:
        Them, a median None where no run gives one.
    """
    read = [r for r in runs if r is not None]
    anchored = [r for r in read if r.anchored]
    return RoleOrientation(
        role=role,
        repo=repo or NO_REPO,
        runs=len(runs),
        read=len(read),
        anchored=len(anchored),
        calls=_median(r.calls for r in read),
        before=_median(r.before for r in anchored),
        searches=_median(r.searches for r in anchored),
        share=_median(r.share for r in anchored),
        spent=_median(r.spent for r in anchored),
    )


def _gates(measured: Mapping[tuple[str, str], Sequence[RunOrientation | None]]) -> tuple[Gate, ...]:
    """The gate per repository a worker run of the window had, by its worker runs whose anchor was found.

    Returns:
        A gate per repository, by name.
    """
    by_repo: dict[str, list[RunOrientation]] = defaultdict(list)
    for (role, repo), runs in measured.items():
        if role in WORKER_KINDS:
            by_repo[repo or NO_REPO] += [r for r in runs if r is not None and r.anchored]
    return tuple(
        Gate(
            repo=repo,
            anchored=len(runs),
            share=_median(r.share for r in runs),
            searches=_median(r.searches for r in runs),
        )
        for repo, runs in sorted(by_repo.items())
    )


def _median(values: Iterable[float | None]) -> float | None:
    """The median of the values that are not None.

    Returns:
        It, or None when there are none.
    """
    found = [v for v in values if v is not None]
    return statistics.median(found) if found else None
