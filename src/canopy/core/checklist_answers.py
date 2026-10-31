"""What a worker answered of its repositories' checklists (DESIGN §42, The reminder).

A worker run that may push, or a one-off task's (§36), is given the list of each of its repositories that has one, in
its answers directory, and canopy's `pre-push` holds its push to ask it (`commit_hooks`). It answers each item in its
result line's `checklist` field, by repository and item id: `pass`, `fixed`, `held` with its reason, or `n/a`. `_run`,
or `_task`, checks the answers against the lists the run was given, read back from its answers directory, and records a
row for every item of every list, naming the run, a worker's or a task's: the answer, or `unanswered` for an item its
result said nothing of. An answer to an item or a repository the run's lists do not hold is dropped, and named in the
run's note; a result with no `checklist` is never refused, since its push is already made. The reason is the worker's
text, which read the PR: it is shown as data, made printable, and authorizes nothing. `canopy checklist` counts the
answers per repository and item over a window (`counts`), so an item earns its place or is dropped; the web UI's
checklist page also groups them by the runs behind each `held` and `fixed` answer, and by week (`details`).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Literal, assert_never, cast

from pydantic import BaseModel, ConfigDict

from canopy.core import contract, db, records, spend, sql
from canopy.core.vocab import ItemAnswer

if TYPE_CHECKING:
    import sqlite3
    from datetime import datetime

    from canopy.core.checklists import Checklist

#: The placeholder of the result field's contract, which a run given a list carries, and any other renders empty.
CHECKLIST = "CHECKLIST"
#: How long a `held` item's reason may be.
MAX_REASON = 1000
#: How many dropped answers a note names; the rest are counted.
MAX_NAMED = 10
#: The answers a worker may give: `unanswered` is the harness's alone.
GIVEN: frozenset[ItemAnswer] = frozenset(ItemAnswer) - {ItemAnswer.UNANSWERED}
#: How many runs `details` names behind each item's `held` answers, and its `fixed`: the newest, which a page lists.
MAX_RUNS = 20
#: The tables of the runs that answer a checklist: a worker's, and a one-off task's (DESIGN §36).
type RunTable = Literal["runs", "task_runs"]
#: Whose run gave an answer, as the API names it: a worker's, or a task's.
type RunKindOf = Literal["run", "task"]


@dataclass(frozen=True)
class Answer:
    """One item's answer to record: its repository, its id, and what the run said of it."""

    repo: str
    item: str
    answer: ItemAnswer
    #: Why the run left the item failing, for `held`; None for any other answer.
    reason: str | None = None


@dataclass(frozen=True)
class Checked:
    """A run's `checklist`, checked: an answer for every item of every list it was given, and what was dropped."""

    answers: Sequence[Answer] = ()
    dropped: Sequence[str] = ()

    def note(self) -> str:
        """The run's harness note about what was dropped, or "" when nothing was.

        Returns:
            A sentence naming each dropped answer with why, at most `MAX_NAMED` of them, and counting the rest.
        """
        if not self.dropped:
            return ""
        parts = list(self.dropped[:MAX_NAMED])
        rest = len(self.dropped) - len(parts)
        if rest:
            parts.append(f"{rest} more, not named")
        return f"checklist answers dropped: {'; '.join(parts)}"


@dataclass(frozen=True)
class ItemCounts(records.View):
    """How the runs of a window answered one item of one repository's list, by answer.

    Counts only: a `held` answer's reason is the worker's text, which the run's own `show` prints, never a count.
    """

    repo: str
    #: The item's id, the operator's, as their list names it.
    item: str
    #: The runs given the item: each answered it, or is counted `unanswered`.
    reminded: int
    passed: int
    fixed: int
    held: int
    not_applicable: int
    unanswered: int

    def of(self, answer: ItemAnswer) -> int:
        """Return how many of the runs answered the item `answer`."""
        match answer:
            case ItemAnswer.PASSED:
                return self.passed
            case ItemAnswer.FIXED:
                return self.fixed
            case ItemAnswer.HELD:
                return self.held
            case ItemAnswer.NOT_APPLICABLE:
                return self.not_applicable
            case ItemAnswer.UNANSWERED:
                return self.unanswered
            case _:
                assert_never(answer)


@dataclass(frozen=True)
class Counts:
    """The answers of the worker and task runs that started in a window, `[since, until)`, per repository and item."""

    since: str
    until: str
    days: int
    #: The one repository counted; None for every one.
    repo: str | None
    #: By repository, then each item in its list's order, as the window's first run given it was.
    items: Sequence[ItemCounts] = ()

    def as_json(self) -> dict[str, object]:
        """Return the counts as one JSON object.

        Returns:
            `since`, `until`, `days`, `repo`, and `items`, each with its `repo`, `item`, `reminded`, and a count under
            each answer's word: `pass`, `fixed`, `held`, `n/a`, and `unanswered`.
        """
        return {
            "since": self.since,
            "until": self.until,
            "days": self.days,
            "repo": self.repo,
            "items": [
                {"repo": c.repo, "item": c.item, "reminded": c.reminded, **{str(a): c.of(a) for a in ItemAnswer}}
                for c in self.items
            ],
        }


