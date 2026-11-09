"""What the mock journal's ended worker and task runs changed (DESIGN §45), for `python -m canopy.serve --mock`.

Run 39, ABC-099's implement in web, started from main, origin having no branch yet, and pushed PR 88's head: both its
diffs are kept, so its page names the files it changed and shows their diff when opened. Run 40, ABC-100's
fix-ci, failed with its fix still in its slot: its diffs are of work not on origin. Run 37, ABC-100's implement, kept
neither, and its page says why. Task 1's run in web kept both, as a worker run's do. Run 45's record is `drafts`'s,
whose PR page reads its branch's diff.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import records, review_diff, run_changes
from canopy.serve.mock.reviews import SHA_88

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

#: Where main was when run 39 started, which its branch still leaves.
_MAIN = "71c3e0a5" + "1" * 32
#: Where PR 86's branch was when run 40 started, and the commit it made but never pushed.
_HEAD_86 = "a40d2f97" + "4" * 32
_UNPUSHED_86 = "d8e61b30" + "8" * 32
#: Where main was when task 1's run started, and the head it pushed.
_MAIN_TASK = "2c9a17e4" + "2" * 32
_HEAD_97 = "5e0b7c2a9d41f3e86a2c4b7d9e1f0a3c5b8d2e4f"
#: Why run 37 kept no diff, as `runs.changes` says it.
_NOT_KEPT = "the run left no branch on origin and no commit of its own in its slot"

_DEBOUNCE = """\
diff --git a/src/search/useSearch.ts b/src/search/useSearch.ts
index 9c41e07..b2d8a15 100644
--- a/src/search/useSearch.ts
+++ b/src/search/useSearch.ts
@@ -1,14 +1,22 @@
 import { useEffect, useState } from 'react'
 import type { Result } from './types'

+const WAIT_MS = 250
+
 export function useSearch(query: string) {
     const [results, setResults] = useState<Result[]>([])

     useEffect(() => {
-        fetch(`/api/search?q=${encodeURIComponent(query)}`)
-            .then((r) => r.json())
-            .then((found: Result[]) => setResults(found))
+        const controller = new AbortController()
+        const timer = setTimeout(() => {
+            fetch(`/api/search?q=${encodeURIComponent(query)}`, { signal: controller.signal })
+                .then((r) => r.json())
+                .then((found: Result[]) => setResults(found))
+        }, WAIT_MS)
+        return () => {
+            clearTimeout(timer)
+            controller.abort()
+        }
     }, [query])

     return results
 }
diff --git a/src/search/useSearch.test.ts b/src/search/useSearch.test.ts
new file mode 100644
index 0000000..4e7f1c2
--- /dev/null
+++ b/src/search/useSearch.test.ts
@@ -0,0 +1,9 @@
+import { renderHook } from '@testing-library/react'
+import { expect, it, vi } from 'vitest'
+
+it('waits 250 ms after the last key', () => {
+    vi.useFakeTimers()
+    const fetched = vi.spyOn(globalThis, 'fetch')
+    renderHook(() => useSearch('dog'))
+    expect(fetched).not.toHaveBeenCalled()
+})
"""

_RETRY = """\
diff --git a/e2e/checkout.spec.ts b/e2e/checkout.spec.ts
index 51a0c3e..e07b9d4 100644
--- a/e2e/checkout.spec.ts
+++ b/e2e/checkout.spec.ts
@@ -12,7 +12,7 @@ test('pays with a card', async ({ page }) => {
     await page.getByRole('button', { name: 'Pay' }).click()
-    await page.waitForTimeout(2000)
+    await expect(page.frameLocator('#payment').getByText('Card number')).toBeVisible()
     await page.frameLocator('#payment').getByLabel('Card number').fill('4242 4242 4242 4242')
"""

_BUNDLE = """\
diff --git a/src/checkout/DatePicker.tsx b/src/checkout/DatePicker.tsx
index 0b4e6f2..c71a9d8 100644
--- a/src/checkout/DatePicker.tsx
+++ b/src/checkout/DatePicker.tsx
@@ -1,4 +1,4 @@
-import moment from 'moment'
+import { format } from 'date-fns'

 export function DatePicker({ value }: { value: Date }) {
-    return <span>{moment(value).format('LL')}</span>
+    return <span>{format(value, 'PPP')}</span>
 }
"""


def seed(conn: sqlite3.Connection) -> None:
    """Record what each ended run changed, as `_run` and `_task` record it when they end, and keep its diffs."""
    run_39 = records.select(records.Run).where("id = ?", 39).one(conn)
    run_40 = records.select(records.Run).where("id = ?", 40).one(conn)
    task_run = records.select(records.TaskRun).where("id = ?", 1).one(conn)
    if run_39 is None or run_40 is None or task_run is None:
        return
    _keep(run_39.log_path, "web", _DEBOUNCE, _DEBOUNCE)
    _keep(run_40.log_path, "web", _RETRY, _RETRY)
    _keep(task_run.log_path, "web", _BUNDLE, _BUNDLE)
    run_changes.record(
        conn,
        39,
        [
            run_changes.Change(
                "web",
                _MAIN,
                start_on_base=True,
                end=SHA_88,
                merge_base=_MAIN,
                change_kept=True,
                branch_kept=True,
                counted=counted(_DEBOUNCE),
            ),
        ],
    )
    run_changes.record(
        conn,
        40,
        [
            run_changes.Change(
                "web",
                _HEAD_86,
                end=_HEAD_86,
                merge_base=_MAIN,
                unpushed=_UNPUSHED_86,
                change_kept=True,
                branch_kept=True,
                counted=counted(_RETRY),
            ),
        ],
    )
    run_changes.record(
        conn,
        37,
        [run_changes.Change("web", _MAIN, start_on_base=True, missing=_NOT_KEPT)],
    )
    run_changes.record(
        conn,
        1,
        [
            run_changes.Change(
                "web",
                _MAIN_TASK,
                start_on_base=True,
                end=_HEAD_97,
                merge_base=_MAIN_TASK,
                change_kept=True,
                branch_kept=True,
                counted=counted(_BUNDLE),
            ),
        ],
        table="task_runs",
    )


def counted(diff: str) -> run_changes.Counted:
    """What git would count of `diff`, as `runs.changes` records it.

    Returns:
        Each file's lines added and removed, and their totals.
    """
    return run_changes.counted(
        [
            review_diff.Count(
                f.path,
                f.old_path,
                sum(ln.kind == "add" for h in f.hunks for ln in h.lines),
                sum(ln.kind == "del" for h in f.hunks for ln in h.lines),
            )
            for f in review_diff.parse(diff).files
        ],
    )


def _keep(log_path: str | Path, repo: str, change: str, branch: str) -> None:
    """Keep a run's two diffs of `repo` beside its log, as `runs.changes` keeps them."""
    path = run_changes.change_path(log_path, repo)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    review_diff.keep(path, change)
    review_diff.keep(review_diff.run_path_for(log_path, repo), branch)
