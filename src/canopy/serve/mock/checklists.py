"""The operator's checklists and the mock journal's answers to them (DESIGN §42), for `python -m canopy.serve --mock`.

`web` and `api` keep a list, in the mock's `paths.checklists`; `mobile` none. T0's ended worker runs in `web` answered
its list, and ABC-102's, in `api`, answered that one's, so the reports' checklist view counts every answer, each item in
its list's order. The running runs have recorded none yet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import checklist_answers, checklists
from canopy.core.checklist_answers import Answer, Checked
from canopy.core.vocab import ItemAnswer

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

#: Each list's file, as the operator wrote it: its items in order, each a heading, its optional lines, and its rule.
LISTS = {
    "web": """\
## no-fixed-sleeps
paths: src/**/*.test.ts, e2e/

A test waits on a condition, never on time. Passes: `await expect.poll(() => count()).toBe(3)`. Fails:
`await page.waitForTimeout(500)`, or a `setTimeout` a test awaits.

## query-keys
paths: src/

Every query's key and fetcher live in `src/api/queries.ts`, and a component calls `useQuery(xQuery)`. Fails: a
`queryKey` written inline in a component.

## no-any
severity: major

No `any`, written or inferred. Passes: `unknown`, narrowed before use. Fails: `as any`, or a parameter left untyped.

## i18n-strings
paths: src/components/, src/routes/

Text a person reads comes from the message catalog, `t('...')`, never a literal in the markup.
""",
    "api": """\
## general-types
paths: src/**/*.py

A parameter takes the most general type its body needs: `Iterable` for one pass, `Mapping` for a dict it only reads.
Passes: `def total(xs: Iterable[int])` over a body that loops once. Fails: `def total(xs: list[int])` over the same.

## newspaper-order

A module reads top-down: its public names first, most important first, then each private helper below the first
function that calls it.

## doc-comments
paths: src/

A public function has a Google docstring, opening with a one-line summary that ends in a period.

## migration-companion
paths: migrations/
severity: blocking

A new migration has its companion under `tests/migrations/`, of the same number, opening with the migration's sha256.
Passes: both files in the diff. Fails: a migration alone.
""",
}
#: Each list's items, in its order.
_ITEMS = {repo: tuple(item.id for item in checklists.parse(repo, text)[0]) for repo, text in LISTS.items()}
_P, _F, _H, _NA, _U = (
    ItemAnswer.PASSED,
    ItemAnswer.FIXED,
    ItemAnswer.HELD,
    ItemAnswer.NOT_APPLICABLE,
    ItemAnswer.UNANSWERED,
)
#: What each run answered of its repository's items, in their order, and why it held one.
_ANSWERS: tuple[tuple[int, str, tuple[ItemAnswer, ...], str | None], ...] = (
    (37, "web", (_F, _P, _P, _NA), None),
    (38, "web", (_P, _F, _H, _NA), "The v1 client's types are generated; typing them by hand is ABC-112."),
    (39, "web", (_P, _P, _P, _F), None),
    (45, "web", (_P, _P, _P, _U), None),
    (42, "api", (_P, _H, _U, _NA), "The CSV writer sits beside the export route, as the module's other writers do."),
)


def write(directory: Path) -> None:
    """Write each list to `directory`, the mock's `paths.checklists`, a file to a repository."""
    directory.mkdir(parents=True)
    for repo, text in LISTS.items():
        (directory / f"{repo}{checklists.SUFFIX}").write_text(text)


def seed(conn: sqlite3.Connection) -> None:
    """Record each run's answers, as `_run` records them when it ends."""
    for run_id, repo, answers, reason in _ANSWERS:
        given = tuple(
            Answer(repo, item, answer, reason if answer is ItemAnswer.HELD else None)
            for item, answer in zip(_ITEMS[repo], answers, strict=True)
        )
        checklist_answers.record(conn, run_id, Checked(answers=given))
