"""`canopy gc --git`: loose objects packed and small packs combined in each primary clone (DESIGN §26).

git's automatic maintenance is off in every primary clone (DESIGN §18), so their objects only grow. This runs the two
maintenance tasks that delete no object a pack does not also hold, and so prune nothing a slot may still read:
`loose-objects`, which packs loose objects and drops the loose copies of packed ones, and `incremental-repack`, which
combines small packs. Each runs as its own `git maintenance run`, since git's run of both refuses a clone with no pack
yet; `prune-packed` after them drops what `loose-objects` just packed, which git's own task leaves to its next run.

A partial clone (`clone_filter`) combines no packs, nor a clone whose config git cannot read. A partial clone's fetched
packs are promisor packs, whose objects may name blobs it never fetched; `incremental-repack` merges them into a pack
with no promisor mark, so git no longer counts those blobs as promised and `git fsck` finds the clone broken, which no
later `git gc` repairs. Its loose objects are its own, never promised, so packing them changes nothing git checks.

It also removes what an interrupted fetch or clone left in the pack directory, `tmp_pack_*` and `tmp_idx_*` files a day
old, which git counts as garbage and never removes.

A repository runs under the dispatch lock, which every lease takes, and only when no slot of its pools is leased, so
no run, review, or task starts or works in a slot while its git directory is repacked. A dispatch waits for it. Each
run is recorded in `upkeep_runs`; a live tick runs one repository's on its own while its pool is idle (`loop.upkeep`).
"""

from __future__ import annotations

import stat
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, assert_never

from canopy.core import hostgit, pool, pools, upkeep_runs, workspace
from canopy.core.vocab import PoolKind, UpkeepKind, UpkeepStatus
from canopy.infra import lock, logs, procs
from canopy.loop import gc

if TYPE_CHECKING:
    from collections.abc import Iterator

    from canopy.core.context import Context

#: What maintenance came to in one repository.
type Outcome = Literal["packed", "skipped", "failed"]

#: The step that combines packs, which git refuses in a clone with no pack, as an empty repository's is.
REPACK: Final = ("maintenance", "run", "--quiet", "--task=incremental-repack")
#: The steps in each clone, in order: none deletes an object that is not also in a pack.
STEPS: Final = (("maintenance", "run", "--quiet", "--task=loose-objects"), REPACK, ("prune-packed", "--quiet"))
_STEP_TIMEOUT_SECONDS: Final = 3600
_REV_PARSE_TIMEOUT_SECONDS: Final = 30
_CONFIG_TIMEOUT_SECONDS: Final = 30
#: The config that makes a clone partial: a promisor remote, as `git clone --filter` names it, or the older extension.
_PARTIAL_KEYS: Final = r"^(extensions\.partialclone|remote\..+\.promisor)$"
#: The values git reads as false; a key with no value is true.
_FALSE: Final = frozenset({"false", "no", "off", "0", ""})
_MAINTENANCE_LOCK: Final = "objects/maintenance.lock"
_PACK_DIR: Final = "objects/pack"
#: The temporary files a fetch or clone writes in the pack directory, and leaves when it is interrupted.
_TEMP_PACKS: Final = ("tmp_pack_*", "tmp_idx_*")
#: How old a temporary pack file must be to be removed: no fetch the harness runs takes that long.
STALE_TEMP: Final = timedelta(days=1)
#: Each outcome as the journal records it.
STATUS: Final[dict[Outcome, UpkeepStatus]] = {
    "packed": UpkeepStatus.DONE,
    "skipped": UpkeepStatus.SKIPPED,
    "failed": UpkeepStatus.FAILED,
}
#: Why a partial clone's packs are left as they are, as the operator reads it.
PARTIAL: Final = (
    "it is a partial clone, whose promisor packs git's incremental-repack would merge into one git no longer trusts "
    "to name blobs it never fetched"
)
#: Why a clone's packs are left as they are when git cannot read its config.
UNREAD: Final = "git could not read its config to tell whether it is a partial clone"


