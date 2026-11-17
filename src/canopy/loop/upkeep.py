"""The pools' upkeep a live tick runs once it started its runs (DESIGN §26): at most one job a tick, when one is due.

Two kinds, each recorded in `upkeep_runs`:

- `pack`, `canopy gc --git`'s maintenance in a repository's primary clone (`loop.git_gc`), while `pools.git_maintenance`
  is on, no slot of its pools is leased, and git counts more than `pools.git_max_packs` packs or `git_max_loose` loose
  objects there. A clone is looked at once in `git_every_hours`: one under both is recorded `skipped`, so the next look
  waits as long, and a clone whose pool is busy is looked at again next tick.
- `idle`, the operator's `pools.idle_cmd` for a repository, in a slot of its pool not leased now that has been idle
  `idle_after_days`: since the end of the newest lease the journal records on it, or the slot directory's last change,
  whichever is later, so a lease canopy did not record that changed the checkout counts too. Once each idle spell, and
  again `idle_after_days` after one that failed.

It runs after the tick's spawn, so each slot this tick dispatched to is leased, and takes the dispatch lock without
waiting: while another holds it, as `canopy gc --git` by hand may, the tick runs none. A lease waits on the lock for
the job, as it does for `--git`, as long as the job's timeout at most. A job that fails is logged and recorded, and
raises `upkeep_failed` (`failed_items`) until a newer run in its clone or slot does not; it never fails the tick.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, assert_never

from canopy.core import db, pools, sandboxing, upkeep_runs
from canopy.core.config import setup_words
from canopy.core.vocab import UpkeepKind, UpkeepStatus
from canopy.infra import lock, procs
from canopy.loop import attention, gc, git_gc
from canopy.runs import worker

if TYPE_CHECKING:
    from collections.abc import Mapping

    from canopy.core import workspace
    from canopy.core.context import Context
    from canopy.infra import logs

#: The attention item a run of the upkeep that failed raises, about its repository.
REASON = attention.UPKEEP_FAILED
#: The statuses of a slot `idle_cmd` may run in: treehouse's and canopy's for a slot no lease holds and no process uses.
IDLE_STATUSES = frozenset({"available", "dirty"})
#: The most of a command's output a failure's detail keeps.
_MAX_OUTPUT = 500


@dataclass(frozen=True)
class FailedItem:
    """An `upkeep_failed` item: the repository, and what failed in its clone or slots."""

    repo: str
    detail: str


def run(ctx: Context, tick_id: int, log: logs.TickAdapter) -> None:
    """Run the one upkeep job due now, if any, under the dispatch lock, unless another process holds it.

    What raises is logged, and the tick goes on.
    """
    now = datetime.now(UTC)
    try:
        with lock.hold(ctx.dispatch_lock_path):
            _one(ctx, tick_id, now, log)
    except lock.LockBusyError:
        log.info("upkeep waits: another process holds the dispatch lock")
    except Exception as e:
        log.exception("upkeep failed", extra={"error": str(e)})


def failed_items(ctx: Context) -> list[FailedItem]:
    """An `upkeep_failed` item for each repository whose clone's or slot's newest upkeep failed.

    A slot's is left out once its repository has no `idle_cmd`, or the slot is gone; a clone's once the map no longer
    lists its repository.

    Returns:
        One item per repository, its failures joined, in the order they failed.
    """
    pools_config = ctx.config.pools
    found: dict[str, list[str]] = {}
    for failed in upkeep_runs.failed(ctx.conn):
        repo = ctx.workspace.repo(failed.repo)
        if repo is None:
            continue
        at = failed.started_at[:16].replace("T", " ")
        match failed.kind:
            case UpkeepKind.PACK:
                again = (
                    f"the loop tries again in {pools_config.git_every_hours} hours while its pool is idle"
                    if pools_config.git_maintenance
                    else "run `canopy gc --git` again"
                )
                text = f"git maintenance in {repo.path} failed at {at} UTC: {failed.detail}; {again}"
            case UpkeepKind.IDLE:
                if repo.name not in pools_config.idle_cmd or failed.slot_path is None:
                    continue
                if not _is_dir(failed.slot_path):
                    continue
                text = (
                    f"pools.idle_cmd failed in {failed.slot_path} at {at} UTC: {failed.detail}; the loop tries "
                    f"again {pools_config.idle_after_days} days after, while the slot stays idle"
                )
            case unknown:
                assert_never(unknown)
        found.setdefault(repo.name, []).append(text)
    return [FailedItem(repo, "; ".join(texts)[:2000]) for repo, texts in found.items()]


def _one(ctx: Context, tick_id: int, now: datetime, log: logs.TickAdapter) -> None:
    """Run the first job due: a clone's git maintenance, then a slot's `idle_cmd`, the caller holding the lock."""
    if ctx.config.pools.git_maintenance:
        for repo in ctx.workspace.repos:
            if repo.cloned and _git(ctx, tick_id, repo, now, log):
                return
    for repo in ctx.workspace.repos:
        if repo.name in ctx.config.pools.idle_cmd and repo.cloned and _idle(ctx, tick_id, repo, now, log):
            return


def _git(ctx: Context, tick_id: int, repo: workspace.Repo, now: datetime, log: logs.TickAdapter) -> bool:
    """Pack `repo`'s primary clone when its look is due, git counts past a threshold there, and its pool is idle.

    A clone under both thresholds is recorded `skipped`, which is quick, so the caller looks at the next.

    Returns:
        Whether it ran git's maintenance, so the tick runs no other job.
    """
    every = timedelta(hours=ctx.config.pools.git_every_hours)
    last = upkeep_runs.latest(ctx.conn, UpkeepKind.PACK, repo.name)
    if last is not None and db.parse_time(last.started_at) > now - every:
        return False
    counts = gc.count_objects(ctx.runner, repo.path)
    if counts is None:
        return False
    if not _crossed(ctx, counts):
        detail = f"{git_gc.objects(counts)}, within pools.git_max_packs and git_max_loose"
        git_gc.record(ctx, git_gc.Maintained(repo.name, "skipped", detail), tick_id=tick_id, started_at=now)
        return False
    try:
        if git_gc.leased(ctx, repo):
            return False
    except pools.PoolError as e:
        log.warning("upkeep could not read a pool", extra={"repo": repo.name, "error": str(e)})
        return False
    done = git_gc.maintain_one(ctx, repo)
    git_gc.record(ctx, done, tick_id=tick_id, started_at=now)
    log.info("git maintenance", extra={"repo": repo.name, "outcome": done.outcome, "detail": done.detail})
    return True


def _crossed(ctx: Context, counts: Mapping[str, int]) -> bool:
    """Whether `git count-objects -v`'s `counts` are past `pools.git_max_packs` or `git_max_loose`.

    Returns:
        True when either is.
    """
    limits = ctx.config.pools
    return counts.get("packs", 0) > limits.git_max_packs or counts.get("count", 0) > limits.git_max_loose


def _idle(ctx: Context, tick_id: int, repo: workspace.Repo, now: datetime, log: logs.TickAdapter) -> bool:
    """Run `repo`'s `idle_cmd` in the first slot of its pools idle long enough that it has not run in this spell.

    Returns:
        Whether it ran the command, so the tick runs no other job.
    """
    try:
        slots = [s for p in git_gc.pools_of(ctx, repo) for s in p.status()]
    except pools.PoolError as e:
        log.warning("upkeep could not read a pool", extra={"repo": repo.name, "error": str(e)})
        return False
    after = timedelta(days=ctx.config.pools.idle_after_days)
    leased = upkeep_runs.last_leased(ctx.conn)
    for slot in slots:
        if slot.lease_holder or slot.status not in IDLE_STATUSES:
            continue
        if _due(ctx, repo.name, slot.path, leased, now=now, after=after):
            _run_idle(ctx, tick_id, repo.name, slot.path, now=now, log=log)
            return True
    return False


def _due(
    ctx: Context,
    repo: str,
    path: Path,
    leased: Mapping[str, str],
    *,
    now: datetime,
    after: timedelta,
) -> bool:
    """Whether `idle_cmd` is due in the slot at `path`: idle `after`, and not yet run since, or failed `after` ago.

    Returns:
        True when it is.
    """
    since = _idle_since(path, leased.get(str(path)))
    if since is None:
        return False
    last = upkeep_runs.latest(ctx.conn, UpkeepKind.IDLE, repo, str(path))
    # Its end, not its start: the command may change the slot's directory, as `bazel clean` removes its links.
    if last is not None and db.parse_time(last.ended_at) >= since:
        return last.status == UpkeepStatus.FAILED and db.parse_time(last.started_at) <= now - after
    return since <= now - after


def _idle_since(path: Path, leased_at: str | None) -> datetime | None:
    """When the slot at `path` was last used: its newest recorded lease, or its directory's last change if later.

    Returns:
        That time, or None when the directory is gone.
    """
    try:
        changed = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    except OSError:
        return None
    if leased_at is None:
        return changed
    return max(changed, db.parse_time(leased_at))


def _run_idle(ctx: Context, tick_id: int, repo: str, path: Path, *, now: datetime, log: logs.TickAdapter) -> None:
    """Run `repo`'s `idle_cmd` in the slot at `path`, and record how it ended."""
    minutes = ctx.config.pools.idle_timeout_minutes
    argv = sandboxing.wrap(ctx.config.runtime, [repo], "setup", setup_words(ctx.config.pools.idle_cmd[repo]))
    log.info("running idle_cmd", extra={"repo": repo, "cmd": argv[0] if argv else "", "cwd": str(path)})
    status, detail = UpkeepStatus.FAILED, ""
    if not argv:
        status, detail = UpkeepStatus.SKIPPED, "pools.idle_cmd is empty"
    else:
        try:
            result = ctx.runner.run(argv, cwd=path, env={worker.SETUP_REPO_ENV: repo}, timeout=minutes * 60)
        except procs.ProcError as e:
            detail = f"it could not start: {e}"
        else:
            if result.ok:
                status, detail = UpkeepStatus.DONE, "exited 0"
            else:
                ended = f"timed out after {minutes} minutes" if result.timed_out else f"exited {result.returncode}"
                output = (result.stderr.strip() or result.stdout.strip())[-_MAX_OUTPUT:]
                detail = f"{ended}: {output}" if output else ended
    upkeep_runs.record(
        ctx.conn,
        tick_id=tick_id,
        kind=UpkeepKind.IDLE,
        repo=repo,
        slot_path=str(path),
        started_at=now,
        status=status,
        detail=detail,
    )
    log.info("idle_cmd ran", extra={"repo": repo, "slot": str(path), "status": status, "detail": detail})


def _is_dir(path: str) -> bool:
    """Whether `path` is a directory now.

    Returns:
        False when it is not, or cannot be read.
    """
    try:
        return Path(path).is_dir()
    except OSError:
        return False
