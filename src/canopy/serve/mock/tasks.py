"""The mock journal's one-off tasks (DESIGN §36), for `python -m canopy.serve --mock`.

Seven tasks across the three repositories, one in each state a task has. Task 1, in web, is done: its long text named
project ABC, and its run pushed `agent/task/1`, opened a draft PR, left a report kept in the state directory, and filed
two tickets recorded against it. Task 2, in mobile, failed on a short text; task 3, in web, was stopped while its run
worked. Task 4, in web, is blocked on a question no reply has followed, so it raises `awaiting_reply`. Task 5, in
mobile, named no project, so the ticket its run reported raises `task_ticket_unrecorded`. Task 6 runs in mobile's
second slot, whose lease the mock's pool holds for it; task 7, in api, which has no clone, waits for a tick.

The attention list's two task items are read from these rows as `loop.attention.listed` reads them, so a reply to a
task, or its stop, clears them here too.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from canopy.core import conversation, sql
from canopy.core.items import Item
from canopy.core.vocab import RunStatus
from canopy.runs import task_tickets, tasks

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from pathlib import Path

#: Where a ticket key would be, an item about a task names it so, as `loop.attention.TASK_PREFIX` does.
TASK_PREFIX = "task:"
#: The task whose run is running, in mobile's second slot.
RUNNING_TASK = 6
#: The lease the running task's run holds, which the mock's pool shows on its slot.
RUNNING_LEASE = "lease-4"
#: The draft PR task 1's run opened.
PR_97 = "https://github.com/acme/web/pull/97"
#: How a run the operator stopped with `canopy stop task:N --now` ends, as `runs.task_run.STOP_NOTE` says it.
STOP_NOTE = "the operator stopped the task with `canopy stop --now`"

_LONG_TEXT = """\
The checkout page's bundle grew past 900 kB after the last two releases, and the first paint on a mid-range phone is
now over three seconds. Find out what grew and cut it back.

What I know so far:
- the date picker pulls in all of moment's locales, which we never use
- the payment iframe's SDK is imported eagerly, though it only loads after the address step
- someone added lodash whole for a single debounce

Keep the public behavior the same: no visual change, no change to the order of the steps. Open a draft PR with what you
change, and file a ticket in ABC for anything you find that is too big for this one, so it does not get lost. Do not
touch the analytics snippet: marketing owns it and will notice."""

_REPORT = """# Checkout bundle

The checkout bundle is 612 kB, down from 934 kB; first paint on the throttled profile is 1.9 s, down from 3.2 s.

## What changed

- **moment** is replaced by `date-fns` in the date picker, which ships no locales we do not import (214 kB less).
- The payment SDK loads on the address step's *Continue*, through a dynamic `import()` (88 kB less).
- `lodash` is gone: the one debounce is `useDebounced` from our own hooks (20 kB less).

## Filed

- ABC-120: the icon font ships 1,400 glyphs and checkout uses 31.
- ABC-121: the analytics snippet blocks the main thread for 180 ms; left alone, as asked.

## Not done

