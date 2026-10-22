"""The mock journal's review runs and the diffs beside their logs (DESIGN §21), for `python -m canopy.serve --mock`.

PR 88 (ABC-099) was reviewed twice: its first commit had a blocking finding, its second has two smaller ones, anchored
on its diff. The operator's own API PR, which no ticket opened, was reviewed clean at their request; PR 91's review
never reported a result. Dana's PR 95 waits on its review, at the operator's request, read once so canopy knows whose
it is. Carol's PR 14 was reviewed at the operator's request too, so it has a draft of a review on it (DESIGN §34), as
the clean review does: two findings on its diff's lines are comments, and one about a file it does not touch is in the
body (`drafts`). Carol's waits on the operator; the clean review's they published, as a comment on their own PR.

The operator has seen every review but the clean one, review 2, which is new to them since they asked for it (DESIGN
§22). Opening a review's page marks it seen, a write, so no test against the journal that never changes opens review
2's.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from canopy.core import db, review_diff, review_drafts, sql
from canopy.core.review_result import Finding, ReviewResult
from canopy.core.vocab import ReviewDraftStatus
from canopy.infra import logs

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from pathlib import Path

PR_88 = "https://github.com/acme/web/pull/88"
PR_91 = "https://github.com/acme/web/pull/91"
PR_12 = "https://github.com/acme/api/pull/12"
PR_95 = "https://github.com/acme/web/pull/95"
PR_14 = "https://github.com/acme/api/pull/14"
SHA_88_FIRST = "5e1c0d2a" + "7" * 32
SHA_88 = "9b2f4c61" + "3" * 32
SHA_91 = "c47a91e0" + "5" * 32
SHA_12 = "0d8e3b57" + "1" * 32
SHA_14 = "a61f7c08" + "4" * 32
#: The reviews that have a draft: those of PRs the loop does not own that ended `done`.
DRAFTED = (2, 5)
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
        ),
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
# What review 5 reported on Carol's PR: two findings on lines of its diff, and one about a file it does not touch.
_CAROL = ReviewResult(
    status="done",
    verdict="findings",
    impact="normal",
    summary="The retry works for a 503, but a request that keeps failing comes back looking like an answer.",
    findings=[
        Finding(
            severity="major",
            title="The last 503 is returned as if it were an answer",
            location="api/upstream.py:15",
            detail="After the last attempt the loop falls through and returns the 503, so a caller cannot tell giving "
            "up from a response. Raise once the attempts run out.",
        ),
        Finding(
            severity="minor",
            title="`attempt` is never read",
            location="api/upstream.py:9",
            detail="Call it `_`.",
        ),
        Finding(
            severity="minor",
            title="No test stops the backoff",
            location="tests/test_upstream.py",
            detail="Nothing checks that it gives up after five attempts.",
        ),
    ],
)
_CLEAN = ReviewResult(
    status="done",
    verdict="clean",
    impact="low",
    summary="A README fix: the port it names.",
    findings=[],
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
DIFF_14 = """\
diff --git a/api/upstream.py b/api/upstream.py
index 3c4d5e6..8f9a0b1 100644
--- a/api/upstream.py
+++ b/api/upstream.py
@@ -1,7 +1,15 @@
 import time
+import random

 import httpx