@dataclass(frozen=True)
class AnsweredBy:
    """A run that gave an item an answer: a worker's, or a one-off task's (DESIGN §36)."""

    kind: RunKindOf
    #: The run's id in its table: `runs` for a worker's, `task_runs` for a task's.
    id: int
    #: The task a task's run is of; None for a worker's.
    task_id: int | None
    started_at: str
    #: Why it left the item failing, for `held`, the worker's text, whole; None for any other answer.
    reason: str | None


@dataclass(frozen=True)
class ItemRuns:
    """The runs of a window behind one item's `held` and `fixed` answers, the newest first, at most `MAX_RUNS` each."""

    repo: str
    item: str
    held: Sequence[AnsweredBy] = ()
    fixed: Sequence[AnsweredBy] = ()


@dataclass(frozen=True)
class WeekCounts:
    """How the runs that started in one local ISO week of a window answered one item."""

    #: The ISO week, `2026-W41`, of this machine's local time: Monday to Sunday.
    week: str
    #: The item's counts in the week alone: all zero for a week no run was given it.
    counts: ItemCounts


@dataclass(frozen=True)
class Details:
    """The answers `counts` counts over a window, grouped by the runs behind each item's and by week (`details`)."""

    #: An entry per item, in `counts`' order.
    items: Sequence[ItemRuns] = ()
    #: An entry per item and ISO week the window touches: the items in `counts`' order, each one's weeks oldest first.
    weeks: Sequence[WeekCounts] = ()


@dataclass(frozen=True)
class _Answered(records.View):
    """One answer of the window, with the run that gave it and when that run started."""

    repo: str
    item: str
    answer: ItemAnswer
    reason: str | None
    #: The run's id in its table: `runs`, or `task_runs` when `task_id` is set.
    id: int
    task_id: int | None
    started_at: str

    def kind(self) -> RunKindOf:
        """Return the table the run is of: a task's when it names one."""
        return "run" if self.task_id is None else "task"


class _Reported(BaseModel):
    """The result line's `checklist` field, read apart from the rest of the result, as review answers are.

    Untrusted, so it is checked in `check`: a value of any shape is read here, and one that is not answers is dropped
    there, never taken as the whole result being invalid.
    """

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    checklist: object = None


def parse(text: str) -> object:
    """Return the `checklist` field of `text`'s result line, as the worker wrote it.

    Returns:
        The field's value, of any shape; None when there is no result line or it has no such field.
    """
    found = contract.last_line(_Reported, text)
    return found.checklist if found is not None else None


def check(lists: Iterable[Checklist], reported: object) -> Checked:
    """Check what a run given `lists` reported in `checklist`, against those lists.

    Each item of each list is answered as the run answered it, under its repository and id: `pass`, `fixed`, or
    `n/a`, as a word or as an object's `answer`, or `held` with a `reason`, as an object. An item it did not answer, or
    answered otherwise, is `unanswered`.

    Returns:
        An answer for every item of every list, in the lists' order, and why each answer that is none of theirs, or
        is not an answer, was dropped.
    """
    given = list(lists)
    dropped: list[str] = []
    by_repo: Mapping[object, object] = {}
    if isinstance(reported, Mapping):
        by_repo = cast("Mapping[object, object]", reported)
    elif reported is not None:
        dropped.append("checklist is not an object of repositories")
    known = {found.repo for found in given}
    dropped.extend(f"{_named(repo)}: no list of the run's" for repo in by_repo if repo not in known)
    answers: list[Answer] = []
    for found in given:
        said = by_repo.get(found.repo)
        items: Mapping[object, object] = {}
        if isinstance(said, Mapping):
            items = cast("Mapping[object, object]", said)
        elif said is not None:
            dropped.append(f"{found.repo}: not an object of items")
        ids = set(found.ids())
        dropped.extend(f"{found.repo} {_named(item)}: not an item of its list" for item in items if item not in ids)
        for item in found.ids():
            try:
                answers.append(_answer(found.repo, item, items.get(item)))
            except ValueError as e:
                dropped.append(f"{found.repo} {item}: {e}")
                answers.append(Answer(found.repo, item, ItemAnswer.UNANSWERED))
    return Checked(answers=tuple(answers), dropped=tuple(dropped))


