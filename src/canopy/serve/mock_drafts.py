"""The mock journal's review replies (DESIGN §29), for `python -m canopy.serve --mock`.

Run 45 resumed ABC-099 on PR 88 to answer alice's and bob's review under `approve`: it fixed the spinner, kept the
debounce, and drafted a reply to each thread and the review's body, which wait on the operator on the PR's page. The
operator has already edited the reply to bob. A third thread, resolved and outdated, no draft answers.

The mock serves a stand-in for canopy's two GitHub programs (`GitHub`), answering from its own journal, so a draft sent
from it posts nowhere: the PRs it names are fixtures' URLs, and some may be real.
"""

from __future__ import annotations

import json
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, override

from canopy.core import db, review_diff, sql
from canopy.infra import procs
from canopy.serve.mock_reviews import PR_88

if TYPE_CHECKING:
    import sqlite3

RUN = 45
# The head run 45 pushed, and its diff from the base branch: the spinner clears in a `finally` now.
SHA = "e3a7d915" + "9" * 32
DIFF = """\
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
index 0000000..d41c9a7
--- /dev/null
+++ b/src/search/useSearch.ts
@@ -0,0 +1,23 @@
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
+            .then((found: Result[]) => setResults(found))
+            .finally(() => {
+                if (!controller.signal.aborted) {
+                    setLoading(false)
+                }
+            })
+        return () => controller.abort()
+    }, [query])
+
+    return { results, loading }
+}
"""
_STARTED, _ENDED = -40, -22
_REVIEW = 4_102_337_001
_THREADS = (
    # thread, comment, author, path, line (None: outdated), resolved, minutes, body
    (
        "PRRT_kwDOA1",
        2_468_013_579,
        "alice",
        "src/search/useSearch.ts",
        16,
        False,
        -48,
        "If the fetch rejects, `loading` never goes back to false. Can it move into a `finally`?",
    ),
    (
        "PRRT_kwDOA2",
        2_468_013_601,
        "bob",
        "src/search/SearchBox.tsx",
        6,
        False,
        -47,
        (
            "Why 250? Our other inputs debounce at 300.\n\n<details>\n<summary>Where they do</summary>\n\n"
            "- `src/filters/FilterInput.tsx`\n- `src/nav/JumpTo.tsx`\n</details>"
        ),
    ),
    ("PRRT_kwDOA3", 2_468_013_644, "alice", "src/search/useSearch.ts", None, True, -46, "nit: `Result` is type-only."),
)
_DRAFTS = (
    # number, kind, comment, stance, the run's text, the operator's edit, the run's reaction
    (
        1,
        "thread",
        2_468_013_579,
        "changed",
        (
            "Moved `setLoading(false)` into a `finally`, skipped for an aborted request so a newer query's spinner "
            "stays on."
        ),
        None,
        None,
    ),
    (
        2,
        "thread",
        2_468_013_601,
        "declined",
        "250 ms is what the ticket asks for. 300 felt sluggish for type-ahead.",
        (
            "ABC-099 asks for 250 ms: at 300 the type-ahead felt sluggish. Happy to make it a shared constant in a "
            "follow-up so the two stop drifting."
        ),
        None,
    ),
    (
        3,
        "pr",
        None,
        None,
        (
            "Thanks both. The spinner fix is in the latest push; the debounce stays at 250 ms for now, reasons on "
            "the thread."
        ),
        None,
        None,
    ),
    # A nit the run fixed, answered with a reaction alone.
    (4, "thread", 2_468_013_644, "changed", "", None, "+1"),
)


def seed(conn: sqlite3.Connection, state_dir: Path, at: Callable[[int], str], slot: str) -> None:
    """Insert run 45, in web's `slot`, the reader's last read of PR 88, and the run's drafts, and keep its diff."""
    log_path = state_dir / "runs" / f"{RUN}.log"
    log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    result = {
        "summary": "Answered the review: a failed search clears the spinner now, and the debounce stays at 250 ms.",
        "prs": {"web": PR_88},
    }
    sql.execute(
        conn,
        sql.insert(
            "runs",
            id=RUN,
            tick_id=1,
            ticket_key="ABC-099",
            kind="resume",
            branch="agent/ABC-099-search",
            started_at=at(_STARTED),
            ended_at=at(_ENDED),
            status="done",
            result_json=json.dumps(result),
            log_path=str(log_path),
            private=0,
            session_id=f"ses_mock{RUN}",
            cost_usd=0.74,
            tokens_input=29600,
            tokens_output=4440,
            tokens_cache_read=296000,
            tokens_peak_context=44400,
        ),
    )
    sql.execute(
        conn,
        sql.insert(
            "run_slots",
            run_id=RUN,
            repo="web",
            slot_path=slot,
            lease_id="lease-45",
            lease_holder="canopy:ABC-099",
            base_branch="main",
        ),
    )
    sql.execute(conn, sql.insert("run_reasons", run_id=RUN, reason="review"))
    sql.execute(conn, sql.insert("run_replies", run_id=RUN, mode="approve", ticket_drafts=0))
    kept = review_diff.run_path_for(log_path, "web")
    review_diff.keep(kept, DIFF)
    review_diff.keep_head(kept, SHA)
    _read(conn, at)
    for number, kind, comment, stance, text, edit, reaction in _DRAFTS:
        thread = next((t[0] for t in _THREADS if t[1] == comment), None)
        found = sql.execute(
            conn,
            sql.insert(
                "drafts",
                run_id=RUN,
                number=number,
                ticket_key="ABC-099",
                kind=kind,
                repo="web",
                pr_url=PR_88,
                comment_id=comment,
                stance=stance,
                thread_id=thread,
                status="waiting",
                basis=at(_STARTED),
                created_at=at(_ENDED),
                checked_at=at(-18),
            ).returning("id"),
        ).fetchone()
        versions: list[tuple[int, str, str, str | None, str, str | None]] = [
            (1, text, "worker", None, at(_ENDED), reaction)
        ]
        if edit is not None:
            versions.append((2, edit, "operator", "web", at(-10), reaction))
        sql.execute_many(
            conn,
            sql.insert_rows(
                "draft_versions", ("draft_id", "version", "body", "author", "channel", "created_at", "reaction")
            ),
            [(found["id"], *v) for v in versions],
        )