The CSS is still one file for the whole app. Splitting it per route is a bigger change than this task.
"""

_TASKS = (
    # id, text, repo, project, channel, submitted, stopped
    (1, _LONG_TEXT, "web", "ABC", "web", -420, None),
    (2, "Bump the iOS deployment target to 16.", "mobile", None, "cli", -300, None),
    (
        3,
        "Profile the dashboard's first paint and write down where the time goes.",
        "web",
        None,
        "web",
        -260,
        -240,
    ),
    (
        4,
        "Rename the `billing_v1` feature flag to `billing_legacy` everywhere it is read.",
        "web",
        "ABC",
        "cli",
        -40,
        None,
    ),
    (5, "Find out why the Android build takes twelve minutes.", "mobile", None, "web", -100, None),
    (6, "Add a dark launch screen to match the app's theme.", "mobile", None, "cli", -1, None),
    (7, "List the endpoints that still accept API keys in the query string.", "api", None, "cli", -2, None),
)

#: A task run's row as `seed` writes it: run, task, repo, slot, started, ended, status, result, head, cost.
type _Run = tuple[int, int, str, int, int, int | None, RunStatus, dict[str, object] | None, str | None, float]

# The ticket task 5's run reported, which its task, naming no project, cannot record.
_UNRECORDED = task_tickets.check(["OPS-7"], project=None, limit=3)


def seed(conn: sqlite3.Connection, state_dir: Path, at: Callable[[int], str], slot: Callable[[str, int], str]) -> None:
    """Insert the tasks, their runs and conversations, task 1's report and tickets; `slot` names a pool slot's path."""
    for task_id, text, repo, project, channel, submitted, stopped in _TASKS:
        sql.execute(
            conn,
            sql.insert(
                "tasks",
                id=task_id,
                text=text,
                repo=repo,
                project=project,
                channel=channel,
                submitted_at=at(submitted),
                stopped_at=at(stopped) if stopped is not None else None,
            ),
        )
    runs: tuple[_Run, ...] = (
        # run, task, repo, slot, started, ended, status, result, head, cost
        (
            1,
            1,
            "web",
            4,
            -418,
            -380,
            RunStatus.DONE,
            {
                "status": "done",
                "summary": "Cut the checkout bundle from 934 kB to 612 kB; filed two tickets for what is left.",
                "question": None,
                "branch": "agent/task/1",
                "prs": [PR_97],
            },
            "5e0b7c2a9d41f3e86a2c4b7d9e1f0a3c5b8d2e4f",
            2.12,
        ),
        (
            2,
            2,
            "mobile",
            2,
            -298,
            -290,
            RunStatus.FAILED,
            {
                "status": "failed",
                "summary": "CocoaPods 1.11 on this machine cannot resolve the pods for iOS 16; it needs 1.12 or later.",
                "question": None,
                "branch": None,
                "prs": [],
            },
            None,
            0.41,
        ),
        (3, 3, "web", 4, -255, -240, RunStatus.STOPPED, {"harness": STOP_NOTE}, None, 0.37),
        (
            4,
            4,
            "web",
            4,
            -38,
            -12,
            RunStatus.BLOCKED,
            {
                "status": "blocked",
                "summary": "Renamed the flag in web's code and tests; the admin console reads it too.",
                "question": (
                    "The admin console in api reads `billing_v1` from the flags table. Rename it there as well, "
                    "or keep the old name as an alias until the console ships?"
                ),
                "branch": "agent/task/4",
                "prs": [],
            },
            None,
            0.88,
        ),
        (
            5,
            5,
            "mobile",
            2,
            -95,
            -45,
            RunStatus.DONE,
            {
                "status": "done",
                "summary": "R8 runs twice, once per flavor; the release flavor alone needs it. Filed OPS-7 for CI.",
                "question": None,
                "branch": None,
                "prs": [],
                "harness": _UNRECORDED.note(),
                **_UNRECORDED.stored(),
            },
            None,
            0.64,
        ),
        (6, RUNNING_TASK, "mobile", 2, 2, None, RunStatus.RUNNING, None, None, 0.09),
    )
    for run_id, task_id, repo, slot_number, started, ended, status, result, head, cost in runs:
        running = status is RunStatus.RUNNING
        sql.execute(
            conn,
            sql.insert(
                "task_runs",
                id=run_id,
                task_id=task_id,
                tick_id=2,
                branch=tasks.branch("agent/", task_id),
                repo=repo,
                slot_path=slot(repo, slot_number),
                lease_id=RUNNING_LEASE if running else f"lease-task-{run_id}",
                lease_holder=tasks.holder(task_id),
                base_branch="main",
                pool="treehouse",
                started_at=at(started),
                ended_at=at(ended) if ended is not None else None,
                status=str(status),
                result_json=json.dumps(result) if result is not None else None,
                head=head,
                log_path=str(state_dir / "task-runs" / f"{run_id}.log"),
                session_id=f"ses_task{run_id}",
                cost_usd=cost,
                tokens_input=int(cost * 40_000),
                tokens_output=int(cost * 6_000),
                tokens_cache_read=int(cost * 400_000),
                tokens_peak_context=int(cost * 60_000),
            ),
        )
        if result is not None and ended is not None:
            # The messages `tasks.close_run` records as a run ends: its report, and a blocked run's question.
            for kind, body in conversation.run_messages(status, json.dumps(result)):
                sql.execute(
                    conn,
                    sql.insert(
                        "messages",
                        subject_kind=conversation.TASK,
                        subject_id=str(task_id),
                        at=at(ended),
                        source="worker",
                        kind=kind,
                        channel="run",
                        body=body,
                        task_run_id=run_id,
                    ),
                )
    kept = tasks.keep_report(state_dir, 1, 1, _REPORT)
    tasks.set_report(conn, 1, kept.sha256)
    sql.execute_many(
        conn,
        sql.insert_rows("task_tickets", ("task_id", "task_run_id", "key", "at")),
        [(1, 1, "ABC-120", at(-380)), (1, 1, "ABC-121", at(-380))],
    )


def attention(conn: sqlite3.Connection) -> list[Item]:
    """The tasks' attention items, as `loop.attention.listed` builds them from the journal (DESIGN §36).

    Returns:
        Each task's `awaiting_reply` item, then each `task_ticket_unrecorded` item.
    """
    waiting = [
        Item(
            f"{TASK_PREFIX}{w.task_id}",
            "awaiting_reply",
            f"{TASK_PREFIX}{w.task_id}'s run {w.run_id} asked you a question, message {w.message_id}: read it with "
            f"`canopy show {TASK_PREFIX}{w.task_id}`, and answer with `canopy reply {TASK_PREFIX}{w.task_id}`",
            w.at,
        )
        for w in tasks.awaiting(conn)
    ]
    unrecorded = [
        Item(
            f"{TASK_PREFIX}{u.task_id}",
            task_tickets.REASON,
            f"{TASK_PREFIX}{u.task_id}'s run {u.run_id} reported {u.count} {'ticket' if u.count == 1 else 'tickets'} "
            f"that canopy did not record against it: `canopy show {TASK_PREFIX}{u.task_id}` names each and why. It "
            "clears when you reply to the task or stop it",
            u.at,
        )
        for u in task_tickets.unrecorded(conn)
    ]
    return waiting + unrecorded