@dataclass(frozen=True)
class Maintained:
    """What `--git` did in one repository's primary clone."""

    repo: str
    outcome: Outcome
    #: What to tell the operator: the objects before and after, why it was skipped, or why git failed.
    detail: str


def maintain(ctx: Context) -> list[Maintained]:
    """Pack each primary clone's loose objects and combine its small packs, skipping one with a leased slot.

    Each repository with a clone is recorded in `upkeep_runs` as a run by hand.

    Returns:
        What it came to in each repository the map lists, in the map's order.
    """
    log = logs.for_tick(None)
    done: list[Maintained] = []
    for repo in ctx.workspace.repos:
        if not repo.cloned:
            done.append(Maintained(repo.name, "skipped", f"no primary clone at {repo.path}"))
            continue
        started = datetime.now(UTC)
        with lock.hold(ctx.dispatch_lock_path, wait=True):
            result = maintain_one(ctx, repo)
        record(ctx, result, tick_id=None, started_at=started)
        log.info(
            "git maintenance",
            extra={"repo": repo.name, "outcome": result.outcome, "detail": result.detail},
        )
        done.append(result)
    return done


def maintain_one(ctx: Context, repo: workspace.Repo) -> Maintained:
    """Run `STEPS` in `repo`'s primary clone, the caller holding the dispatch lock, unless a slot of it is leased.

    A partial clone's packs are left as they are, and its detail says so.

    Returns:
        `packed` with the objects before and after, `skipped` when a slot is leased, or `failed` with why.
    """
    try:
        held = leased(ctx, repo)
    except pools.PoolError as e:
        return Maintained(repo.name, "failed", f"its pool could not say which slots are leased: {e}")
    if held:
        return Maintained(repo.name, "skipped", f"slot {', '.join(held)} is leased; run it again once none is")
    busy = _maintenance_lock(ctx.runner, repo.path)
    if busy is not None:
        # git skips a run whose lock another holds, and exits 0 saying nothing.
        why = f"{busy} is held: git's own maintenance runs there, or a dead one left it"
        return Maintained(repo.name, "skipped", why)
    keep_packs = _keep_packs(ctx.runner, repo.path)
    before = gc.count_objects(ctx.runner, repo.path)
    for step in STEPS:
        if step == REPACK and (keep_packs or not (gc.count_objects(ctx.runner, repo.path) or {}).get("packs")):
            continue
        try:
            result = ctx.runner.run(
                hostgit.argv(*step),
                cwd=repo.path,
                env=hostgit.ENV,
                timeout=_STEP_TIMEOUT_SECONDS,
            )
        except procs.ProcError as e:
            return Maintained(repo.name, "failed", str(e))
        if not result.ok:
            status = "timed out" if result.timed_out else f"exited {result.returncode}"
            output = (result.stderr.strip() or result.stdout.strip())[:500]
            return Maintained(repo.name, "failed", f"git {' '.join(step[:3])} {status}: {output}")
    removed = _remove_temp_packs(ctx.runner, repo.path)
    after = gc.count_objects(ctx.runner, repo.path)
    temp = f"; removed {removed} temporary pack files an interrupted fetch left" if removed else ""
    kept = f"; combined no packs: {keep_packs}" if keep_packs else ""
    return Maintained(repo.name, "packed", f"{objects(before)} before, {objects(after)} after{temp}{kept}")


def record(ctx: Context, done: Maintained, *, tick_id: int | None, started_at: datetime) -> None:
    """Record `done`, a run that started at `started_at`, in `upkeep_runs`: by hand when `tick_id` is None."""
    upkeep_runs.record(
        ctx.conn,
        tick_id=tick_id,
        kind=UpkeepKind.PACK,
        repo=done.repo,
        slot_path=None,
        started_at=started_at,
        status=STATUS[done.outcome],
        detail=done.detail,
    )


def leased(ctx: Context, repo: workspace.Repo) -> list[str]:
    """The slots of `repo`'s pools that are leased now, by name.

    Returns:
        Their names; none when its pools are idle.

    Raises:
        PoolError: a pool could not say.
    """
    return [s.name for p in pools_of(ctx, repo) for s in p.status() if s.lease_holder]


