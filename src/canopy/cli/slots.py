"""`canopy workspace slots`, `release`, and `remove-slot`: the operator's commands for a pool's slots (DESIGN §18).

`slots` lists every slot of each repository's pools: the one `pools.backend` names and, after a switch, the other's
while it still has slots, since a lease goes back to the pool that made it. Each slot comes with the running run,
review, or task whose lease holds it, matched by lease id as reconcile matches them. `release` frees a slot nothing
running holds: one a failed seeding quarantined, which only the operator frees, or a `canopy:` lease the next tick's
reconcile would return. `remove-slot` removes one slot only if nothing in it could be lost, as sync's trim does. Both
change a pool only between ticks.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, assert_never

import click

from canopy.cli.common import CliError, between_ticks, open_context, require_workspace
from canopy.cli.params import REPO
from canopy.core import conversation, db, pool, pools, records, reports, workspace
from canopy.core.vocab import PoolKind
from canopy.infra.text import one_line, printable
from canopy.runs import tasks

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping, Sequence

    from canopy.core.context import Context

#: How many of a slot's processes a line names; a build can start hundreds.
PROCESSES = 5
_NO_CLONE = "no clone; run `canopy workspace sync`"


@dataclass(frozen=True)
class Found:
    """A slot, and the pool it is in: the one `pools.backend` names, or the other's left from a switch."""

    kind: PoolKind
    pool: pools.Pool
    slot: pools.Slot


@click.command("slots")
@click.argument("repos", metavar="[REPO]...", nargs=-1, type=REPO)
@click.option("--json", "as_json", is_flag=True, help="Print the pools as one JSON object instead.")
@click.pass_context
def cmd_slots(click_ctx: click.Context, repos: tuple[str, ...], *, as_json: bool) -> int:
    """List each pool's slots, with what holds each, for every repository in the map or those named.

    Each slot shows its number, its status, its lease's holder and when it was taken, the running run, review, or
    task that holds that lease, and its path; under canopy's pool, the files seeding wrote, and with `--json` the
    branch its last lease was based on. A slot that waits on you has a note saying what frees it. After a switch of
    `pools.backend`, the other pool is listed too while it has slots. Changes nothing; exits 1 when a pool could not
    be read.
    """
    require_workspace()
    ctx = open_context(click_ctx)
    for name in repos:
        _known(ctx, name)
    named = set(repos)
    listed = [r for r in ctx.workspace.repos if not named or r.name in named]
    held = holders(ctx.conn)
    report = [entry for repo in listed for entry in _read(ctx, repo, held)]
    if as_json:
        click.echo(reports.report_json({"pools": report}))
    else:
        for entry in report:
            for line in _render(entry, ctx.workspace.root):
                click.echo(line)
        if not listed:
            click.echo(f"The map lists no repositories; add them under [repos.<name>] in {ctx.workspace.map_file}.")
    unread = sum(entry["error"] is not None for entry in report)
    if unread:
        raise CliError(f"{unread} of {len(report)} pools could not be read; see above")
    return 0


@click.command("release")
@click.argument("repo", type=REPO)
@click.argument("slot", metavar="SLOT")
@click.pass_context
def cmd_release(click_ctx: click.Context, repo: str, slot: str) -> int:
    """Free a slot of REPO's pool that nothing running holds, so the next lease can reuse it.

    Two holds are freed. When seeding finds a file already in a reused slot, the lease fails and the pool holds the
    slot as `quarantined: worktree seeding failed`, counted as busy, until it is released. Look at the slot first:
    release resets it as a return does and keeps its ignored files, the one seeding collided with too, so a lease that
    seeds it fails again until you remove that file. And a `canopy:` lease whose run, review, or task is no longer
    running is returned now, as the next tick's reconcile would return it: its processes ended, its changes and
    unpushed commits discarded. SLOT is the slot's number, as `canopy workspace slots` shows it, or its path. A slot
    a running run, review, or task holds is refused: its lease goes back when that ends. Waits for a running tick to
    end.
    """
    _refuse_inside_run("release")
    require_workspace()
    ctx = open_context(click_ctx)
    _known(ctx, repo)
    # A dispatch records its run only after it has leased, so the dispatch lock keeps an unrecorded lease from looking
    # like one nothing holds.
    with between_ticks(ctx, "release", dispatches=True):
        found = find(ctx, repo, slot)
        s = found.slot
        held = holders(ctx.conn)
        try:
            if s.lease_holder == pools.QUARANTINED:
                outcome, did = found.pool.release(s.path), f"released slot {s.name} ({s.path})"
            elif s.lease_id and s.canopy_key is not None and s.lease_id not in held:
                outcome = found.pool.return_slot(s.path, lease_id=s.lease_id, lease_holder=s.lease_holder)
                did = f"returned slot {s.name} ({s.path}), whose lease {s.lease_holder} no running run held"
            else:
                raise CliError(f"slot {s.name} {_unreleasable(s, held)}; nothing released")
        except pools.PoolError as e:
            raise CliError(f"{repo}'s pool: {e}") from e
    match outcome:
        case pools.ReturnOutcome.RETURNED:
            click.echo(f"{repo}: {did}")
        case pools.ReturnOutcome.FAILED | pools.ReturnOutcome.DIRTY:
            raise CliError(
                f"{repo}'s pool kept slot {s.name}: its hold changed since it was read, or a process in it outlived "
                "its signals",
            )
        case unknown:
            assert_never(unknown)
    return 0