-def fetch(url: str) -> httpx.Response:
-    return httpx.get(url, timeout=5)
+def fetch(url: str, attempts: int = 5) -> httpx.Response:
+    delay = 0.5
+    for attempt in range(attempts):
+        response = httpx.get(url, timeout=5)
+        if response.status_code != 503:
+            return response
+        time.sleep(delay)
+        delay = delay * 2 + random.random()
+    return response
"""


def seed(conn: sqlite3.Connection, state_dir: Path, at: Callable[[int], str]) -> None:
    """Insert the review runs, and write the diffs beside their logs, under `state_dir/reviews/`."""
    reviews = state_dir / "reviews"
    reviews.mkdir(mode=0o700, exist_ok=True)
    rows = (
        # id, PR, commit, ticket, repo, purpose, started, ended, status, result, cost, diff
        (1, PR_88, SHA_88_FIRST, "ABC-099", "web", "own", -100, -97, "done", _STALE.model_dump_json(), 0.21, None),
        (2, PR_12, SHA_12, None, "api", "request", -80, -79, "done", _CLEAN.model_dump_json(), 0.06, DIFF_12),
        (3, PR_91, SHA_91, "ABC-103", "web", "own", -70, -69, "unknown", json.dumps({"harness": _UNKNOWN}), 0.02, None),
        (4, PR_88, SHA_88, "ABC-099", "web", "own", -58, -56, "done", LATEST.model_dump_json(), 0.24, DIFF_88),
        # Its runtime reported no cost, so it leaves the mock's spend, and what the spend pages show, as they were.
        (5, PR_14, SHA_14, None, "api", "request", -32, -30, "done", _CAROL.model_dump_json(), None, DIFF_14),
    )
    for run_id, pr, sha, ticket, repo, purpose, started, ended, status, result, cost, diff in rows:
        log_path = reviews / f"{run_id}.log"
        sql.execute(
            conn,
            sql.insert(
                "review_runs",
                id=run_id,
                tick_id=1,
                pr_url=pr,
                sha=sha,
                ticket_key=ticket,
                repo=repo,
                purpose=purpose,
                started_at=at(started),
                ended_at=at(ended),
                status=status,
                result_json=result,
                log_path=str(log_path),
                base_branch="main",
                session_id=f"ses_review{run_id}",
                cost_usd=cost,
            ),
        )
        if diff is not None:
            logs.write_private(review_diff.path_for(log_path), diff)
    sql.execute_many(
        conn,
        sql.insert_rows("seen", ["kind", "subject", "at", "channel"]),
        [
            ("review", "1", at(-96), "web"),
            ("review", "3", at(-68), "web"),
            ("review", "4", at(-50), "web"),
            ("review", "5", at(-28), "web"),
        ],
    )
    # The request review 2 answered, which ended with it (DESIGN §21).
    sql.execute(
        conn,
        sql.insert(
            "review_requests",
            pr_url=PR_12,
            created_at=at(-85),
            channel="cli",
            ended_at=at(-79),
            end_reason="reviewed",
        ),
    )
    # Carol's PR, which the operator asked canopy to review, and its review answered.
    sql.execute(
        conn,
        sql.insert(
            "review_requests",
            pr_url=PR_14,
            created_at=at(-34),
            channel="web",
            ended_at=at(-30),
            end_reason="reviewed",
        ),
    )
    # A coworker's PR the operator asked canopy to review from the web UI (DESIGN §21).
    sql.execute(
        conn,
        sql.insert(
            "review_requests",
            pr_url=PR_95,
            created_at=at(-20),
            channel="web",
            notes="The author asked for a close look at the retry loop; I'm not sure it backs off.",
        ),
    )
    # The reader's read of it, since an open request watches its PR (DESIGN §21): whose it is, before its review.
    sql.execute(
        conn,
        sql.insert(
            "observed_prs",
            url=PR_95,
            repository="acme/web",
            number=95,
            base_ref="main",
            state="open",
            draft=0,
            author="dana",
            observed_at=at(-15),
        ),
    )


def drafts(conn: sqlite3.Connection, at: Callable[[int], str]) -> None:
    """Make the drafts of the reviews of PRs the loop does not own, as `_review` does once one ends, at its end.

    The clean review's the operator has published since, so the lists show a draft that waits and one that posted.
    """
    for run_id in DRAFTED:
        review_drafts.make(conn, run_id)
    with db.transaction(conn):
        sql.execute(
            conn,
            sql.update("review_drafts")
            .set(
                status=ReviewDraftStatus.PUBLISHED,
                publish_version=1,
                publish_started_at=at(-75),
                publish_channel="web",
                published_at=at(-75),
                published_review_id=2_480_000_001,
                published_url=f"{PR_12}#pullrequestreview-2480000001",
                published_comments="[]",
            )
            .where("review_run_id = ?", 2),
        )
        sql.execute(
            conn,
            sql.update("review_drafts")
            .set_to("created_at = (SELECT ended_at FROM review_runs WHERE id = review_drafts.review_run_id)")
            .everything(),
        )
        sql.execute(
            conn,
            sql.update("review_draft_versions")
            .set_to("created_at = (SELECT created_at FROM review_drafts WHERE id = review_draft_versions.draft_id)")
            .everything(),
        )
