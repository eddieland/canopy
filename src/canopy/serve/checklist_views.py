"""Each repository's checklist, and how worker and task runs answered it, as the API sends them (DESIGN §42).

The lists as the operator's files hold them now, each read and parsed as a run's would be, one canopy cannot use with
why. The counts by the backend's clock, as `canopy checklist` prints them, with the runs behind each item's `held` and
`fixed` answers, a held one's reason on one line, and the counts by week; and one run's answers, as `canopy show run:ID`
and `task:N` print them, a held item's reason among them: the worker's words, made printable and sent as text. With
them, what the run pushed after being shown each list: each stretch's commits and the diff kept beside its log, read
within a review's diff's bounds (`review_diff.read`), and said to be missing, or removed by retention, when it is.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, assert_never

from canopy.core import checklist_answers, checklists, conversation, db, health, review_diff, spend
from canopy.core.vocab import ItemAnswer
from canopy.serve.diff_views import diff_view
from canopy.serve.schema import ChecklistAnswer, ChecklistStretch
from canopy.serve.schema import ItemAnswer as AnswerWord
from canopy.serve.schema.checklist import (
    ChecklistCounts,
    ChecklistItem,
    ChecklistItemCounts,
    ChecklistList,
    ChecklistPrevious,
    ChecklistRun,
    ChecklistWeek,
    RepoChecklist,
)
from canopy.serve.transcript_views import removed_after

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable

    from canopy.core.checklist_answers import AnsweredBy, RunTable
    from canopy.core.context import Context
    from canopy.serve.backend import Backend

#: How many of a run's stretches its page is sent, each with its diff, as large as a review's may be: far more than a
#: run makes, as it is held again only after half an hour's work.
MAX_STRETCHES = 5


def lists(ctx: Context) -> ChecklistList:
    """Read each mapped repository's list from `paths.checklists` now, as the next run in it would.

    Returns:
        Each repository of the map, in its order, with its list's items; with none when it has no file, or when the
        file is one canopy would refuse a run over, with why.
    """
    directory = ctx.config.paths.checklists
    found: list[RepoChecklist] = []
    for repo in ctx.ws.repos:
        file = None if directory is None else str(directory / f"{repo.name}{checklists.SUFFIX}")
        try:
            loaded = checklists.load(ctx.config, repo.name)
        except checklists.ChecklistError as e:
            found.append(RepoChecklist(repo=repo.name, file=file, items=[], error=str(e)))
            continue
        items = [] if loaded is None else [_item(item) for item in loaded.items]
        found.append(RepoChecklist(repo=repo.name, file=file, items=items))
    return ChecklistList(directory=None if directory is None else str(directory), repos=found)


def checklist_counts(backend: Backend, ctx: Context, days: int, *, repo: str | None = None) -> ChecklistCounts:
    """Count the answers of the worker and task runs that started in the last `days` local days, as `canopy checklist`.

    Returns:
        A count per repository and item a run of the window was given, with the runs behind its `held` and `fixed`
        answers, and its counts in each ISO week of the window; `repo`'s alone when it is named.
    """
    now = backend.clock()
    # One snapshot for both reads, so a run that ends between them cannot leave an item in one and out of the other.
    with db.read_snapshot(ctx.conn):
        found = checklist_answers.counts(ctx.conn, now, days, repo=repo)
        grouped = checklist_answers.details(ctx.conn, now, days, repo=repo)
        before = checklist_answers.between(ctx.conn, *spend.window_before(found.since, days), repo=repo)
    runs = {(r.repo, r.item): r for r in grouped.items}
    paths = _paths(ctx, {c.repo for c in found.items})
    return ChecklistCounts(
        since=db.parse_time(found.since),
        until=db.parse_time(found.until),
        days=found.days,
        repo=found.repo,
        items=[
            ChecklistItemCounts(
                repo=c.repo,
                item=c.item,
                reminded=c.reminded,
                passed=c.passed,
                fixed=c.fixed,
                held=c.held,
                not_applicable=c.not_applicable,
                unanswered=c.unanswered,
                held_by=c.held_by,
                paths=paths.get((c.repo, c.item)),
                held_runs=_runs(runs[c.repo, c.item].held),
                fixed_runs=_runs(runs[c.repo, c.item].fixed),
            )
            for c in found.items
        ],
        weeks=[
            ChecklistWeek(
                repo=w.counts.repo,
                item=w.counts.item,
                week=w.week,
                reminded=w.counts.reminded,
                passed=w.counts.passed,
                fixed=w.counts.fixed,
                held=w.counts.held,
                not_applicable=w.counts.not_applicable,
                unanswered=w.counts.unanswered,
            )
            for w in grouped.weeks
        ],
        previous=ChecklistPrevious(
            since=db.parse_time(before.since),
            until=db.parse_time(before.until),
            reminded=before.reminded,
            held=before.held,
            unanswered=before.unanswered,
        ),
    )


def run_answers(conn: sqlite3.Connection, run_id: int, *, table: RunTable = "runs") -> list[ChecklistAnswer]:
    """What run `run_id` of `table` answered of its repositories' checklists, as `canopy show` prints it.

    Returns:
        A row per item it was given, by repository and in each list's order; none for a run given no list.
    """
    return [
        ChecklistAnswer(
            repo=a.repo,
            item=a.item,
            answer=_word(a.answer),
            reason=_text(a.reason) if a.reason is not None else None,
        )
        for a in checklist_answers.of_run(conn, run_id, table=table)
    ]


def run_stretches(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    log_path: str,
    ended_at: str | None,
    table: RunTable = "runs",
) -> tuple[list[ChecklistStretch], int]:
    """What run `run_id` of `table` pushed after being shown its lists, each stretch with the diff kept beside its log.

    `log_path` is the run's log, as the journal names it, and `ended_at` when the run ended, which says whether
    retention removed a diff that is gone. Each diff is read as a review's is, within its bounds: a file that is
    missing, a symlink, or not a regular file is no diff, never an empty one.

    Returns:
        The first `MAX_STRETCHES` stretches, in the order the run was shown its lists, and how many more there are.
    """
    pushes = checklist_answers.pushes_of(conn, run_id, table=table)
    stretches: list[ChecklistStretch] = []
    for p in pushes[:MAX_STRETCHES]:
        kept = checklist_answers.diff_path(log_path, p.repo, p.shown_sha)
        found = review_diff.read(kept)
        stretches.append(
            ChecklistStretch(
                repo=p.repo,
                shown_sha=p.shown_sha,
                pushed_sha=p.pushed_sha,
                diff=diff_view(found) if found is not None else None,
                diff_removed_after_days=removed_after(conn, kept, ended_at, "run_files_days"),
            ),
        )
    return stretches, max(len(pushes) - MAX_STRETCHES, 0)


def _item(item: checklists.Item) -> ChecklistItem:
    # One item as the operator wrote it: their own text, which the parser has already held to a list's bounds.
    return ChecklistItem(id=item.id, paths=list(item.paths), severity=item.severity, rule=item.rule)


def _paths(ctx: Context, repos: Iterable[str]) -> dict[tuple[str, str], list[str]]:
    # The paths each item of `repos`' lists names now, by repository and id: none for a list canopy cannot read, whose
    # items the page then cannot say are scoped or not, nor for a repository the workspace no longer maps, whose name
    # is the journal's and never names a file.
    found: dict[tuple[str, str], list[str]] = {}
    mapped = {r.name for r in ctx.ws.repos}
    for repo in sorted(mapped.intersection(repos)):
        try:
            loaded = checklists.load(ctx.config, repo)
        except checklists.ChecklistError:
            continue
        found.update({(repo, item.id): list(item.paths) for item in loaded.items} if loaded is not None else {})
    return found


def _runs(found: Iterable[AnsweredBy]) -> list[ChecklistRun]:
    # The runs behind an item's answers, each held one's reason on a line.
    return [
        ChecklistRun(
            kind=r.kind,
            id=r.id,
            task_id=r.task_id,
            started_at=db.parse_time(r.started_at),
            reason=_line(r.reason) if r.reason is not None else None,
        )
        for r in found
    ]


def _word(answer: ItemAnswer) -> AnswerWord:
    # The API's word for an answer, the journal's own.
    match answer:
        case ItemAnswer.PASSED:
            return "pass"
        case ItemAnswer.FIXED:
            return "fixed"
        case ItemAnswer.HELD:
            return "held"
        case ItemAnswer.NOT_APPLICABLE:
            return "n/a"
        case ItemAnswer.UNANSWERED:
            return "unanswered"
        case _:
            assert_never(answer)


def _text(reason: str) -> str | None:
    # The worker's reason as a page lays it out: control characters dropped, line breaks kept, blank ends cut.
    return "\n".join(line.rstrip() for line in conversation.printable(reason).splitlines()).strip("\n") or None


def _line(reason: str) -> str | None:
    # The worker's reason on one line, printable, and cut as the health report cuts a note: a hover's worth.
    text = " ".join(conversation.printable(reason).split())
    if not text:
        return None
    return text if len(text) <= health.NOTE_LIMIT else text[: health.NOTE_LIMIT - 3] + "..."
