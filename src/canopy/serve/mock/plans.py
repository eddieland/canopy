"""The mock journal's planned ticket (DESIGN §25), for `python -m canopy.serve --mock`.

ABC-105 is planned: its plan waits on the operator, with three comments on it, one resolved, an open decision for the
page to offer, and an earlier plan it superseded, each written to its file under the state directory. The earlier one
was superseded after the operator asked for changes; each comment's passage is in the one waiting.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from canopy.core import plans, records

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from pathlib import Path

_FIRST_PLAN = """# Schedule report exports

## What changes

In **web**, a report gains a *Schedule* menu: daily or weekly, at an hour. A new job, `ExportJob`, runs each schedule
and emails the CSV.

## Tests

- [ ] a daily schedule runs once a day
"""
_PLAN = """# Schedule report exports

## What changes

In **web**, a report gains a *Schedule* menu: daily or weekly, at an hour the operator picks. A new job,
`ExportJob`, runs each schedule through the existing CSV export and emails a link to the file, never the file itself.

In **api**, `ReportQuery` gains `owner_timezone()`, so an hour means the owner's hour.

## Files

| Repository | File | Why |
| --- | --- | --- |
| web | `app/reports/schedule.py` | the menu and its form |
| web | `app/jobs/export_job.py` | the job |
| api | `api/reports/query.py` | `owner_timezone()` |

## Decisions

### Decision 1: Where a schedule keeps its hour

- **A (chosen):** As the owner's local hour: the ticket asks for the owner's hour, so it holds when the clocks change.
- **B:** As an hour in UTC: simpler to store, but the export moves an hour twice a year.

## Tests

- [ ] a daily schedule runs once a day, at the owner's hour
- [ ] a weekly schedule skips the other six days
- [ ] the email links to the file and does not attach it

## Out of scope

- Exports to anything but CSV.

## Risks

> The job runner retries a failed job three times. A report that always fails would email nothing, and say nothing.
"""
_PLAN_THREADS = (
    # quote, prefix, suffix, body, minutes, resolved, replies
    (
        "emails a link to the file, never the file itself",
        "the existing CSV export and",
        ".",
        "How long does the link work? Say so in the plan.",
        -10,
        False,
        ("Seven days, as the share links do.",),
    ),
    (
        "A report that always fails would email nothing, and say nothing.",
        "retries a failed job three times.",
        "",
        "Raise it on the attention list after the third failure.",
        -9,
        False,
        (),
    ),
    (
        "at an hour the operator picks",
        "a report gains a Schedule menu: daily or weekly,",
        ". A new job,",
        "Good: the ticket asks for the owner's hour.",
        -11,
        True,
        (),
    ),
)


def seed(conn: sqlite3.Connection, state_dir: Path, at: Callable[[int], str], root: Path) -> None:
    """Insert ABC-105, its two plan runs, their plans, and the comments on the second, and write each plan's file."""
    records.insert(
        records.Ticket,
        key="ABC-105",
        repo=str(root),
        first_seen_at=at(-90),
        last_seen_at=at(-8),
        changed_at=at(-8),
        title="Schedule report exports",
        phase="plan_proposed",
    ).run(conn)
    for run_id, started, ended, summary in (
        (35, -60, -52, "A schedule menu and a job that emails the CSV."),
        (44, -30, -14, "A schedule menu, a job that emails a link to the CSV, and the owner's timezone."),
    ):
        records.insert(
            records.Run,
            id=run_id,
            tick_id=1,
            ticket_key="ABC-105",
            kind="plan",
            branch="",
            started_at=at(started),
            ended_at=at(ended),
            status="done",
            result_json=json.dumps({"status": "done", "summary": summary}),
            log_path=str(state_dir / "runs" / f"{run_id}.log"),
            private=0,
            cost_usd=0.64,
        ).run(conn)
    for plan_id, run_id, text, status, created in (
        (1, 35, _FIRST_PLAN, "superseded", -52),
        (2, 44, _PLAN, "proposed", -14),
    ):
        written = plans.write(state_dir, "ABC-105", run_id, text)
        records.insert(
            records.Plan,
            id=plan_id,
            ticket_key="ABC-105",
            run_id=run_id,
            created_at=at(created),
            status=status,
            sha256=written.sha256,
            size=written.size,
        ).run(conn)
    for quote, prefix, suffix, body, minutes, resolved, replies in _PLAN_THREADS:
        thread = records.insert(
            records.PlanThread,
            ticket_key="ABC-105",
            quote=quote,
            prefix=prefix,
            suffix=suffix,
            body=body,
            created_at=at(minutes),
            resolved_at=at(minutes + 1) if resolved else None,
        ).returning("id")
        thread_id = thread.run(conn).fetchone()[0]
        for reply in replies:
            records.insert(records.PlanReply, thread_id=thread_id, body=reply, created_at=at(minutes + 2)).run(conn)
