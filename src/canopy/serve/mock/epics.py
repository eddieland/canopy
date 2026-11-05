"""The mock journal's epics (DESIGN §43), for `python -m canopy.serve --mock`.

Three epics across the workspace's repositories, one in each place an epic's plan stands. Epic 1, over api, web, and
mobile, was planned before its tickets existed: its plan run's plan, approved, breaks it into four entries, of which
B4 is marked trivial. The operator filed tickets for two and registered each after the approval: ABC-103 fulfils B1,
its PR 91 open, and ABC-104 fulfils B2, its resume running; ABC-100, a ticket the breakdown did not foresee, is a member
of no entry. Epic 2, over mobile and web, had a plan the operator replied to, asking for changes; its second plan run
wrote the plan that now waits on them. Epic 3, over api and web, was just submitted, and its first plan run works.

The plan runs report no cost, so the spend page's totals are what they were without them. The running one holds no
slot in the mock's pools, which show no lease for it. Every row and message here takes its id after every other
fixture's: `seed` runs last.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from canopy.core import conversation, epics, plans, records
from canopy.core.vocab import PlanStatus, RunStatus
from canopy.runs import desks, epic_runs

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable, Sequence
    from pathlib import Path

#: The epic whose plan is approved, with members.
APPROVED = 1
#: The epic whose plan waits on the operator, after their reply.
PROPOSED = 2
#: The epic whose first plan run works.
PLANNING = 3

# The operator's words, as typed: a paragraph is one line.
_BILLING = (
    "Move billing to the v2 API everywhere it is called, web and mobile both, and retire v1 once nothing reads it.\n\n"
    "v2 is down for a minute or two most weeks, so a call that fails should wait and try again rather than show the "
    "customer an error. Keep the invoices' numbers exactly as they are."
)

_OFFLINE = (
    "Show a customer's order history in the mobile app when it is offline, as of their last sync. The web account "
    "page has the same list; keep the two in step."
)

_FLAGS = "Replace the feature flags read from the `flags` table with the flags service, in api and web."

_BILLING_PLAN = """\
# Billing on v2

## Goal

Every billing call goes to v2, a failed call is retried from a queue, and the v1 flag is gone.

## Requirements

- **R1.** Every billing call in web and mobile goes to the v2 endpoint.
- **R2.** A billing call that fails while v2 is down is queued and retried, never shown to the customer as an error.
- **R3.** Nothing reads the `billing_v1` flag, and api no longer serves it.

## Contracts

- **C1.** `BillingClient`, the v2 client: `listInvoices`, `charge`, and `refund`, each returning v2's types unchanged.
  web provides it; mobile's screens and the retry queue use it.

## Breakdown

### B1. A v2 billing client in web

- Covers: R1
- Provides: C1
- Uses: none
- Repositories: web
- After: none
- Trivial: no

### B2. Retry failed billing calls from a queue

- Covers: R2
- Provides: none
- Uses: C1
- Repositories: web, mobile
- After: B1
- Trivial: no

### B3. Mobile's billing screens on v2

- Covers: R1
- Provides: none
- Uses: C1
- Repositories: mobile
- After: B1
- Trivial: no

### B4. Retire the v1 billing flag

- Covers: R3
- Provides: none
- Uses: none
- Repositories: api
- After: B1, B3
- Trivial: yes, it deletes one flag and its read, which nothing calls once B1 and B3 ship

## Decisions

- The queue lives in each client, not in api: a call api never received cannot be retried there.

## Out of scope

- The invoices' PDF layout.
"""

_OFFLINE_FIRST = """\
# Offline order history

## Goal

The order history reads from a local copy when the app is offline.

## Requirements

- **R1.** The mobile app shows the order history offline, as of its last sync.
- **R2.** The web account page and the app show the same orders.

## Contracts

- **C1.** `GET /orders/changes?since=`: the orders changed since a time, for a client's sync.

## Breakdown

### B1. A local copy of the order history in mobile

- Covers: R1
- Provides: none
- Uses: C1
- Repositories: mobile
- After: B2
- Trivial: no

### B2. A changes feed for the web account page and the app

- Covers: R2
- Provides: C1
- Uses: none
- Repositories: web
- After: none
- Trivial: no

## Decisions

- Sync on launch and on pull to refresh only.

## Out of scope

- Placing an order offline.
"""

_OFFLINE_REPLY = (
    "Drop the web half: the account page already reads the same API, so the two cannot drift. Keep it to mobile, and "
    "say how the local copy is cleared when the customer signs out."
)

_OFFLINE_SECOND = """\
# Offline order history

## Goal

The mobile app's order history reads from a local copy when it is offline, and the copy goes when its customer does.

## Requirements

- **R1.** The mobile app shows the order history offline, as of its last sync.
- **R2.** Signing out clears the local copy before the sign-in screen shows.

## Contracts

- **C1.** `OrderStore`: `orders()`, `sync()`, and `clear()`, the local copy the screens read.

## Breakdown

### B1. A local copy of the order history

- Covers: R1
- Provides: C1
- Uses: none
- Repositories: mobile
- After: none
- Trivial: no

### B2. The order screens read the local copy

- Covers: R1
- Provides: none
- Uses: C1
- Repositories: mobile
- After: B1
- Trivial: no

### B3. Clear the local copy at sign-out

- Covers: R2
- Provides: none
- Uses: C1
- Repositories: mobile
- After: B1
- Trivial: no

## Decisions

- The web account page is left as it is: it reads the same API the copy syncs from.

## Out of scope