@dataclass
class GitHub(procs.SubprocessRunner):
    """canopy's GitHub programs as the mock serves them, which post nothing.

    The reader prints what the journal holds of each PR, and the poster reports each reply posted, with ids and URLs
    made from what it was asked. Any other program runs.
    """

    journal: Path

    @override
    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        timeout: float | None = None,
        on_start: Callable[[int], None] | None = None,
        on_line: Callable[[str], None] | None = None,
    ) -> procs.Result:
        """Answer for `canopy-connect-github` and `canopy-post-github`; run anything else. See `procs.Runner.run`.

        Returns:
            What the program printed.
        """
        name = Path(args[0]).name if args else ""
        if name == "canopy-connect-github":
            return procs.Result(tuple(args), 0, self._read(json.loads(stdin or "{}")), "")
        if name == "canopy-post-github":
            printed = _post(stdin or "{}")
            self._hold_staged(json.loads(stdin or "{}"), printed)
            return procs.Result(tuple(args), 0, printed, "")
        return super().run(args, cwd=cwd, env=env, stdin=stdin, timeout=timeout, on_start=on_start, on_line=on_line)

    def _hold_staged(self, request: Mapping[str, object], printed: str) -> None:
        """Keep a staged review where the reader reads it, pending under the operator's login, as GitHub would."""
        pr = request.get("pr")
        if request.get("submit") is not False or not isinstance(pr, str):
            return
        lines = [json.loads(line) for line in printed.splitlines()]
        pending = next((line for line in lines if line["kind"] == "pending"), None)
        if pending is None:
            return
        conn = db.connect(self.journal)
        try:
            with db.transaction(conn):
                sql.execute(
                    conn,
                    sql.insert(
                        "observed_reviews",
                        pr_url=pr,
                        item="review",
                        id=pending["id"],
                        author="op",
                        bot=0,
                        state="pending",
                        created_at=None,
                        body=str(request.get("body") or ""),
                        url=None,
                        observed_at=db.now(),
                    ),
                )
                for line in (line for line in lines if line["kind"] == "comment"):
                    answered = (
                        sql.select(
                            "pr_url, 'comment', ?, 'op', 0, ?, ?, ?, ?, thread_id, path, line, side, outdated, "
                            "resolved, ?",
                            line["id"],
                            db.now(),
                            _text_for(request, line["comment"]),
                            line["url"],
                            pending["id"],
                            db.now(),
                        )
                        .from_("observed_reviews")
                        .where("pr_url = ?", pr)
                        .where("item = 'comment'")
                        .where("id = ?", line["comment"])
                    )
                    columns = (
                        "pr_url",
                        "item",
                        "id",
                        "author",
                        "bot",
                        "created_at",
                        "body",
                        "url",
                        "review_id",
                        "thread_id",
                        "path",
                        "line",
                        "side",
                        "outdated",
                        "resolved",
                        "observed_at",
                    )
                    sql.execute(conn, sql.insert_from("observed_reviews", columns, answered))
        finally:
            conn.close()

    def _read(self, request: Mapping[str, list[str]]) -> str:
        conn = db.connect(self.journal)
        try:
            prs = sql.execute(
                conn,
                sql.select("*")
                .from_("observed_prs")
                .where("url IN (SELECT value FROM json_each(?))", json.dumps(request.get("prs", []))),
            ).fetchall()
            lines: list[dict[str, object]] = []
            for pr in prs:
                lines.append(
                    {
                        "kind": "pr",
                        "url": pr["url"],
                        "repository": pr["repository"],
                        "number": pr["number"],
                        "head_sha": pr["head_sha"],
                        "base_ref": pr["base_ref"],
                        "state": pr["state"],
                        "draft": bool(pr["draft"]),
                        "mergeable": pr["mergeable"],
                        "author": pr["author"],
                    }
                )
                reviews = sql.select("*").from_("observed_reviews").where("pr_url = ?", pr["url"]).order_by("id")
                for r in sql.execute(conn, reviews):
                    thread = None
                    if r["thread_id"] is not None:
                        thread = {
                            "id": r["thread_id"],
                            "path": r["path"],
                            "line": r["line"],
                            "side": r["side"],
                            "outdated": bool(r["outdated"]),
                            "resolved": bool(r["resolved"]),
                        }
                    lines.append(
                        {
                            "kind": "review",
                            "item": r["item"],
                            "pr": r["pr_url"],
                            "id": r["id"],
                            "author": r["author"],
                            "bot": bool(r["bot"]),
                            "state": r["state"],
                            "time": r["created_at"],
                            "body": r["body"],
                            "url": r["url"],
                            "review": r["review_id"],
                            "thread": thread,
                        }
                    )
            lines.append({"kind": "end", "prs": [pr["url"] for pr in prs]})
        finally:
            conn.close()
        return "".join(json.dumps(line) + "\n" for line in lines)


