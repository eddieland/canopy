"""The mock journal's answers to the operator's checklists (DESIGN §42), for `python -m canopy.serve --mock`.

`web` and `api` keep a list; `mobile` none. T0's ended worker runs in `web` answered its list, and ABC-102's, in `api`,
answered that one's, so the reports' checklist view counts every answer, each item in its list's order. The running
runs have recorded none yet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import checklist_answers
from canopy.core.checklist_answers import Answer, Checked
from canopy.core.vocab import ItemAnswer

if TYPE_CHECKING:
    import sqlite3

#: Each list's items, in its order.
_ITEMS = {
    "web": ("no-fixed-sleeps", "query-keys", "no-any", "i18n-strings"),
    "api": ("general-types", "newspaper-order", "doc-comments", "migration-companion"),
}
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


def seed(conn: sqlite3.Connection) -> None:
    """Record each run's answers, as `_run` records them when it ends."""
    for run_id, repo, answers, reason in _ANSWERS:
        given = tuple(
            Answer(repo, item, answer, reason if answer is ItemAnswer.HELD else None)
            for item, answer in zip(_ITEMS[repo], answers, strict=True)
        )
        checklist_answers.record(conn, run_id, Checked(answers=given))
