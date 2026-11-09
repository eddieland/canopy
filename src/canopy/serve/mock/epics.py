"""The mock journal's epics (DESIGN §43), for `python -m canopy.serve --mock`.

Four epics across the workspace's repositories, one in each place an epic's plan stands, and one the operator stopped.
Epic 1, over api, web, and mobile, was planned before its tickets existed: its plan run's plan, approved, breaks it into
four entries, of which B4 is marked trivial. The operator filed tickets for two and registered each after the approval:
ABC-103 fulfils B1, its PR 91 open, and ABC-104 fulfils B2, its resume running; ABC-100, a ticket the breakdown did not
foresee, is a member of no entry. ABC-103 was planned first: its planner read the approved plan, so its own plan,
approved, follows it. ABC-107, B2's mobile half, was planned and approved too, before its first implement. Then the
operator replied, asking that a refund take an idempotency key: a second plan run changed C1, and they approved it.
The change reached every member: ABC-107, approved with no branch yet, has its implement held (`epic_changed`) until
they approve its plan again or ask for a new one, and the rest, at work or with a branch, are only told. Epic 2, over
mobile and web, had a plan the operator replied to, asking for changes; its second plan run wrote the plan that now
waits on them. Epic 3, over api and web, was just submitted, and its first plan run works. Epic 4, over web, the
operator stopped as soon as they submitted it, before a tick started its plan run: it has no plan, and none starts
again.

The plan runs, ABC-103's and ABC-107's too, report no cost, so the spend page's totals are what they were without
them. The running one holds no slot in the mock's pools, which show no lease for it. Every row and message here takes
its id after every other fixture's: `seed` runs last.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from canopy.core import conversation, db, epic_changes, epics, plans, records
from canopy.core.items import Item
from canopy.core.vocab import PlanEffort, PlannerApproval, PlanStatus, RunKind, RunStatus
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
#: The epic the operator stopped before any plan run of it started.
STOPPED = 4

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

_DARK = "Give the web app a dark theme that follows the system's setting."

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

#: Epic 1's plan as approved the second time: C1's refund takes an idempotency key, which reaches every member.
_BILLING_SECOND = _BILLING_PLAN.replace(
    "each returning v2's types unchanged.\n",
    "each returning v2's types unchanged.\n"
    "  `refund` takes an idempotency key, so a refund the queue retries is made once.\n",
)

#: The operator's reply to epic 1's approved plan, which its second plan run answered.
_BILLING_REPLY = (
    "A refund retried from the queue must never be made twice: have `refund` take an idempotency key, and say so in C1."
)

# ABC-103's plan, for B1, written against epic 1's approved plan.
_MEMBER_PLAN = """\
# A v2 billing client in web

## What changes

In **web**, a `BillingClient` for the v2 endpoint, as the epic's contract C1 names it: `listInvoices`, `charge`, and
`refund`, each returning v2's types unchanged. Every billing call in web moves to it, and the v1 client goes.

## Tests

- [ ] each method calls its v2 endpoint and returns its type unchanged
- [ ] nothing in web imports the v1 client
"""

# ABC-107's plan, for B2's mobile half, written against epic 1's first approved plan, before C1 changed.
_HELD_PLAN = """\
# Retry billing calls in mobile

## What changes

In **mobile**, a queue for billing calls that fail while v2 is down, retried with backoff through the epic's C1,
`BillingClient`, and never shown to the customer as an error.

## Tests

