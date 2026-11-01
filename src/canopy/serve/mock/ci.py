"""The mock journal's check runs (DESIGN §35), for the CI page of `python -m canopy.serve --mock`.

The week's PRs as the `vcs` source observed their checks complete. `api` PR 12 went red on `unit` and then on `build`,
each fixed by the next head; Carol's PR 14 timed out on `unit`, and its head now fails `integration` and `typecheck`.
In `web`, PR 88's first head failed `e2e` and its next passed, as did the head run 45 pushed to answer its review, which
the Reviews page times as canopy's turnaround, PR 91 went green first time, and PR 86, ABC-100's, fails
`e2e` on its one head, rerun once (cancelled) and again (red), which run 40, a `fix-ci`, failed to fix. Nothing kicks a
flaky check: the mock leaves `trust.max_flaky_kicks` at 0. A skipped and a cancelled run count as neither.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import records
from canopy.core.vocab import CheckConclusion
from canopy.serve.mock import drafts
from canopy.serve.mock.reviews import PR_12, PR_14, PR_88, PR_91, SHA_12, SHA_14, SHA_88, SHA_88_FIRST, SHA_91

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

#: ABC-100's PR, which its run 37 opened.
PR_86 = "https://github.com/acme/web/pull/86"
# The heads only these check runs name.
_SHA_86 = "3f6b2e19" + "6" * 32
_SHA_12_A = "71c0a9d4" + "2" * 32
_SHA_12_B = "b2e98f13" + "2" * 32
_SHA_12_C = "e5d4c37a" + "2" * 32
_SHA_14_A = "4a90d1be" + "8" * 32
# The check runs' ids on their host, from here up.
_RUN_IDS = 9_200_000
_S, _F, _T, _C, _K = (
    CheckConclusion.SUCCESS,
    CheckConclusion.FAILURE,
    CheckConclusion.TIMED_OUT,
    CheckConclusion.CANCELLED,
    CheckConclusion.SKIPPED,
)
#: Each check run: its PR, head, name, conclusion, and when it was observed, in minutes after T0, the oldest first.
_RUNS: tuple[tuple[str, str, str, CheckConclusion, int], ...] = (
    (PR_12, _SHA_12_A, "lint", _S, -7330),
    (PR_12, _SHA_12_A, "unit", _F, -7325),
    (PR_12, _SHA_12_A, "build", _S, -7322),
    (PR_12, _SHA_12_A, "deploy-preview", _K, -7320),
    (PR_12, _SHA_12_B, "lint", _S, -5880),
    (PR_12, _SHA_12_B, "unit", _S, -5875),
    (PR_12, _SHA_12_B, "build", _S, -5872),
    (PR_12, _SHA_12_C, "lint", _S, -2950),
    (PR_12, _SHA_12_C, "unit", _S, -2945),
    (PR_12, _SHA_12_C, "build", _F, -2940),
    (PR_14, _SHA_14_A, "lint", _S, -1500),
    (PR_14, _SHA_14_A, "unit", _T, -1490),
    (PR_14, _SHA_14_A, "build", _S, -1488),
    (PR_14, _SHA_14_A, "integration", _S, -1480),
    (PR_12, SHA_12, "lint", _S, -98),
    (PR_12, SHA_12, "unit", _S, -96),
    (PR_12, SHA_12, "build", _S, -95),
    (PR_88, SHA_88_FIRST, "lint", _S, -106),
    (PR_88, SHA_88_FIRST, "unit", _S, -105),
    (PR_88, SHA_88_FIRST, "e2e", _F, -104),
    (PR_86, _SHA_86, "lint", _S, -166),
    (PR_86, _SHA_86, "unit", _S, -164),
    (PR_86, _SHA_86, "e2e", _F, -162),
    (PR_86, _SHA_86, "e2e", _C, -150),
    (PR_86, _SHA_86, "e2e", _F, -140),
    (PR_91, SHA_91, "lint", _S, -122),
    (PR_91, SHA_91, "unit", _S, -121),
    (PR_91, SHA_91, "typecheck", _S, -120),
    (PR_91, SHA_91, "e2e", _S, -118),
    (PR_88, SHA_88, "lint", _S, -59),
    (PR_88, SHA_88, "unit", _S, -58),
    (PR_88, SHA_88, "e2e", _S, -57),
    (PR_14, SHA_14, "lint", _S, -46),
    (PR_14, SHA_14, "unit", _S, -45),
    (PR_14, SHA_14, "build", _S, -44),
    (PR_14, SHA_14, "typecheck", _F, -43),
    (PR_14, SHA_14, "integration", _F, -41),
    # Run 45's push, after run 46 planned again: its plan says no check had run at the head yet.
    (PR_88, drafts.SHA, "lint", _S, -9),
    (PR_88, drafts.SHA, "unit", _S, -8),
    (PR_88, drafts.SHA, "e2e", _S, -7),
)


def seed(conn: sqlite3.Connection, at: Callable[[int], str]) -> None:
    """Insert the check runs, each observed completed at its time, `at` turning minutes after T0 into a journal time."""
    rows = [
        (pr, _RUN_IDS + i, name, sha, conclusion, at(minutes))
        for i, (pr, sha, name, conclusion, minutes) in enumerate(_RUNS, start=1)
    ]
    records.insert_rows(
        records.ObservedCheckRun,
        ("pr_url", "run_id", "name", "head_sha", "conclusion", "observed_at"),
    ).many(conn, rows)