def objects(counts: dict[str, int] | None) -> str:
    """`git count-objects -v`'s numbers as the operator reads them.

    Returns:
        The loose objects and the packs, or `unknown` when git could not count them.
    """
    if counts is None:
        return "unknown"
    return f"{counts.get('count', 0)} loose objects ({counts.get('size', 0)} KiB) and {counts.get('packs', 0)} packs"


def _maintenance_lock(runner: procs.Runner, clone: Path) -> Path | None:
    """The lock `git maintenance run` takes in `clone`'s git directory, if a file is there.

    Returns:
        The lock file's path, or None when it is not there or git cannot say where it would be.
    """
    path = _git_path(runner, clone, _MAINTENANCE_LOCK)
    return path if path is not None and path.exists() else None


def _keep_packs(runner: procs.Runner, clone: Path) -> str | None:
    """Why `clone`'s packs must not be combined: it is a partial clone, or git cannot say whether it is one.

    A partial clone's config names a promisor remote, or the older partial clone extension. When git cannot read the
    config the packs are kept too: combining a partial clone's breaks it, and leaving a full clone's costs little.

    Returns:
        Why, as the operator reads it, or None when the clone is not partial.
    """
    try:
        result = runner.run(
            hostgit.argv("config", "--get-regexp", _PARTIAL_KEYS),
            cwd=clone,
            env=hostgit.ENV,
            timeout=_CONFIG_TIMEOUT_SECONDS,
        )
    except procs.ProcError:
        return UNREAD
    # 1 is git's answer when no key is set.
    if result.timed_out or result.returncode not in {0, 1}:
        return UNREAD
    for line in result.stdout.splitlines():
        key, has_value, value = line.partition(" ")
        if key == "extensions.partialclone" or not has_value or value.strip().lower() not in _FALSE:
            return PARTIAL
    return None


def _remove_temp_packs(runner: procs.Runner, clone: Path) -> int:
    """Remove the temporary pack files in `clone`'s pack directory older than `STALE_TEMP`, regular files only.

    Returns:
        How many it removed.
    """
    pack_dir = _git_path(runner, clone, _PACK_DIR)
    if pack_dir is None:
        return 0
    cutoff = time.time() - STALE_TEMP.total_seconds()
    removed = 0
    for pattern in _TEMP_PACKS:
        for path in pack_dir.glob(pattern):
            try:
                found = path.lstat()
                if not stat.S_ISREG(found.st_mode) or found.st_mtime > cutoff:
                    continue
                path.unlink()
            except OSError:
                continue
            removed += 1
    return removed


def _git_path(runner: procs.Runner, clone: Path, name: str) -> Path | None:
    """Where `name` is in `clone`'s git directory, as `git rev-parse --git-path` says.

    Returns:
        The absolute path, or None when git cannot say.
    """
    try:
        result = runner.run(
            hostgit.argv("rev-parse", "--path-format=absolute", "--git-path", name),
            cwd=clone,
            env=hostgit.ENV,
            timeout=_REV_PARSE_TIMEOUT_SECONDS,
        )
    except procs.ProcError:
        return None
    return Path(result.stdout.strip()) if result.ok and result.stdout.strip() else None


def pools_of(ctx: Context, repo: workspace.Repo) -> Iterator[pools.Pool]:
    """`repo`'s pool, and the other backend's while the workspace still has one: a lease goes back to its own pool.

    Yields:
        Each pool that may hold a lease on a slot of `repo`'s primary clone.
    """
    yield ctx.pool(repo.name)
    match ctx.config.pools.backend:
        case PoolKind.CANOPY:
            if (ctx.repo_root / workspace.POOLS_DIR).is_dir():
                yield ctx.pool_of(PoolKind.TREEHOUSE, repo.name)
        case PoolKind.TREEHOUSE:
            if (ctx.repo_root / pool.POOLS_DIR / repo.name).is_dir():
                yield ctx.canopy_pool(repo.name)
        case unknown:
            assert_never(unknown)