- [ ] a call that fails is queued, and retried once v2 answers
- [ ] the customer sees no error while it waits
"""

#: The member whose implement epic 1's second approval holds: approved before C1 changed, with no branch yet.
HELD = "ABC-107"

#: The members planned against epic 1's first approved plan: each one's plan, its run's summary, and when it was written
#: and approved.
_MEMBER_PLANS = {
    "ABC-103": (_MEMBER_PLAN, "A v2 billing client in web, as the epic's C1.", -238, -200),
    HELD: (_HELD_PLAN, "A retry queue in mobile, through the epic's C1.", -140, -120),
}

_EPICS = (
    # id, text, repositories, project, channel, submitted
    (APPROVED, _BILLING, ("api", "web", "mobile"), "ABC", "cli", -720),
    (PROPOSED, _OFFLINE, ("mobile", "web"), "ABC", "web", -260),
    (PLANNING, _FLAGS, ("api", "web"), None, "cli", -3),
    (STOPPED, _DARK, ("web",), "ABC", "web", -1),
)

#: When the operator stopped epic 4: as soon as they submitted it.
_STOPPED_AT = -1

#: A plan run's row as `seed` writes it: run, epic, started, ended, status, summary, the plan it wrote.
type _Run = tuple[int, int, int, int | None, RunStatus, str | None, str | None]

#: When the operator replied to epic 2's first plan, asking for changes.
_REPLIED = -200
#: When the operator replied to epic 1's approved plan, asking for C1's change.
_BILLING_REPLIED = -80
#: The plan run whose plan the operator approved first, and the one they approved since, with when they did.
_APPROVED_RUN = 1
_SECOND_RUN = 5
_APPROVALS = ((_APPROVED_RUN, _BILLING_PLAN, -600), (_SECOND_RUN, _BILLING_SECOND, -55))

_RUNS: tuple[_Run, ...] = (
    (_APPROVED_RUN, APPROVED, -715, -690, RunStatus.DONE, "A plan of four entries; B4 is trivial.", _BILLING_PLAN),
    (2, PROPOSED, -258, -240, RunStatus.DONE, "A plan of two entries, one per repository.", _OFFLINE_FIRST),
    (3, PROPOSED, -190, -170, RunStatus.DONE, "Kept it to mobile, and added clearing at sign-out.", _OFFLINE_SECOND),
    (4, PLANNING, -2, None, RunStatus.RUNNING, None, None),
    (_SECOND_RUN, APPROVED, -75, -62, RunStatus.DONE, "C1's refund takes an idempotency key.", _BILLING_SECOND),
)

#: Epic 1's members: key, the entries each fulfils, and when it was added. The second approval's C1 reached each.
_MEMBERS = (
    ("ABC-103", ("B1",), -290),
    ("ABC-104", ("B2",), -285),
    ("ABC-100", (), -200),
    (HELD, ("B2",), -170),
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
    billing = records.insert(
        records.Message,
        subject_kind=conversation.EPIC,
        subject_id=str(APPROVED),
        at=at(_BILLING_REPLIED),
        source="operator",
        kind="reply",
        channel="web",
        body=_BILLING_REPLY,
    )
    billing_id = int(billing.run(conn).lastrowid or 0)
    written_by: dict[int, plans.Written] = {}
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
            message_id=_answered(epic_id, started, reply_id, billing_id),
        ).run(conn)
        if plan is not None and ended is not None:
            written_by[run_id] = _plan(conn, state_dir, (epic_id, run_id), plan, at(ended))
    for run_id, text, approved in _APPROVALS:
        _approve(conn, state_dir, (run_id, text), written_by[run_id].sha256, at(approved))
    records.update(records.Epic).set(stopped_at=at(_STOPPED_AT)).where("id = ?", STOPPED).run(conn)
    _held_ticket(conn, root, at)
    _members(conn, at)
    for key in _MEMBER_PLANS:
        _member_plan(conn, state_dir, at, key)


def attention(conn: sqlite3.Connection) -> list[Item]:
    """The epics' members' `epic_changed` items, as the harness raises them from the journal (DESIGN §43).

    Returns:
        One for each member whose implement a change of its epic's plan holds, open since that plan's approval.
    """
    found: list[Item] = []
    for member in records.select(records.EpicMember).where("removed_at IS NULL").order_by("id").all(conn):
        held = epic_changes.held(conn, member.ticket_key)
        since = epics.approved_plan(conn, member.epic_id)
        if held is not None and since is not None and since.approved_at is not None:
            found.append(Item(held.key, epic_changes.REASON, held.detail(), since.approved_at))
    return found


def _answered(epic_id: int, started: int, *replies: int) -> int | None:
    """The reply a plan run of epic `epic_id`, started at `started`, carried: the operator's last before it.

    Returns:
        Its message's id, of `replies`, epic 2's then epic 1's; None for a run before any reply.
    """
    if epic_id == PROPOSED and started > _REPLIED:
        return replies[0]
    if epic_id == APPROVED and started > _BILLING_REPLIED:
        return replies[1]
    return None


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


def _approve(conn: sqlite3.Connection, state_dir: Path, ran: tuple[int, str], sha256: str, at: str) -> None:
    """Approve the plan epic 1's run wrote, `ran` its run and text, hashing to `sha256`, keeping `epics.approve`'s copy.

    The newest stays approved; one a newer plan superseded keeps its approval, as what the next was compared with.
    """
    run_id, text = ran
    path = epics.approved_path(state_dir, APPROVED, run_id, sha256)
    plans.write_new(state_dir / epics.PLANS_DIR, str(APPROVED), path.name, text)
    newest = run_id == _SECOND_RUN
    records.update(records.EpicPlan).set(
        status=PlanStatus.APPROVED if newest else PlanStatus.SUPERSEDED,
        approved_sha256=sha256,
        approved_at=at,
        approved_channel="web",
    ).where("run_id = ?", run_id).run(conn)


def _members(conn: sqlite3.Connection, at: Callable[[int], str]) -> None:
    """Make epic 1's members, each registered against its entries, as `epics.add` does after the approval.

    Each keeps C1, which the second approval reached it by, as its pending notice (`epic_changes.reach`).
    """
    for key, entries, added in _MEMBERS:
        member = records.insert(
            records.EpicMember,
            epic_id=APPROVED,
            ticket_key=key,
            added_at=at(added),
            added_channel="cli",
            changed_ids="C1",
        )
        member_id = int(member.run(conn).lastrowid or 0)
        _register(conn, member_id, entries)


def _member_plan(conn: sqlite3.Connection, state_dir: Path, at: Callable[[int], str], key: str) -> None:
    """Plan `key` against epic 1's first approved plan, as its planner's run records it, and approve it via web.

    ABC-103's implement follows it; HELD has none yet. Its run takes an id after every other fixture's, and reports no
    cost, so the spend page's totals stay as they were.
    """
    text, summary, written_at, approved_at = _MEMBER_PLANS[key]
    run = records.insert(
        records.Run,
        tick_id=1,
        ticket_key=key,
        kind=RunKind.PLAN,
        branch="",
        started_at=at(written_at - 12),
        ended_at=at(written_at),
        status=RunStatus.DONE,
        result_json=json.dumps({"status": "done", "summary": summary}),
        log_path="",
        private=0,
        # Before ABC-105's, so at the level its plans were offered too, before the operator turned the key off.
        plan_review=PlannerApproval.STRICT,
    )
    run_id = db.rowid(run.run(conn))
    log = state_dir / "runs" / f"{run_id}.log"
    records.update(records.Run).set(log_path=str(log)).where("id = ?", run_id).run(conn)
    written = plans.write(state_dir, key, run_id, text)
    followed = records.select(records.EpicPlan).where("run_id = ?", _APPROVED_RUN).one(conn)
    plan = records.insert(
        records.Plan,
        ticket_key=key,
        run_id=run_id,
        created_at=at(written_at),
        status=PlanStatus.APPROVED,
        sha256=written.sha256,
        size=written.size,
        approved_sha256=written.sha256,
        approved_at=at(approved_at),
        approved_channel="web",
        effort=PlanEffort.SMALL,
        epic_plan_id=followed.id if followed is not None else None,
    )
    plan_id = db.rowid(plan.run(conn))
    # Its implement, its first, followed the plan.
    implement = records.update(records.Run).set(plan_id=plan_id)
    implement.where(
        "id = (SELECT min(id) FROM runs WHERE ticket_key = ? AND kind = ?)",
        key,
        RunKind.IMPLEMENT,
    ).run(conn)


def _held_ticket(conn: sqlite3.Connection, root: Path, at: Callable[[int], str]) -> None:
    """Insert HELD, a ticket held for canopy and planned, its implement not yet dispatched: no branch, so `ready`."""
    records.insert(
        records.Ticket,
        key=HELD,
        repo=str(root),
        first_seen_at=at(-175),
        last_seen_at=at(-8),
        changed_at=at(-55),
        title="Retry billing calls in mobile",
        phase="ready",
    ).run(conn)


def _register(conn: sqlite3.Connection, member_id: int, entries: Sequence[str]) -> None:
    if entries:
        rows = records.insert_rows(records.EpicMemberEntry, ("member_id", "entry"))
        rows.many(conn, [(member_id, e) for e in entries])