def record(conn: sqlite3.Connection, run_id: int, checked: Checked | None, *, table: RunTable = "runs") -> None:
    """Record the answers of run `run_id` of `table`, in the transaction that closes it; none for one given no list."""
    if checked is None or not checked.answers:
        return
    column = _column(table)
    records.insert_rows(records.ChecklistAnswer, [column, "repo", "item", "answer", "reason"]).many(
        conn,
        [(run_id, a.repo, a.item, a.answer, a.reason) for a in checked.answers],
    )


def of_run(conn: sqlite3.Connection, run_id: int, *, table: RunTable = "runs") -> list[records.ChecklistAnswer]:
    """Return what run `run_id` of `table` answered of its lists, by repository and in each list's order.

    Returns:
        A row per item it was given; none for a run given no list.
    """
    query = records.select(records.ChecklistAnswer)
    match table:
        case "runs":
            query = query.where("run_id = ?", run_id)
        case "task_runs":
            query = query.where("task_run_id = ?", run_id)
        case _:
            assert_never(table)
    return query.order_by("repo, rowid").all(conn)


def counts(conn: sqlite3.Connection, now: datetime, days: int, *, repo: str | None = None) -> Counts:
    """Count the answers of the runs that started in the last `days` local days, today's so far included.

    The window is `canopy spend`'s and `canopy health`'s (`spend.window`), and a run, a worker's or a task's, is in it
    by when it started. A run still running has recorded no answers yet.

    Returns:
        A count per repository and item a run of the window was given; `repo`'s alone when it is named.
    """
    start, end = spend.window(now, days)
    since, until = db.format_time(start), db.format_time(end)
    query = _in_window(
        sql.select(
            "a.repo, a.item, count(*) AS reminded, sum(a.answer = ?) AS passed, sum(a.answer = ?) AS fixed, "
            "sum(a.answer = ?) AS held, sum(a.answer = ?) AS not_applicable, sum(a.answer = ?) AS unanswered",
            ItemAnswer.PASSED,
            ItemAnswer.FIXED,
            ItemAnswer.HELD,
            ItemAnswer.NOT_APPLICABLE,
            ItemAnswer.UNANSWERED,
        ),
        since,
        until,
        repo,
    )
    # An answer's rowid follows its list's order, as `record` wrote them, so the window's first run orders the items.
    query = query.group_by("a.repo, a.item").order_by("a.repo, min(a.rowid)")
    items = tuple(records.fetch_all(conn, ItemCounts, query))
    return Counts(since=since, until=until, days=days, repo=repo, items=items)


def details(
    conn: sqlite3.Connection,
    now: datetime,
    days: int,
    *,
    repo: str | None = None,
    limit: int = MAX_RUNS,
) -> Details:
    """Group the answers `counts` counts once more: by the runs that held or fixed each item, and by local ISO week.

    The window, the runs in it, and the items' order are `counts`'.

    Returns:
        For each item, the newest `limit` runs that held it and that fixed it, and its counts in every ISO week the
        window touches, none skipped; `repo`'s items alone when it is named.
    """
    start, end = spend.window(now, days)
    query = _in_window(
        sql.select(
            "a.repo, a.item, a.answer, a.reason, coalesce(a.run_id, a.task_run_id) AS id, t.task_id, "
            "coalesce(r.started_at, t.started_at) AS started_at",
        ),
        db.format_time(start),
        db.format_time(end),
        repo,
    ).order_by("a.repo, a.rowid")
    rows = records.fetch_all(conn, _Answered, query)
    # The items in `counts`' order: by repository, then as the window's first run given each listed them.
    order = list(dict.fromkeys((row.repo, row.item) for row in rows))
    shown = {ItemAnswer.HELD, ItemAnswer.FIXED}
    runs: dict[tuple[str, str, ItemAnswer], list[_Answered]] = {}
    tally: dict[tuple[str, str, str], Counter[ItemAnswer]] = {}
    for row in rows:
        if row.answer in shown:
            runs.setdefault((row.repo, row.item, row.answer), []).append(row)
        week = _week_of(db.parse_time(row.started_at).astimezone().date())
        tally.setdefault((row.repo, row.item, week), Counter())[row.answer] += 1

    def newest(repo: str, item: str, answer: ItemAnswer) -> tuple[AnsweredBy, ...]:
        found = sorted(runs.get((repo, item, answer), ()), key=lambda r: (r.started_at, r.id), reverse=True)
        return tuple(AnsweredBy(r.kind(), r.id, r.task_id, r.started_at, r.reason) for r in found[:limit])

    weeks = _weeks(start, end)
    return Details(
        items=tuple(
            ItemRuns(repo, item, held=newest(repo, item, ItemAnswer.HELD), fixed=newest(repo, item, ItemAnswer.FIXED))
            for repo, item in order
        ),
        weeks=tuple(
            WeekCounts(week, _counted(repo, item, tally.get((repo, item, week), Counter())))
            for repo, item in order
            for week in weeks
        ),
    )