- Placing an order offline.
"""

_EPICS = (
    # id, text, repositories, project, channel, submitted
    (APPROVED, _BILLING, ("api", "web", "mobile"), "ABC", "cli", -720),
    (PROPOSED, _OFFLINE, ("mobile", "web"), "ABC", "web", -260),
    (PLANNING, _FLAGS, ("api", "web"), None, "cli", -3),
)

#: A plan run's row as `seed` writes it: run, epic, started, ended, status, summary, the plan it wrote.
type _Run = tuple[int, int, int, int | None, RunStatus, str | None, str | None]

#: When the operator replied to epic 2's first plan, asking for changes.
_REPLIED = -200
#: The plan run whose plan the operator approved.
_APPROVED_RUN = 1

_RUNS: tuple[_Run, ...] = (
    (_APPROVED_RUN, APPROVED, -715, -690, RunStatus.DONE, "A plan of four entries; B4 is trivial.", _BILLING_PLAN),
    (2, PROPOSED, -258, -240, RunStatus.DONE, "A plan of two entries, one per repository.", _OFFLINE_FIRST),
    (3, PROPOSED, -190, -170, RunStatus.DONE, "Kept it to mobile, and added clearing at sign-out.", _OFFLINE_SECOND),
    (4, PLANNING, -2, None, RunStatus.RUNNING, None, None),
)

#: Epic 1's members: key, the entries each fulfils, and when it was added.
_MEMBERS = (
    ("ABC-103", ("B1",), -290),
    ("ABC-104", ("B2",), -285),
    ("ABC-100", (), -200),
)


def seed(conn: sqlite3.Connection, state_dir: Path, root: Path, at: Callable[[int], str]) -> None:
    """Insert the epics, their plan runs, plans, and members, and write each plan's file, epic 1's approved copy too."""
    for epic_id, text, repos, project, channel, submitted in _EPICS:
        records.insert(
            records.Epic,
            id=epic_id,
            text=text,
            project=project,
            tracker_epic=None,
            channel=channel,
            submitted_at=at(submitted),
        ).run(conn)
        records.insert_rows(records.EpicRepo, ("epic_id", "repo")).many(conn, [(epic_id, r) for r in repos])
    reply = records.insert(
        records.Message,
        subject_kind=conversation.EPIC,
        subject_id=str(PROPOSED),
        at=at(_REPLIED),
        source="operator",
        kind="reply",
        channel="web",
        body=_OFFLINE_REPLY,
    )
    reply_id = int(reply.run(conn).lastrowid or 0)
    approved: plans.Written | None = None
    for run_id, epic_id, started, ended, status, summary, plan in _RUNS:
        records.insert(
            records.EpicRun,
            id=run_id,
            epic_id=epic_id,
            tick_id=2,
            desk_path=str(desks.path(root, epic_runs.desk_key(epic_id))),
            started_at=at(started),
            ended_at=at(ended) if ended is not None else None,
            status=status,
            result_json=json.dumps({"status": "done", "summary": summary}) if summary is not None else None,
            log_path=str(state_dir / epic_runs.RUNS_DIR / f"{run_id}.log"),
            session_id=f"ses_epic{run_id}",
            # The run after the operator's reply carried it, so the reply is answered and no run is due for it.
            message_id=reply_id if started > _REPLIED and epic_id == PROPOSED else None,
        ).run(conn)
        if plan is not None and ended is not None:
            written = _plan(conn, state_dir, (epic_id, run_id), plan, at(ended))
            approved = written if epic_id == APPROVED else approved
    if approved is not None:
        _approve(conn, state_dir, approved.sha256, at(-600))
    _members(conn, at)


def _plan(conn: sqlite3.Connection, state_dir: Path, ran: tuple[int, int], text: str, at: str) -> plans.Written:
    """Write the plan run `ran`, an epic and its run, wrote as the epic's newest, as `epics.record_plan` does.

    Returns:
        The file's hash and size.
    """
    epic_id, run_id = ran
    written = epics.write_plan(state_dir, epic_id, run_id, text)
    superseded = records.update(records.EpicPlan).set(status=PlanStatus.SUPERSEDED)
    superseded.where("epic_id = ?", epic_id).run(conn)
    records.insert(
        records.EpicPlan,
        epic_id=epic_id,
        run_id=run_id,
        created_at=at,
        sha256=written.sha256,
        size=written.size,
    ).run(conn)
    return written


def _approve(conn: sqlite3.Connection, state_dir: Path, sha256: str, at: str) -> None:
    """Approve epic 1's plan, whose file hashes to `sha256`, as its planner wrote it, keeping `epics.approve`'s copy."""
    path = epics.approved_path(state_dir, APPROVED, _APPROVED_RUN, sha256)
    plans.write_new(state_dir / epics.PLANS_DIR, str(APPROVED), path.name, _BILLING_PLAN)
    records.update(records.EpicPlan).set(
        status=PlanStatus.APPROVED,
        approved_sha256=sha256,
        approved_at=at,
        approved_channel="web",
    ).where("run_id = ?", _APPROVED_RUN).run(conn)


def _members(conn: sqlite3.Connection, at: Callable[[int], str]) -> None:
    """Make epic 1's members, each registered against its entries, as `epics.add` does after the approval."""
    for key, entries, added in _MEMBERS:
        member = records.insert(
            records.EpicMember,
            epic_id=APPROVED,
            ticket_key=key,
            added_at=at(added),
            added_channel="cli",
        )
        member_id = int(member.run(conn).lastrowid or 0)
        _register(conn, member_id, entries)


def _register(conn: sqlite3.Connection, member_id: int, entries: Sequence[str]) -> None:
    if entries:
        rows = records.insert_rows(records.EpicMemberEntry, ("member_id", "entry"))
        rows.many(conn, [(member_id, e) for e in entries])