@click.command("remove-slot")
@click.argument("repo", type=REPO)
@click.argument("slot", metavar="SLOT")
@click.pass_context
def cmd_remove_slot(click_ctx: click.Context, repo: str, slot: str) -> int:
    """Remove one slot of REPO's pool, only if nothing in it could be lost.

    The slot must be idle, as sync requires of the slots it trims: unleased, with no process in it, no changes, and
    its HEAD merged into the default branch. One whose directory is gone is forgotten. A slot kept is named with why,
    and exits 1. With a size declared, the next `canopy workspace sync` makes a fresh slot in its place. SLOT is the
    slot's number, as `canopy workspace slots` shows it, or its path. Waits for a running tick to end.
    """
    _refuse_inside_run("remove-slot")
    require_workspace()
    ctx = open_context(click_ctx)
    _known(ctx, repo)
    with between_ticks(ctx, "remove-slot"):
        found = find(ctx, repo, slot)
        try:
            kept = found.pool.destroy(found.slot.path)
        except pools.PoolError as e:
            raise CliError(f"{repo}'s pool: {e}") from e
    if kept is not None:
        raise CliError(f"{repo}'s pool kept slot {found.slot.name}: {kept}")
    click.echo(f"{repo}: removed slot {found.slot.name} ({found.slot.path})")
    return 0


def holders(conn: sqlite3.Connection) -> dict[str, str]:
    """What running in the journal holds each lease, by lease id: a ticket's run, a review, or a task's run.

    Returns:
        How each holder is named, such as `run:12 of PROJ-1`, by the lease id it holds.
    """
    held: dict[str, str] = {}
    running = {int(r["id"]): str(r["ticket_key"]) for r in db.running_runs(conn, "runs")}
    for run_id, slots in db.all_run_slots(conn, list(running)).items():
        held |= {s.lease_id: f"run:{run_id} of {running[run_id]}" for s in slots}
    for review in db.running_runs(conn, "review_runs"):
        if review["lease_id"]:
            held[str(review["lease_id"])] = f"review:{review['id']} of {review['pr_url']}"
    for run in tasks.running(conn):
        held[run.lease_id] = f"task:{run.task_id}#{run.id}"
    return held


def find(ctx: Context, repo: str, slot: str) -> Found:
    """Find the slot of `repo`'s pools that `slot` names, by its number or its path.

    Returns:
        The slot and its pool.

    Raises:
        CliError: The pool `pools.backend` names could not be read, no slot is named so, or a number names a slot in
            each pool.
    """
    found: list[Found] = []
    unread: list[str] = []
    for kind, pool_ in pools_of(ctx, repo):
        try:
            slots = pool_.status()
        except pools.PoolError as e:
            if kind is ctx.config.pools.backend:
                raise CliError(f"{repo}'s pool: {e}") from e
            unread.append(f"; {_pool_name(kind)} could not be read: {e}")
            continue
        found += [Found(kind, pool_, s) for s in slots if _names(slot, s)]
    match found:
        case []:
            raise CliError(f"{repo}'s pool has no slot {slot}{''.join(unread)}")
        case [one]:
            return one
        case _:
            paths = " or ".join(str(f.slot.path) for f in found)
            raise CliError(f"slot {slot} names a slot in each of {repo}'s pools; name it by its path, {paths}")


