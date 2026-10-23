"""`canopy gc --git`: loose objects packed and small packs combined in each primary clone (DESIGN §26).

git's automatic maintenance is off in every primary clone (DESIGN §18), so their objects only grow. This runs the two
maintenance tasks that delete no object a pack does not also hold, and so prune nothing a slot may still read:
`loose-objects`, which packs loose objects and drops the loose copies of packed ones, and `incremental-repack`, which
combines small packs. Each runs as its own `git maintenance run`, since git's run of both refuses a clone with no pack
yet; `prune-packed` after them drops what `loose-objects` just packed, which git's own task leaves to its next run.

A repository runs under the dispatch lock, which every lease takes, and only when no slot of its pools is leased, so
no run, review, or task starts or works in a slot while its git directory is repacked. A dispatch waits for it. The
loop never runs it on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, assert_never

from canopy.core import hostgit, pool, pools, workspace
from canopy.core.vocab import PoolKind
from canopy.infra import lock, logs, procs
from canopy.loop import gc

if TYPE_CHECKING:
    from collections.abc import Iterator

    from canopy.core.context import Context

#: What maintenance came to in one repository.
Outcome = Literal["packed", "skipped", "failed"]

#: The step that combines packs, which git refuses in a clone with no pack, as an empty repository's is.
REPACK = ("maintenance", "run", "--quiet", "--task=incremental-repack")
#: The steps in each clone, in order: none deletes an object that is not also in a pack.
STEPS = (("maintenance", "run", "--quiet", "--task=loose-objects"), REPACK, ("prune-packed", "--quiet"))
_STEP_TIMEOUT_SECONDS = 3600
_REV_PARSE_TIMEOUT_SECONDS = 30
_MAINTENANCE_LOCK = "objects/maintenance.lock"


@dataclass(frozen=True)
class Maintained:
    """What `--git` did in one repository's primary clone."""

    repo: str
    outcome: Outcome
    #: What to tell the operator: the objects before and after, why it was skipped, or why git failed.
    detail: str


def maintain(ctx: Context) -> list[Maintained]:
    """Pack each primary clone's loose objects and combine its small packs, skipping one with a leased slot.

    Returns:
        What it came to in each repository the map lists, in the map's order.
    """
    log = logs.for_tick(None)
    done: list[Maintained] = []
    for repo in ctx.workspace.repos:
        if not repo.cloned:
            done.append(Maintained(repo.name, "skipped", f"no primary clone at {repo.path}"))
            continue
        with lock.hold(ctx.dispatch_lock_path, wait=True):
            result = _maintain(ctx, repo)
        log.info(
            "git maintenance",
            extra={"repo": repo.name, "outcome": result.outcome, "detail": result.detail},
        )
        done.append(result)
    return done


def _maintain(ctx: Context, repo: workspace.Repo) -> Maintained:
    """Run `STEPS` in `repo`'s primary clone, the caller holding the dispatch lock.

    Returns:
        `packed` with the objects before and after, `skipped` when a slot is leased, or `failed` with why.
    """
    try:
        leased = [s.name for p in _pools(ctx, repo) for s in p.status() if s.lease_holder]
    except pools.PoolError as e:
        return Maintained(repo.name, "failed", f"its pool could not say which slots are leased: {e}")
    if leased:
        return Maintained(repo.name, "skipped", f"slot {', '.join(leased)} is leased; run it again once none is")
    held = _maintenance_lock(ctx.runner, repo.path)
    if held is not None:
        # git skips a run whose lock another holds, and exits 0 saying nothing.
        why = f"{held} is held: git's own maintenance runs there, or a dead one left it"
        return Maintained(repo.name, "skipped", why)
    before = gc.count_objects(ctx.runner, repo.path)
    for step in STEPS:
        if step == REPACK and not (gc.count_objects(ctx.runner, repo.path) or {}).get("packs"):
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
    after = gc.count_objects(ctx.runner, repo.path)
    return Maintained(repo.name, "packed", f"{_objects(before)} before, {_objects(after)} after")


def _maintenance_lock(runner: procs.Runner, clone: Path) -> Path | None:
    """The lock `git maintenance run` takes in `clone`'s git directory, if a file is there.

    Returns:
        The lock file's path, or None when it is not there or git cannot say where it would be.
    """
    try:
        result = runner.run(
            hostgit.argv("rev-parse", "--path-format=absolute", "--git-path", _MAINTENANCE_LOCK),
            cwd=clone,
            env=hostgit.ENV,
            timeout=_REV_PARSE_TIMEOUT_SECONDS,
        )
    except procs.ProcError:
        return None
    path = Path(result.stdout.strip())
    return path if result.ok and path.exists() else None


def _pools(ctx: Context, repo: workspace.Repo) -> Iterator[pools.Pool]:
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


def _objects(counts: dict[str, int] | None) -> str:
    """`git count-objects -v`'s numbers as the operator reads them.

    Returns:
        The loose objects and the packs, or `unknown` when git could not count them.
    """
    if counts is None:
        return "unknown"
    return f"{counts.get('count', 0)} loose objects ({counts.get('size', 0)} KiB) and {counts.get('packs', 0)} packs"
