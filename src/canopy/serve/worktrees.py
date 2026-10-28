"""The worktrees page (DESIGN §22): each pool's slots from `treehouse status --json`, with the run that holds each.

treehouse is read when the page asks, never by the event stream: the journal does not record what a slot has checked
out or what runs in it, and a `treehouse status` a second per open page would cost more than the page is worth. A
lease is matched to a running run or review by its lease id, as reconcile matches them. Branch names and process names
are text from the machine and the workers, so the UI renders them as text, like everything from the journal.

The pools are read at once, a thread each, so a workspace of many repositories waits on its slowest pool rather than on
all of them in turn. `treehouse status` changes no lease, but it takes the pool's state lock and may rewrite the
pool's state file as it heals it, as reconcile's reads do every tick: a slow read can hold up a lease in that pool for
as long as it takes.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from canopy.core import conversation, db, records, tasks
from canopy.core.pools import AVAILABLE, HOLDER_PREFIX, QUARANTINED, SYNC_HOLDER, PoolError, Slot
from canopy.serve import views
from canopy.serve.schema.worktree import Pool, Process, ReviewHold, TaskHold, Worktree, WorktreeState

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence
    from pathlib import Path

    from canopy.core.context import Context
    from canopy.serve.backend import Backend

# At most this many pools are read at once.
READERS: Final = 8
# How many of a slot's processes the page lists; a build can start hundreds.
PROCESSES: Final = 20
_STATES: Final[dict[str, WorktreeState]] = {
    AVAILABLE: "idle",
    "you're here": "idle",
    "leased": "held",
    "in-use": "held",
    "dirty": "dirty",
}
_NO_CLONE: Final = "no clone; run `canopy workspace sync`"
_STALE: Final = "no running run holds this lease; the next tick's reconcile returns it"
_SYNC: Final = "held while `canopy workspace sync` makes this pool's slots"
# What a dirty slot blocks and what clears it (DESIGN §18, What a pool guarantees). No canopy command clears one: its
# changes may be someone's work, so the operator keeps or discards them.
_DIRTY: Final = (
    "never reused while it has changes, and counts as busy, so a full pool refuses a lease: keep what you need of "
    "them, then discard them in the slot"
)
# What holds a slot a failed seeding left, and what frees it (DESIGN §18): only the operator, once they have looked.
_QUARANTINED: Final = (
    "seeding found a file already in this slot, so the pool holds it and counts it as busy: remove the file it "
    "collided with, then run `canopy workspace release {repo} {name}`"
)


def pools(backend: Backend, ctx: Context) -> list[Pool]:
    """Every pool of the workspace, in map order, each with its slots or why they could not be read.

    Returns:
        One pool per repository in the map. One with no clone, or whose slots could not be read, carries an error
        instead of worktrees.
    """
    running = db.running_runs(ctx.conn, "runs")
    by_lease: dict[str, sqlite3.Row] = {}
    for run_id, slots in db.all_run_slots(ctx.conn, [int(r["id"]) for r in running]).items():
        row = next(r for r in running if int(r["id"]) == run_id)
        by_lease |= {str(s.lease_id): row for s in slots}
    reviews = {str(r["lease_id"]): r for r in db.running_runs(ctx.conn, "review_runs") if r["lease_id"]}
    # A task's run holds a slot too (DESIGN §36), matched by lease id as a ticket's run is.
    for_tasks = {r.lease_id: r for r in tasks.running(ctx.conn)}
    root = ctx.workspace.root
    sizes = {repo.name: ctx.config.capacity.slots_for(repo.name) for repo in ctx.workspace.repos}
    cloned = [repo for repo in ctx.workspace.repos if repo.cloned]
    # Each read opens a Context of its own: a pool may read the journal, and `ctx.conn` belongs to this thread.
    with ThreadPoolExecutor(max_workers=max(1, min(READERS, len(cloned))), thread_name_prefix="canopy-pool") as ex:
        reads = {repo.name: ex.submit(_read, backend, repo.name) for repo in cloned}
    found: list[Pool] = []
    for repo in ctx.workspace.repos:
        size = sizes[repo.name]
        if not repo.cloned:
            found.append(Pool(repo=repo.name, size=size, error=_NO_CLONE))
            continue
        try:
            slots = reads[repo.name].result()
        except PoolError as e:
            found.append(Pool(repo=repo.name, size=size, error=str(e)))
            continue
        worktrees = [
            worktree(
                s,
                by_lease.get(s.lease_id),
                reviews.get(s.lease_id),
                root=root,
                repo=repo.name,
                task=for_tasks.get(s.lease_id),
            )
            for s in slots
        ]
        found.append(Pool(repo=repo.name, size=size, worktrees=worktrees))
    return found


def worktree(
    slot: Slot,
    run: sqlite3.Row | None,
    review: sqlite3.Row | None,
    *,
    root: Path,
    repo: str,
    task: records.TaskRun | None = None,
) -> Worktree:
    """One slot of `repo`'s pool, with the running run or review that holds its lease, if the journal has one.

    Its path is shown from workspace `root` when under it. `task` is the running task's run that holds it, if one does
    (DESIGN §36).

    Returns:
        The worktree, `working` while a run, review, or task holds it, with a note when its lease is canopy's but no
        running run holds it, or `canopy workspace sync` does, when a failed seeding holds it, or when it is dirty.
    """
    leased = slot.lease_id != ""
    state: WorktreeState = _STATES.get(slot.status, "broken")
    note = None
    if run is not None or review is not None or task is not None:
        state = "working"
    elif slot.lease_holder == QUARANTINED:
        note = _QUARANTINED.format(repo=repo, name=slot.name)
    elif leased and slot.lease_holder == SYNC_HOLDER:
        note = _SYNC
    elif leased and slot.lease_holder.startswith(HOLDER_PREFIX):
        note = _STALE
    elif state == "dirty":
        note = _DIRTY
    return Worktree(
        name=slot.name,
        path=views.shown_path(str(slot.path), root),
        status=slot.status,
        state=state,
        # A run's slot is detached (D109): the branch it works on is the run's.
        branch=_text(slot.branch) or (_run_branch(run, task) if slot.detached else None),
        detached=slot.detached,
        branch_error=_text(slot.branch_error),
        holder=_text(slot.lease_holder),
        leased_at=_time(slot.leased_at),
        run=views.run(run, root) if run is not None else None,
        review=(
            ReviewHold(
                id=int(review["id"]),
                pr_url=str(review["pr_url"]),
                started_at=db.parse_time(str(review["started_at"])),
            )
            if review is not None
            else None
        ),
        task=(
            TaskHold(task_id=task.task_id, run_id=task.id, started_at=db.parse_time(task.started_at))
            if task is not None
            else None
        ),
        note=note,
        processes=[Process(pid=p.pid, name=conversation.printable(p.name)) for p in slot.processes[:PROCESSES]],
    )


def _run_branch(run: sqlite3.Row | None, task: records.TaskRun | None) -> str | None:
    """The branch a run or task's run that holds a detached slot works on, or None when neither holds it.

    Returns:
        The branch on one line, or None.
    """
    if run is not None:
        return _text(str(run["branch"]))
    return _text(task.branch) if task is not None else None


def _read(backend: Backend, repo: str) -> Sequence[Slot]:
    with backend.open() as own:
        return backend.slots(own, repo)


def _time(stamp: str | None) -> datetime | None:
    """When treehouse says a slot was leased, or None if it says nothing a page can show.

    Returns:
        The time in UTC, or None for a missing stamp, one that is not ISO 8601, or one with no offset.
    """
    if stamp is None:
        return None
    try:
        found = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    return found.astimezone(UTC) if found.tzinfo is not None else None


def _text(value: str) -> str | None:
    """A value from treehouse on one line without control characters, or None when it is empty.

    Returns:
        `value` with control characters made spaces and whitespace collapsed, or None if nothing is left.
    """
    return " ".join(conversation.printable(value).split()) or None