def pools_of(ctx: Context, repo: str) -> list[tuple[PoolKind, pools.Pool]]:
    """`repo`'s pools: the one `pools.backend` names, then the other's, where the workspace still has one.

    Returns:
        Each pool, with the backend that makes it.
    """
    backend = ctx.config.pools.backend
    found: list[tuple[PoolKind, pools.Pool]] = [(backend, ctx.pool(repo))]
    match backend:
        case PoolKind.TREEHOUSE:
            other, there = PoolKind.CANOPY, (ctx.workspace.root / pool.POOLS_DIR / repo).is_dir()
        case PoolKind.CANOPY:
            other, there = PoolKind.TREEHOUSE, (ctx.workspace.root / workspace.POOLS_DIR).is_dir()
        case unknown:
            assert_never(unknown)
    if there:
        found.append((other, ctx.pool_of(other, repo)))
    return found


def _refuse_inside_run(command: str) -> None:
    """Refuse inside one of canopy's ticks or runs: a slot is the operator's to free, and the tick lock its own."""
    try:
        conversation.check_operator()
    except conversation.Refused as r:
        raise CliError(f"{command} refused ({r.guard}): {r.reason}") from None


def _known(ctx: Context, repo: str) -> None:
    if ctx.workspace.repo(repo) is None:
        raise CliError(f"the map lists no repository {repo}")


def _names(arg: str, slot: pools.Slot) -> bool:
    """Whether `arg`, a slot's number or a path to it, names `slot`."""
    if arg == slot.name:
        return True
    if os.sep not in arg:
        return False
    given = Path(arg).absolute()
    return slot.path in {given, given.resolve()}


def _unreleasable(slot: pools.Slot, held: Mapping[str, str]) -> str:
    """Why release leaves `slot`, which no failed seeding holds and whose lease, if any, something still holds.

    Returns:
        A clause naming what holds the slot, or saying nothing does.
    """
    if slot.lease_id in held:
        return (
            f"is held by {held[slot.lease_id]}, still running; its lease goes back when it ends, or at the next tick "
            "if its process is gone"
        )
    if slot.lease_holder == pools.SYNC_HOLDER:
        return f"is held by {pools.SYNC_HOLDER}, a sync that did not finish; `canopy workspace sync` returns it"
    if slot.lease_holder:
        return f"is held by {slot.lease_holder}, which is not canopy's"
    return f"is {slot.status}, and nothing holds it"


def _read(ctx: Context, repo: workspace.Repo, held: Mapping[str, str]) -> list[dict[str, Any]]:
    """Each of `repo`'s pools as `slots` reports it: its slots, or why they could not be read.

    Returns:
        One entry per pool, the one `pools.backend` names first.
    """
    backend = ctx.config.pools.backend
    declared = ctx.config.capacity.slots_for(repo.name)
    if not repo.cloned:
        return [_entry(repo.name, backend, declared, backend=True, error=_NO_CLONE)]
    entries: list[dict[str, Any]] = []
    read: list[tuple[PoolKind, Sequence[pools.Slot]]] = []
    for kind, pool_ in pools_of(ctx, repo.name):
        try:
            read.append((kind, pool_.status()))
        except pools.PoolError as e:
            entries.append(_entry(repo.name, kind, declared, backend=kind is backend, error=str(e)))
    # A number two pools share is ambiguous to `release` and `remove-slot`, so a note names that slot by its path.
    counts: dict[str, int] = {}
    for _, slots in read:
        for s in slots:
            counts[s.name] = counts.get(s.name, 0) + 1
    rows = {r.path: r for r in records.select(records.PoolSlot).where("repo = ?", repo.name).all(ctx.conn)}
    for kind, slots in read:
        listed = [
            _slot(
                repo.name,
                kind,
                s,
                held,
                rows.get(str(s.path)) if kind is PoolKind.CANOPY else None,
                ref=s.name if counts[s.name] == 1 else str(s.path),
            )
            for s in slots
        ]
        entries.append(_entry(repo.name, kind, declared, backend=kind is backend, slots=listed))
    entries.sort(key=lambda e: not e["backend"])
    return entries


def _entry(
    repo: str,
    kind: PoolKind,
    declared: int | None,
    *,
    backend: bool,
    slots: Sequence[dict[str, Any]] = (),
    error: str | None = None,
) -> dict[str, Any]:
    """One pool as `slots` reports it; `backend` says whether `pools.backend` names it, and so leases from it.

    Returns:
        The pool's repository, backend, declared size, and slots, or why they could not be read.
    """
    return {
        "repo": repo,
        "pool": kind.value,
        "backend": backend,
        "declared": declared,
        "error": error,
        "slots": list(slots),
    }


