"""The operator's checklists and the mock journal's answers to them (DESIGN §42), for `python -m canopy.serve --mock`.

`web` and `api` keep a list, in the mock's `paths.checklists`; `mobile` none. T0's ended worker runs in `web` answered
its list, and ABC-102's, in `api`, answered that one's, so the reports' checklist view counts every answer, each item in
its list's order. The running runs have recorded none yet. ABC-103's run, held in `web`, keeps the diff of what it
pushed after the list, the `query-keys` fix it answered, so its page shows the stretch under its answers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import checklist_answers, checklists, records, review_diff
from canopy.core.checklist_answers import Answer, Checked, Pushed
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

#: The run whose push was held.
HELD_RUN = 38
#: The commit the held run's list was shown at.
_SHOWN = "5b1e0c47" + "a" * 32
#: The commit it pushed next, which it left on origin.
PUSHED = "c9d24f83" + "b" * 32
#: The diff between the two: the `query-keys` fix, a part of what the run changed (`run_diffs`).
STRETCH = """\
diff --git a/src/api/queries.ts b/src/api/queries.ts
index 1f0a3c2..8e4b7d5 100644
--- a/src/api/queries.ts
+++ b/src/api/queries.ts
@@ -40,3 +40,11 @@ export function invoicesQuery(account: string) {
         queryFn: () => fetchInvoices(account),
     })
 }
+
+/** An invoice's lines, from the v2 endpoint. */
+export function invoiceLinesQuery(id: string) {
+    return queryOptions({
+        queryKey: ['invoice', id, 'lines'],
+        queryFn: () => fetchInvoiceLines(id),
+    })
+}
diff --git a/src/billing/InvoiceLines.tsx b/src/billing/InvoiceLines.tsx
index 3d6e9a1..a72c0f4 100644
--- a/src/billing/InvoiceLines.tsx
+++ b/src/billing/InvoiceLines.tsx
@@ -1,11 +1,8 @@
 import { useQuery } from '@tanstack/react-query'

-import { fetchInvoiceLines } from '@/api/billing'
+import { invoiceLinesQuery } from '@/api/queries'

 export function InvoiceLines({ id }: { id: string }) {
-    const { data } = useQuery({
-        queryKey: ['invoice', id, 'lines'],
-        queryFn: () => fetchInvoiceLines(id),
-    })
+    const { data } = useQuery(invoiceLinesQuery(id))
     return <LineTable lines={data ?? []} />
 }
"""


def write(directory: Path) -> None:
    """Write each list to `directory`, the mock's `paths.checklists`, a file to a repository."""
    directory.mkdir(parents=True)
    for repo, text in LISTS.items():
        (directory / f"{repo}{checklists.SUFFIX}").write_text(text)


def seed(conn: sqlite3.Connection) -> None:
    """Record each run's answers, as `_run` records them when it ends, and the held run's stretch, with its diff."""
    for run_id, repo, answers, reason in _ANSWERS:
        given = tuple(
            Answer(repo, item, answer, reason if answer is ItemAnswer.HELD else None)
            for item, answer in zip(_ITEMS[repo], answers, strict=True)
        )
        pushed = (Pushed(repo, _SHOWN, PUSHED),) if run_id == HELD_RUN else ()
        checklist_answers.record(conn, run_id, Checked(answers=given, pushes=pushed))
    held = records.select(records.Run).where("id = ?", HELD_RUN).one(conn)
    if held is not None:
        kept = checklist_answers.diff_path(held.log_path, "web", _SHOWN)
        kept.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        review_diff.keep(kept, STRETCH)
