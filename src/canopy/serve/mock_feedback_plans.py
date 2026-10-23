"""The mock journal's feedback plan (DESIGN §32), for `python -m canopy.serve --mock`.

After run 45's push, run 46 planned the next round of PR 88's feedback: alice's review and her thread to leave, since
run 45's drafts answer them, and bob's to change, the debounce made a shared constant, with the reply it would draft.
The plan waits on the operator, and is stale: carol reviewed the PR after it was written. What it saw is recorded
with it as the planner's own run records it, so the harness computes that in code, as it would for a real plan.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from canopy.core import feedback_items, plans, sql
from canopy.core.vocab import PlanItem, PlanStatus, Proposal, RunKind, RunStatus
from canopy.serve.mock_reviews import PR_88

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from pathlib import Path

    from canopy.core.config import Trust

RUN = 46
_KEY = "ABC-099"
_STARTED, _ENDED = -16, -12
_REVIEW = 4_102_337_001
_ALICE = 2_468_013_579
_BOB = 2_468_013_601
# carol's review, after the plan was written: what makes it stale.
_CAROL = 4_102_337_050
_TEXT = """# Feedback plan: ABC-099

The round after run 45's push to acme/web#88: alice's review and its two threads. Run 45 already drafted a reply to
each; they wait on you, and this plan changes none of them but bob's.

## Items

### Item 4102337001: leave

alice's review asks for changes; its threads are the work, below. Nothing to do for the review itself.

### Item 2468013579: leave

Run 45 moved `setLoading(false)` into a `finally`, skipped for an aborted request. Its draft says so.

### Item 2468013601: change

bob asks why 250 ms when the other inputs debounce at 300. Keep 250, which the ticket asks for, and move it into
`SEARCH_DEBOUNCE_MS` in `src/search/constants.ts`, so the inputs stop drifting apart.

## Checks

No check has run at the head yet.
"""
_ITEMS = (
    # item, id, proposal, reply
    (PlanItem.REVIEW, _REVIEW, Proposal.LEAVE, None),
    (PlanItem.COMMENT, _ALICE, Proposal.LEAVE, None),
    (
        PlanItem.COMMENT,
        _BOB,
        Proposal.CHANGE,
        "Kept 250 ms, which ABC-099 asks for, and moved it into `SEARCH_DEBOUNCE_MS` so the inputs stop drifting.",
    ),
)


def seed(conn: sqlite3.Connection, state_dir: Path, at: Callable[[int], str], trust: Trust, slot: str) -> None:
    """Insert run 46, in web's `slot`, its plan, waiting, its file and what it saw of PR 88, then bob's reply."""
    log_path = state_dir / "runs" / f"{RUN}.log"
    result = {"status": "done", "summary": "Planned PR 88's next round: leave alice's two items, change bob's."}
    sql.execute(
        conn,
        sql.insert(
            "runs",
            id=RUN,
            tick_id=1,
            ticket_key=_KEY,
            kind=RunKind.FEEDBACK_PLAN,
            branch="agent/ABC-099-search",
            started_at=at(_STARTED),
            ended_at=at(_ENDED),
            status=RunStatus.DONE,
            result_json=json.dumps(result),
            log_path=str(log_path),
            private=0,
        ),
    )
    sql.execute(
        conn,
        sql.insert(
            "run_slots",
            run_id=RUN,
            repo="web",
            slot_path=slot,
            lease_id="lease-46",
            lease_holder="canopy:ABC-099",
            base_branch="main",
        ),
    )
    written = plans.write(state_dir, _KEY, RUN, _TEXT)
    [plan_id] = sql.execute(
        conn,
        sql.insert(
            "feedback_plans",
            ticket_key=_KEY,
            run_id=RUN,
            created_at=at(_ENDED),
            status=PlanStatus.PROPOSED,
            sha256=written.sha256,
            size=written.size,
        ).returning("id"),
    ).fetchone()
    sql.execute_many(
        conn,
        sql.insert_rows(
            "feedback_plan_items",
            ("plan_id", "number", "pr_url", "item", "item_id", "proposal", "reply"),
        ),
        [(plan_id, n, PR_88, *item) for n, item in enumerate(_ITEMS, start=1)],
    )
    given = feedback_items.offered(conn, trust, _KEY, [PR_88])
    feedback_items.record(conn, plan_id, feedback_items.take(conn, [PR_88], given))
    _review(conn, at)


def _review(conn: sqlite3.Connection, at: Callable[[int], str]) -> None:
    """The review carol left, as the reader's next whole read of PR 88 holds it, with all else it read again."""
    read_at = at(-5)
    sql.execute(conn, sql.update("observed_prs").set(observed_at=read_at).where("url = ?", PR_88))
    sql.execute(conn, sql.update("observed_reviews").set(observed_at=read_at).where("pr_url = ?", PR_88))
    sql.execute(
        conn,
        sql.insert(
            "observed_reviews",
            pr_url=PR_88,
            item="review",
            id=_CAROL,
            author="carol",
            bot=0,
            state="commented",
            created_at=at(-6),
            body="Fine by me once the debounce is a shared constant; the filters could use it too.",
            url=f"{PR_88}#pullrequestreview-{_CAROL}",
            observed_at=read_at,
        ),
    )