def _text_for(request: Mapping[str, object], comment: object) -> str:
    """The text of the reply `request` makes to `comment`.

    Returns:
        The text, or empty when it makes none.
    """
    raw = request.get("replies")
    replies: list[object] = raw if isinstance(raw, list) else []
    return next((str(r.get("text")) for r in replies if isinstance(r, dict) and r.get("comment") == comment), "")


def _post(stdin: str) -> str:
    """What `canopy-post-github` would print for one PR's drafts or one ticket's.

    Returns:
        Its lines, every id drawn from what it was asked.
    """
    request: dict[str, object] = json.loads(stdin)
    made = zlib.crc32(stdin.encode()) % 1_000_000
    lines: list[dict[str, object]] = [{"kind": "as", "login": "op"}]
    pr = request.get("pr")
    if isinstance(pr, str):
        raw = request.get("replies")
        replies: list[dict[str, object]] = [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []
        # Reactions first, as the real poster adds them, and a PR's drafts that are all reactions open no review.
        lines.extend(
            {
                "kind": "reaction",
                "comment": r.get("comment"),
                "reaction": r["reaction"],
                "url": f"{pr}#discussion_r{r.get('comment')}",
            }
            for r in replies
            if "reaction" in r
        )
        texts = [r for r in replies if "text" in r]
        if texts or request.get("body") is not None:
            review = 4_102_000_000 + made
            lines.append({"kind": "pending", "review": f"PRR_mock{review}", "id": review})
            for reply in texts:
                answered = reply.get("comment")
                posted = 2_469_000_000 + (answered if isinstance(answered, int) else 0) % 1_000_000
                url = f"{pr}#discussion_r{posted}"
                lines.append({"kind": "comment", "comment": answered, "id": posted, "url": url})
            if request.get("submit") is False:
                lines.append({"kind": "end", "submitted": False, "staged": True})
                return "".join(json.dumps(line) + "\n" for line in lines)
            lines.append({"kind": "review", "id": review, "url": f"{pr}#pullrequestreview-{review}"})
    else:
        posted = 2_470_000_000 + made
        lines.append({"kind": "comment", "id": posted, "url": f"{request.get('issue')}#issuecomment-{posted}"})
    lines.append({"kind": "end", "submitted": True})
    return "".join(json.dumps(line) + "\n" for line in lines)


def _read(conn: sqlite3.Connection, at: Callable[[int], str]) -> None:
    """The reader's last whole read of PR 88, at the head run 45 pushed, after the run ended."""
    read_at = at(-18)
    sql.execute(
        conn,
        sql.insert(
            "observed_prs",
            url=PR_88,
            repository="acme/web",
            number=88,
            head_sha=SHA,
            base_ref="main",
            state="open",
            draft=0,
            mergeable="mergeable",
            author="op",
            observed_at=read_at,
        ),
    )
    sql.execute(
        conn,
        sql.insert(
            "observed_reviews",
            pr_url=PR_88,
            item="review",
            id=_REVIEW,
            author="alice",
            bot=0,
            state="changes_requested",
            created_at=at(-48),
            body="A couple of things before this goes in.",
            url=f"{PR_88}#pullrequestreview-{_REVIEW}",
            observed_at=read_at,
        ),
    )
    for thread, comment, author, path, line, resolved, minutes, body in _THREADS:
        sql.execute(
            conn,
            sql.insert(
                "observed_reviews",
                pr_url=PR_88,
                item="comment",
                id=comment,
                author=author,
                bot=0,
                created_at=at(minutes),
                body=body,
                url=f"{PR_88}#discussion_r{comment}",
                review_id=_REVIEW,
                thread_id=thread,
                path=path,
                line=line,
                side="right",
                outdated=int(line is None),
                resolved=int(resolved),
                observed_at=read_at,
            ),
        )
