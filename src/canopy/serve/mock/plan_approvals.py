"""The plans before September's landed tickets (DESIGN §25), for the Plans report: how each was approved.

The workspace planned every ticket from September on. ABC-076's plan was written before canopy kept the level a plan
run was offered; the operator approved it as written. ABC-079's they edited first. Then they set
`policy.planner_may_approve` to `strict` for a while: the planner approved ABC-082's plan and ABC-088's itself, and
said ABC-085's needed review, which the operator approved as written; ABC-091's first plan drew a comment and was sent
back, and its second was approved four hours after it was written. ABC-105's two plans, the fixtures' own, were
written at `strict` too, after which the operator turned the key off again. ABC-082's and ABC-091's PRs each needed a
`resume`, and ABC-076's a `fix-ci` from before resumes took it over.

The plan runs report no cost, so the months' spend and each landed ticket's cost are what they were without them, and
each started before October, so the spend page's week holds none.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from canopy.core import db, plans, records, workspace
from canopy.core.vocab import PlanEffort, PlannerApproval, PlanStatus, RunKind, RunStatus
from canopy.serve.mock import history

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path


@dataclass(frozen=True)
class _Planned:
    """A plan before a landed ticket's first implement."""

    key: str
    #: The level its run was offered; None for one from before canopy kept it.
    level: PlannerApproval | None
    #: How it was approved: `web`, `cli`, or the planner's; None for one sent back.
    channel: str | None
    #: When it was written and approved, in hours before its ticket's first implement started.
    written: float
    approved: float
    #: Roughly how long its file is, in bytes.
    size: int
    effort: PlanEffort
    edited: bool = False
    #: When the operator commented on it, in hours before its ticket's first implement started.
    comment: float | None = None


_PLANNED = (
    _Planned("ABC-076", None, "web", written=3, approved=2.5, size=3_200, effort=PlanEffort.SMALL),
    _Planned("ABC-079", PlannerApproval.OFF, "cli", 5, 2.5, 9_400, PlanEffort.MEDIUM, edited=True),
    _Planned("ABC-082", PlannerApproval.STRICT, plans.PLANNER, 1, 1, 2_100, PlanEffort.SMALL),
    _Planned("ABC-085", PlannerApproval.STRICT, "web", 2, 0.8, 6_300, PlanEffort.MEDIUM),
    _Planned("ABC-088", PlannerApproval.STRICT, plans.PLANNER, 1, 1, 1_500, PlanEffort.SMALL),
    _Planned("ABC-091", PlannerApproval.STRICT, None, 9, 9, 11_800, PlanEffort.LARGE, comment=7),
    _Planned("ABC-091", PlannerApproval.STRICT, "web", 6, 2, 14_600, PlanEffort.LARGE),
)
# A comment's passage, which each plan's text holds.
_QUOTE = "the existing patterns"


def seed(conn: sqlite3.Connection, state_dir: Path, root: Path) -> None:
    """Insert each plan's run and row, approved as `_PLANNED` says, write its file, and set the implement's plan.

    ABC-105's plan runs, the fixtures', are given the level they were offered.
    """
    started = {t.key: t.started for t in history.TICKETS}
    for planned in _PLANNED:
        first = started[planned.key]
        written = db.format_time(first - timedelta(hours=planned.written))
        run = records.insert(
            records.Run,
            tick_id=1,
            ticket_key=planned.key,
            kind=RunKind.PLAN,
            branch="",
            started_at=db.format_time(first - timedelta(hours=planned.written, minutes=12)),
            ended_at=written,
            status=RunStatus.DONE,
            result_json=json.dumps({"status": "done", "summary": f"A plan for {planned.key}."}),
            log_path="",
            plan_review=planned.level,
        )
        run_id = db.rowid(run.run(conn))
        log = root.absolute() / workspace.WORKSPACE_STATE_DIR / "runs" / f"{run_id}.log"
        records.update(records.Run).set(log_path=str(log)).where("id = ?", run_id).run(conn)
        file = plans.write(state_dir, planned.key, run_id, _text(planned))
        approved = None if planned.channel is None else db.format_time(first - timedelta(hours=planned.approved))
        records.update(records.Plan).set(status=PlanStatus.SUPERSEDED).where("ticket_key = ?", planned.key).run(conn)
        plan = records.insert(
            records.Plan,
            ticket_key=planned.key,
            run_id=run_id,
            created_at=written,
            status=PlanStatus.SUPERSEDED if approved is None else PlanStatus.APPROVED,
            sha256=file.sha256,
            size=file.size,
            # An edit before approval is a file the operator changed: its hash is no longer the planner's.
            approved_sha256=None if approved is None else ("e" * 64 if planned.edited else file.sha256),
            approved_at=approved,
            approved_channel=planned.channel,
            approved_reason="Two files, the ticket names both, no interface touched."
            if planned.channel == plans.PLANNER
            else None,
            effort=planned.effort,
        )
        plan_id = db.rowid(plan.run(conn))
        if planned.comment is not None:
            records.insert(
                records.PlanThread,
                ticket_key=planned.key,
                quote=_QUOTE,
                prefix="",
                suffix="",
                body="Split the migration into its own step.",
                created_at=db.format_time(first - timedelta(hours=planned.comment)),
                resolved_at=written,
            ).run(conn)
        if approved is not None:
            (
                records.update(records.Run)
                .set(plan_id=plan_id)
                .where(
                    "id = (SELECT min(id) FROM runs WHERE ticket_key = ? AND kind = ?)",
                    planned.key,
                    RunKind.IMPLEMENT,
                )
                .run(conn)
            )
    records.update(records.Run).set(plan_review=PlannerApproval.STRICT).where(
        "ticket_key = ? AND kind = ?",
        "ABC-105",
        RunKind.PLAN,
    ).run(conn)


# A plan of about `planned.size` bytes: a heading, what changes, and steps enough to fill it.
def _text(planned: _Planned) -> str:
    head = f"# {planned.key}\n\n## What changes\n\nFollow {_QUOTE} in the code, file by file.\n\n## Steps\n\n"
    step = "- [ ] Change the next file the ticket names, and its test beside it.\n"
    return head + step * max(1, (planned.size - len(head)) // len(step))
