"""The mock journal's review runs and the diffs beside their logs (DESIGN §21), for `python -m canopy.serve --mock`.

PR 88 (ABC-099) was reviewed twice: its first commit had a blocking finding, its second has two smaller ones, anchored
on its diff. The operator's own API PR, which `review.query` matched, was reviewed clean; PR 91's review never
reported a result. A coworker's PR 95 waits on its review, at the operator's request.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from canopy.core import review_diff
from canopy.core.review_result import Finding, ReviewResult
from canopy.infra import logs

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from pathlib import Path

PR_88 = "https://github.com/acme/web/pull/88"
PR_91 = "https://github.com/acme/web/pull/91"
PR_12 = "https://github.com/acme/api/pull/12"
PR_95 = "https://github.com/acme/web/pull/95"
SHA_88_FIRST = "5e1c0d2a" + "7" * 32
SHA_88 = "9b2f4c61" + "3" * 32
SHA_91 = "c47a91e0" + "5" * 32
SHA_12 = "0d8e3b57" + "1" * 32
_UNKNOWN = "the reviewer's last line was not a valid result"

_STALE = ReviewResult(
    status="done",
    verdict="findings",
    impact="normal",
    summary="The debounce works, but a slow response can overwrite a newer one.",
    findings=[
        Finding(
            severity="blocking",
            title="A stale response replaces the results of a newer query",
            location="src/search/useSearch.ts:11",
            detail="Nothing cancels the earlier fetch, so typing `ab` then `abc` shows `ab`'s results whenever they "
            "arrive last.",
        )
    ],
)
# What review 4 reported, its reviewer's last line in its transcript too.
LATEST = ReviewResult(
    status="done",
    verdict="findings",
    impact="normal",
    summary="Stale requests are aborted now. Two smaller things remain; neither holds the merge on its own.",
    findings=[
        Finding(
            severity="major",
            title="A failed request leaves the spinner on",
            location="src/search/useSearch.ts:15",
            detail="`setLoading(false)` runs only after a successful `json()`. A network error or a 500 rejects "
            "first, so `loading` stays true until the next query.\nMove it into a `finally`, and skip it for an "
            "aborted request.",
        ),
        Finding(
            severity="minor",
            title="The debounce delay is a bare number",
            location="src/search/SearchBox.tsx:6",
            detail="Name it, as `SEARCH_DEBOUNCE_MS` beside the other timings in `src/config.ts`.",
        ),
        Finding(
            severity="minor",
            title="No test covers an aborted request",
            location="src/search/useSearch.test.ts",
            detail="The new hook's tests check the debounce only.",
        ),
    ],
)
_CLEAN = ReviewResult(
    status="done", verdict="clean", impact="low", summary="A README fix: the port it names.", findings=[]
)

DIFF_88 = """\
diff --git a/src/search/SearchBox.tsx b/src/search/SearchBox.tsx
index 4a1f2b3..7c9d0e1 100644
--- a/src/search/SearchBox.tsx
+++ b/src/search/SearchBox.tsx
@@ -1,6 +1,8 @@
 import { useState } from 'react'
+import { useDebounced } from './useDebounced'

 export function SearchBox({ onSearch }: { onSearch: (q: string) => void }) {
     const [query, setQuery] = useState('')
-    return <input value={query} onChange={(e) => { setQuery(e.target.value); onSearch(e.target.value) }} />
+    const search = useDebounced(onSearch, 250)
+    return <input value={query} onChange={(e) => { setQuery(e.target.value); search(e.target.value) }} />
 }
diff --git a/src/search/useSearch.ts b/src/search/useSearch.ts
new file mode 100644
index 0000000..b3e8f42
--- /dev/null
+++ b/src/search/useSearch.ts
@@ -0,0 +1,21 @@
+import { useEffect, useState } from 'react'
+import type { Result } from './types'
+
+export function useSearch(query: string) {
+    const [results, setResults] = useState<Result[]>([])
+    const [loading, setLoading] = useState(false)
+
+    useEffect(() => {
+        const controller = new AbortController()
+        setLoading(true)
+        fetch(`/api/search?q=${encodeURIComponent(query)}`, { signal: controller.signal })
+            .then((r) => r.json())
+            .then((found: Result[]) => {
+                setResults(found)
+                setLoading(false)
+            })
+        return () => controller.abort()
+    }, [query])
+
+    return { results, loading }
+}
"""
# Blank context lines are written empty, as some tools save them; the reader takes them as context.
DIFF_12 = """\
diff --git a/README.md b/README.md
index 1d2e3f4..5a6b7c8 100644
--- a/README.md
+++ b/README.md
@@ -12,3 +12,3 @@ ## Running locally

-Run `make serve` and open http://localhost:8000.
+Run `make serve` and open http://localhost:8080.

"""


def seed(conn: sqlite3.Connection, state_dir: Path, at: Callable[[int], str]) -> None:
    """Insert the review runs, and write the diffs beside their logs, under `state_dir/reviews/`."""
    reviews = state_dir / "reviews"
    reviews.mkdir(mode=0o700, exist_ok=True)
    rows = (
        # id, PR, commit, ticket, repo, started, ended, status, result, cost, diff
        (1, PR_88, SHA_88_FIRST, "ABC-099", "web", -100, -97, "done", _STALE.model_dump_json(), 0.21, None),
        (2, PR_12, SHA_12, None, "api", -80, -79, "done", _CLEAN.model_dump_json(), 0.06, DIFF_12),
        (3, PR_91, SHA_91, "ABC-103", "web", -70, -69, "unknown", json.dumps({"harness": _UNKNOWN}), 0.02, None),
        (4, PR_88, SHA_88, "ABC-099", "web", -58, -56, "done", LATEST.model_dump_json(), 0.24, DIFF_88),
    )
    for run_id, pr, sha, ticket, repo, started, ended, status, result, cost, diff in rows:
        log_path = reviews / f"{run_id}.log"
        conn.execute(
            "INSERT INTO review_runs (id, tick_id, pr_url, sha, ticket_key, repo, purpose, started_at, ended_at, "
            "status, result_json, log_path, base_branch, session_id, cost_usd) "
            "VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'main', ?, ?)",
            (
                run_id,
                pr,
                sha,
                ticket,
                repo,
                "query" if ticket is None else "own",
                at(started),
                at(ended),
                status,
                result,
                str(log_path),
                f"ses_review{run_id}",
                cost,
            ),
        )
        if diff is not None:
            logs.write_private(review_diff.path_for(log_path), diff)
    # A coworker's PR the operator asked canopy to review from the web UI (DESIGN §21).
    conn.execute(
        "INSERT INTO review_requests (pr_url, created_at, channel, notes) VALUES (?, ?, 'web', ?)",
        (PR_95, at(-20), "The author asked for a close look at the retry loop; I'm not sure it backs off."),
    )