def _slot(
    repo: str,
    kind: PoolKind,
    slot: pools.Slot,
    held: Mapping[str, str],
    row: records.PoolSlot | None,
    *,
    ref: str,
) -> dict[str, Any]:
    """One slot as `slots` reports it, with what holds its lease and, under canopy's pool, its row's base and seeds.

    Returns:
        The slot's fields, its holder in the journal, and a note when it waits on the operator.
    """
    holder = held.get(slot.lease_id) if slot.lease_id else None
    return {
        "name": slot.name,
        "path": str(slot.path),
        "status": slot.status,
        "branch": slot.branch,
        "detached": slot.detached,
        "lease_id": slot.lease_id,
        "lease_holder": slot.lease_holder,
        "leased_at": slot.leased_at,
        "held_by": holder,
        "processes": [{"pid": p.pid, "name": p.name} for p in slot.processes],
        "base": row.base if row is not None else None,
        "seeded": json.loads(row.seeded) if row is not None else None,
        "note": None if holder is not None else _note(repo, kind, slot, ref),
    }


def _note(repo: str, kind: PoolKind, slot: pools.Slot, ref: str) -> str | None:
    """What frees a slot nothing running holds, when it waits on the operator or on the next tick or sync.

    Returns:
        The note, or None for a slot that needs nothing.
    """
    if slot.lease_holder == pools.QUARANTINED:
        return (
            "a failed seeding holds it, counted as busy: remove the file seeding collided with, then "
            f"`canopy workspace release {repo} {ref}`"
        )
    if slot.lease_id and slot.lease_holder == pools.SYNC_HOLDER:
        return "held by a sync that did not finish; the next `canopy workspace sync` returns it"
    if slot.lease_id and slot.canopy_key is not None:
        return (
            f"no running run holds this lease; `canopy workspace release {repo} {ref}` returns it now, as the next "
            "tick would"
        )
    if slot.status == pool.DIRTY:
        return (
            "has changes, so it is never reused and counts as busy: keep what you need, then discard them in the slot"
        )
    if slot.status == pool.DAMAGED and kind is PoolKind.CANOPY and not slot.lease_holder and not slot.path.exists():
        return f"its directory is gone; `canopy workspace remove-slot {repo} {ref}` forgets it"
    return None


def _render(entry: Mapping[str, Any], root: Path) -> list[str]:
    """`slots`'s lines for one pool: a heading, then a line per slot and its note.

    Returns:
        The lines.
    """
    name = _pool_name(PoolKind(entry["pool"]))
    if entry["error"] is not None:
        return [f"{entry['repo']}: {name}: {printable(entry['error'])}"]
    slots: Sequence[Mapping[str, Any]] = entry["slots"]
    count = f"{len(slots)} slot{'' if len(slots) == 1 else 's'}"
    if not entry["backend"]:
        count += "; pools.backend names the other, so this one only takes back its leases"
    elif entry["declared"] is not None:
        count += f" of {entry['declared']} declared"
    lines = [f"{entry['repo']}: {name}, {count}"]
    for s in slots:
        lines += _slot_lines(s, root)
    return lines


def _slot_lines(slot: Mapping[str, Any], root: Path) -> list[str]:
    """One slot's line, then what seeding wrote in it and its note, if any.

    Process and file names are the machine's and the workers' text, so each is printed without control characters.

    Returns:
        The lines.
    """
    parts = [slot["name"], slot["status"]]
    if slot["lease_holder"]:
        hold = printable(slot["lease_holder"])
        if slot["held_by"]:
            hold += f" ({printable(slot['held_by'])})"
        if slot["leased_at"]:
            hold += f", since {slot['leased_at']}"
        parts.append(hold)
    if slot["processes"]:
        shown = ", ".join(f"{one_line(printable(p['name']))} ({p['pid']})" for p in slot["processes"][:PROCESSES])
        more = len(slot["processes"]) - PROCESSES
        parts.append(f"in use by {shown}" + (f" and {more} more" if more > 0 else ""))
    parts.append(_shown(slot["path"], root))
    lines = ["  " + "  ".join(parts)]
    if slot["seeded"]:
        lines.append(f"      seeded: {one_line(printable(', '.join(slot['seeded'])))}")
    if slot["note"]:
        lines.append(f"      {slot['note']}")
    return lines


def _pool_name(kind: PoolKind) -> str:
    match kind:
        case PoolKind.CANOPY:
            return "canopy's pool"
        case PoolKind.TREEHOUSE:
            return "treehouse's pool"
        case unknown:
            assert_never(unknown)


def _shown(path: str, root: Path) -> str:
    """`path` from the workspace root when it is under it, else as it is."""
    try:
        return str(Path(path).relative_to(root))
    except ValueError:
        return path
