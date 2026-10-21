"""The mock journal's chore runs (DESIGN §19), for `python -m canopy.serve --mock`.

`deps`'s latest run found the advisory the attention list shows, and the operator left a note on it; `build-health` is
running.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from canopy.core import sql, workspace

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from pathlib import Path

#: The advisory `deps`'s chore run 2 found, which the attention list shows.
LODASH = {
    "id": "lodash-advisory",
    "title": "lodash 4.17.20 has a prototype pollution advisory",
    "detail": "web's lockfile pins lodash 4.17.20 through an old date picker; 4.17.21 fixes it.",
    "link": "https://github.com/advisories/GHSA-35jh-r3h4-6jhm",
}


def seed(conn: sqlite3.Connection, root: Path, at: Callable[[int], str], chore: str) -> None:
    """Insert `chore`'s two runs and `build-health`'s two, the second running, and the operator's note on `chore`."""
    chore_runs = (
        # id, chore, started, ended, status, result, cost
        (1, chore, -480, -474, "ok", {"status": "ok", "summary": "No advisory touches the lockfiles."}, 0.21),
        (
            2,
            chore,
            -240,
            -233,
            "ok",
            {"status": "ok", "summary": "One advisory touches web's lockfile.", "findings": [LODASH]},
            0.26,
        ),
        (
            3,
            "build-health",
            -130,
            -124,
            "ok",
            {"status": "ok", "summary": "main is green; two flaky checks passed on a retry."},
            0.33,
        ),
        (4, "build-health", -10, None, "running", None, 0.05),
    )
    for run_id, name, started, ended, status, result, cost in chore_runs:
        sql.execute(
            conn,
            sql.insert(
                "chore_runs",
                id=run_id,
                tick_id=1,
                chore=name,
                started_at=at(started),
                ended_at=at(ended) if ended is not None else None,
                status=status,
                result_json=json.dumps(result) if result is not None else None,
                log_path=str(root.absolute() / workspace.WORKSPACE_STATE_DIR / "chore-runs" / name / f"{run_id}.log"),
                session_id=f"ses_chore{run_id}",
                cost_usd=cost,
                tokens_input=int(cost * 40_000),
                tokens_output=int(cost * 6_000),
                tokens_cache_read=int(cost * 400_000),
                tokens_peak_context=int(cost * 60_000),
            ),
        )
    sql.execute(
        conn,
        sql.insert(
            "messages",
            id=8,
            subject_kind="chore",
            subject_id=chore,
            at=at(-300),
            source="operator",
            kind="reply",
            channel="cli",
            body="Leave out the docs site's lockfile: it is never deployed.",
            submission="mock-note-8",
        ),
    )
