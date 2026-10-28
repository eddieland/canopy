"""Put a run's slot back the way treehouse expects it, before it is returned (DESIGN §8, §24).

A run can leave two things in a slot that host-side git must not meet: a `.git` file that points somewhere new, and a
HEAD, index, ref, or reflog that names objects only the run's object directory holds. `_run` undoes both on every exit
path, and reconcile does for a run whose `_run` is gone.

The object directory is `<state_dir>/runs/<id>.objects/`. `_run` makes it and passes it to the worker as
`CANOPY_GIT_OBJECTS`, never as git's own variables: those would reach every git the worker's tools run, so only a
sandbox wrapper sets them. An unsandboxed run leaves the directory empty, and nothing here touches its slots.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Final

from canopy.core import attachments, hostgit, plans
from canopy.infra import procs

if TYPE_CHECKING:
    from collections.abc import Mapping

    from canopy.infra import logs

OBJECTS_ENV: Final = "CANOPY_GIT_OBJECTS"
_GIT_TIMEOUT_SECONDS: Final = 300
# A worktree's own refs, kept in its own directory beside HEAD. Every other ref is shared, which a sandbox denies.
_OWN_REFS: Final = ("refs/worktree", "refs/bisect", "refs/rewritten")
_PSEUDO_REFS: Final = ("ORIG_HEAD", "FETCH_HEAD")


class GitError(Exception):
    """A git step in a slot failed."""


def objects_dir(runs_dir: Path, run_id: int) -> Path:
    """Return run `run_id`'s object directory."""
    return runs_dir / f"{run_id}.objects"


def make_objects(path: Path) -> None:
    """Make an empty object directory, readable only by the operator."""
    path.mkdir(mode=0o700, exist_ok=True)


def used(path: Path) -> bool:
    """Whether anything was written to the object directory at `path`.

    Returns:
        True when `path` is a directory with at least one entry.
    """
    return path.is_dir() and any(True for _ in path.iterdir())


def reading(runner: procs.Runner, slot: Path, objects: Path) -> dict[str, str]:
    """Return what git in `slot` needs to read the objects in `objects` as well as the slot's own: git's variables.

    Raises:
        GitError: the slot's git directory could not be found.
    """
    common = _git(runner, slot, hostgit.ENV, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return {
        **hostgit.ENV,
        "GIT_OBJECT_DIRECTORY": str(objects),
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(Path(common) / "objects"),
    }


def tidy(
    runner: procs.Runner,
    slot: Path,
    *,
    link: bytes | None,
    base: str,
    objects: Path,
    log: logs.TickAdapter,
    fields: Mapping[str, object],
) -> bool:
    """Remove a run's copies, put back the slot's `.git` file and `commondir` if changed, and move it off `objects`.

    The slot is moved off any object only `objects` holds. The plan's copy, `.canopy-plan.md` at the worktree's root,
    and the attachments' copies, `.canopy-attachments/`, are written for one run alone (DESIGN §22, §25); git ignores
    them, so nothing else would remove them before the next lease.

    The slot is checked out detached at `origin/<base>`, which `_run` fetched into the shared directory before the
    worker started and a sandboxed worker cannot move. Its own refs, `ORIG_HEAD`, `FETCH_HEAD`, and its HEAD reflog,
    which may name the worker's objects, are dropped. Nothing shared is touched: not a branch, not another reflog.

    Returns:
        Whether the slot may be returned. treehouse runs git in a slot it takes back, so one this could not put back
        is left leased, and the object directory kept, for the operator.
    """
    _drop_copy(slot, log, fields)
    _drop_attachments(slot, log, fields)
    if link is not None and hostgit.read_link(slot) != link:
        try:
            hostgit.restore_link(slot, link)
        except OSError as e:
            failed = {**fields, "error": str(e)}
            log.error("slot's .git link changed and was not put back; slot kept", extra=failed)  # noqa: TRY400
            return False
        log.warning("slot's .git link changed during the run; put back", extra=dict(fields))
    if link is not None and hostgit.commondir_moved(slot, link):
        try:
            hostgit.restore_commondir(slot, link)
        except OSError as e:
            failed = {**fields, "error": str(e)}
            log.error("slot's commondir changed and was not put back; slot kept", extra=failed)  # noqa: TRY400
            return False
        log.warning("slot's commondir changed during the run; put back", extra=dict(fields))
    if not used(objects):
        return True
    try:
        env = reading(runner, slot, objects)
        _git(runner, slot, env, "checkout", "--quiet", "--detach", "--force", f"refs/remotes/origin/{base}")
        own = _git(runner, slot, env, "for-each-ref", "--format=%(refname)", *_OWN_REFS).split()
        for ref in [*own, *_PSEUDO_REFS]:
            _git(runner, slot, env, "update-ref", "-d", ref, check=False)
        _git(runner, slot, env, "reflog", "expire", "--expire=now", "--expire-unreachable=now", "HEAD")
    except GitError as e:
        failed = {**fields, "error": str(e)}
        log.error("slot names the run's own objects and was not moved off them; slot kept", extra=failed)  # noqa: TRY400
        return False
    log.info("slot moved off the run's own objects", extra=dict(fields))
    return True


def _drop_copy(slot: Path, log: logs.TickAdapter, fields: Mapping[str, object]) -> None:
    """Remove the plan's copy at the slot's root, never following a link: a link is removed, not what it names."""
    try:
        (slot / plans.COPY).unlink(missing_ok=True)
    except OSError as e:
        # A directory a worker made in its place: it holds no plan canopy wrote, and the next copy refuses it.
        log.warning("plan copy not removed", extra={**fields, "error": str(e)})


def _drop_attachments(slot: Path, log: logs.TickAdapter, fields: Mapping[str, object]) -> None:
    """Remove the attachments' copies at the slot's root, written for one run alone (§22), never following a link."""
    try:
        attachments.clear(slot / attachments.RUN_DIR)
    except OSError as e:
        # The next run's copies are written afresh, whatever is left here.
        log.warning("attachments' copies not removed", extra={**fields, "error": str(e)})


def remove_objects(path: Path, log: logs.TickAdapter) -> None:
    """Delete an object directory, never following a link in it."""
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        return
    except OSError as e:
        log.error("run's object directory not removed", extra={"path": str(path), "error": str(e)})  # noqa: TRY400


def _git(runner: procs.Runner, slot: Path, env: Mapping[str, str], *args: str, check: bool = True) -> str:
    try:
        result = runner.run(hostgit.argv(*args), cwd=slot, env=env, timeout=_GIT_TIMEOUT_SECONDS)
    except procs.ProcError as e:
        raise GitError(f"git {args[0]}: {e}") from e
    if check and not result.ok:
        detail = (result.stderr.strip() or result.stdout.strip() or ("timed out" if result.timed_out else ""))[:500]
        raise GitError(f"git {args[0]} exited {result.returncode}: {detail}")
    return result.stdout.strip()