def contract_text(lists: Sequence[Checklist]) -> str:
    """Return `{{CHECKLIST}}`: how a push is held for the lists of the run's repositories, and the field it answers in.

    Returns:
        The contract, starting with the blank line before it; empty for a run none of whose repositories has a list.
    """
    if not lists:
        return ""
    repos = ", ".join(f"`{found.repo}`" for found in lists)
    entry = '{"<item id>":"pass|fixed|n/a","<item id>":{"answer":"held","reason":"<why>"}}'
    return "\n".join(
        [
            "",
            "",
            (
                f"The operator keeps a checklist for {repos}: rules no linter checks. canopy's `pre-push` hook holds "
                "your first push of a stretch of work, before anything is sent, and prints the repository's list in a "
                "`[canopy] Push held` line. A held push is not a rejected one: diff the branch against its base, hold "
                "each item to the diff, commit a fix for each item that fails, and push again, and that push goes "
                "through. A push the remote rejects is still never retried."
            ),
            "",
            (
                f'That JSON object also carries `"checklist":{{"<repository>":{entry}}}`: under each repository above, '
                "each item of its list by its id. `pass` when the diff holds to it, `fixed` when this run committed "
                "the fix, `held` when you left it failing, with a `reason` saying why in a sentence or two, at most "
                f"{MAX_REASON} characters, and `n/a` when it is about nothing the diff changes. An item you leave out "
                "is recorded unanswered."
            ),
        ],
    )


def _answer(repo: str, item: str, said: object) -> Answer:
    """The answer to item `item` of `repo`'s list, from what the run said of it.

    Returns:
        The answer; `unanswered` for an item the run said nothing of.

    Raises:
        ValueError: what it said is not an answer, with why.
    """
    if said is None:
        return Answer(repo, item, ItemAnswer.UNANSWERED)
    reason: object = None
    if isinstance(said, Mapping):
        entry = cast("Mapping[object, object]", said)
        reason, said = entry.get("reason"), entry.get("answer")
    if not isinstance(said, str) or said not in GIVEN:
        raise ValueError(f"`answer` is not {', '.join(sorted(GIVEN))}")
    answer = ItemAnswer(said)
    if answer is not ItemAnswer.HELD:
        return Answer(repo, item, answer)
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("`held` gives no reason")
    return Answer(repo, item, answer, reason.strip()[:MAX_REASON])


def _in_window(query: sql.Select, since: str, until: str, repo: str | None) -> sql.Select:
    # `query`'s answers: those of the worker and task runs that started in `[since, until)`, of `repo` when named.
    query = (
        query.from_("checklist_answers a")
        .left_join("runs r ON r.id = a.run_id")
        .left_join("task_runs t ON t.id = a.task_run_id")
        .where("coalesce(r.started_at, t.started_at) >= ? AND coalesce(r.started_at, t.started_at) < ?", since, until)
    )
    return query if repo is None else query.where("a.repo = ?", repo)


def _counted(repo: str, item: str, answers: Mapping[ItemAnswer, int]) -> ItemCounts:
    # An item's counts, from how many runs gave each answer.
    return ItemCounts(
        repo=repo,
        item=item,
        reminded=sum(answers.values()),
        passed=answers.get(ItemAnswer.PASSED, 0),
        fixed=answers.get(ItemAnswer.FIXED, 0),
        held=answers.get(ItemAnswer.HELD, 0),
        not_applicable=answers.get(ItemAnswer.NOT_APPLICABLE, 0),
        unanswered=answers.get(ItemAnswer.UNANSWERED, 0),
    )


def _weeks(start: datetime, end: datetime) -> list[str]:
    # Every local ISO week the window `[start, end)` touches, oldest first.
    first, last = start.astimezone().date(), (end.astimezone() - timedelta(days=1)).date()
    days = (last - first).days + 1
    return list(dict.fromkeys(_week_of(first + timedelta(days=n)) for n in range(days)))


def _week_of(day: date) -> str:
    # The ISO week a local day is in, as `2026-W41`: Monday to Sunday, as `spend`'s first-call weeks are.
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def _column(table: RunTable) -> Literal["run_id", "task_run_id"]:
    # The column an answer names a run of `table` in.
    match table:
        case "runs":
            return "run_id"
        case "task_runs":
            return "task_run_id"
        case _:
            assert_never(table)


def _named(key: object) -> str:
    # A key the worker wrote, as the note names it: printable, and short.
    return repr(str(key)[:64])
