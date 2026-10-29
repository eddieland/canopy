"""canopy's own worktree pool (DESIGN §18; ROADMAP M45): git worktrees canopy makes, with their leases in the journal.

A repository's slots are `<workspace>/pools/<repo>/<N>/<repo>`, numbered from 1, each a detached worktree of the
primary clone, and each a row of the journal's `slots` table. The pool keeps every guarantee DESIGN §18 lists, as
treehouse does, and differs where the design says: no network call outside a lease's fetch, a slot's `.git` link and
`commondir` checked before any git runs in it, and the declared size, or 16 with none, as the only bound.

Everything that changes a pool holds its lock, `<workspace>/pools/<repo>/.lock`, and writes its rows in short
transactions under it: a lease claims its slot in the journal before touching the worktree, so two leases never pick
one slot, and a lease whose process dies before its run is recorded is a `canopy:` lease no running run holds, which
reconcile returns as it returns treehouse's. Every git goes through `hostgit.argv` (D107).
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import uuid
from collections.abc import Collection, Iterable, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from canopy.core import db, hostgit, records, sql
from canopy.core.pools import AVAILABLE, QUARANTINED, Lease, PoolError, Process, ReturnOutcome, Slot, holder_for
from canopy.infra import cwds, lock, procs

POOLS_DIR = "pools"
# A pool with no declared size stops here, as treehouse's default `max_trees` does.
MAX_SLOTS = 16
LOCK_NAME = ".lock"
LEASED = "leased"
IN_USE = "in-use"
DIRTY = "dirty"
DAMAGED = "damaged"
UNVERIFIED = "unverified"
# git takes no optional lock, so reading a slot's status never writes its index.
ENV = {**hostgit.ENV, "GIT_OPTIONAL_LOCKS": "0"}
_GIT_TIMEOUT_SECONDS = 300
_FETCH_TIMEOUT_SECONDS = 900
_WORKTREES = "worktrees"


@dataclass(frozen=True)
class _Want:
    """What a lease asks for.

    Its holder, the base it named (None for the default), that base's name and commit, and the operator's manifest.
    """

    holder: str
    base: str | None
    branch: str
    commit: str
    manifest: str | None


@dataclass(frozen=True)
class CanopyPool:
    """Repository `repo`'s pool in the workspace at `root`, as a `pools.Pool`.

    `clone` is the repository's primary clone. `slots` is the pool's declared size (`capacity.slots_for`), its only
    bound; None bounds it at `MAX_SLOTS`. `include_file` is the operator's own `.worktreeinclude`, read in place of
    the committed one (DESIGN §9).
    """

    runner: procs.Runner
    conn: sqlite3.Connection
    repo: str
    root: Path
    clone: Path
    slots: int | None = None
    include_file: Path | None = None

    @property
    def directory(self) -> Path:
        """Where the pool's slots are: `<workspace>/pools/<repo>`."""
        return self.root / POOLS_DIR / self.repo

    def status(self) -> list[Slot]:
        """Every slot in the pool, by name, each as canopy's own checks classify it.

        Returns:
            The slots: `leased` while one has a lease, else in-use, unverified, damaged, dirty, or available.
        """
        return [self._slot(row) for row in self._rows()]

    def lease(self, key: str, *, base: str | None = None) -> Lease:
        """Lease a slot for ticket `key`, based on `base` or the default branch, within the pool's declared size.

        With a declared size, a pool with that many slots busy refuses without making one.

        Returns:
            The leased slot.

        Raises:
            PoolError: The declared slots are all busy, none can be reused and the pool is at its bound, or the slot
                could not be fetched, reset, made, or seeded.
        """
        return self._lease(holder_for(key), base=base, fetch=True, refuse_busy=True)

    def lease_as(self, holder: str, *, base: str | None = None, fetch: bool = True) -> Lease:
        """Lease any slot for `holder`, making one if none can be reused, up to the pool's bound.

        Without `fetch`, the slot is cut from the clone's refs as they are.

        Returns:
            The leased slot.

        Raises:
            PoolError: No slot can be reused and the pool is at its bound, or the slot could not be fetched, reset,
                made, or seeded.
        """
        return self._lease(holder, base=base, fetch=fetch, refuse_busy=False)

    def return_slot(self, path: Path, *, lease_id: str, lease_holder: str) -> ReturnOutcome:
        """Return slot `path` only if it is still held under this exact lease, forced.

        The processes in the slot are ended first. The slot is reset to its lease's base as it is now, without a
        fetch, so what the run left uncommitted and every commit no branch holds is discarded, and so is what
        seeding wrote; ignored files stay. A slot whose directory is gone, or whose git link canopy cannot vouch for,
        is freed without a reset, and never reused.

        Returns:
            `RETURNED`, or `FAILED` when the slot is not this pool's, is not held under this lease, or a process in it
            outlived its signals.

        Raises:
            PoolError: The process table could not be read, or git could not reset the slot.
        """
        with self._locked():
            row = self._row(path)
            if row is None or row.lease_holder is None or (row.lease_id, row.lease_holder) != (lease_id, lease_holder):
                return ReturnOutcome.FAILED
            return self._free(path, row)

    def release(self, path: Path) -> ReturnOutcome:
        """Return slot `path` only if a failed seeding still holds it (`QUARANTINED`), as `return_slot` frees a lease.

        The operator's way to free the slot once they have looked at it (DESIGN §18). The ignored file seeding
        collided with stays, as a return keeps ignored files, so a lease that seeds it fails again until it is gone.

        Returns:
            `RETURNED`, or `FAILED` when the slot is not this pool's, is not quarantined, or a process in it outlived
            its signals.

        Raises:
            PoolError: The process table could not be read, or git could not reset the slot.
        """
        with self._locked():
            row = self._row(path)
            if row is None or row.lease_id is not None or row.lease_holder != QUARANTINED:
                return ReturnOutcome.FAILED
            return self._free(path, row)

    def destroy(self, path: Path) -> str | None:
        """Remove slot `path` if nothing in it could be lost: unleased, idle, clean, and merged.

        Merged means HEAD is an ancestor of the default branch as last fetched, or of the branch the slot was last
        leased on. Nothing is fetched. An unheld slot whose directory is gone holds nothing to lose, so its row is
        forgotten, as a lease forgets it.

        Returns:
            None when the slot is gone, else why it was kept, at most 500 characters.
        """
        with self._locked():
            row = self._row(path)
            if row is None:
                return f"{path} is not a slot of canopy's {self.repo} pool"
            if row.lease_holder is None and not path.exists() and not path.is_symlink():
                self._forget_gone(path)
                return None
            kept = self._kept(path, row)
            if kept:
                return "; ".join(kept)[:500]
            if self.clone.is_dir():
                self._git.run(self.clone, "worktree", "remove", "--force", str(path))
            container = path.parent
            if container.parent == self.directory and not container.is_symlink():
                shutil.rmtree(container, ignore_errors=True)
            with db.transaction(self.conn):
                sql.execute(self.conn, sql.delete("slots").where("path = ?", str(path)))
        return None

    def move_in(self, path: Path) -> Path:
        """Move the worktree at `path`, an idle slot of another pool of this clone, into this pool as an idle slot.

        `git worktree move` keeps everything in the slot, its ignored files too, so a switch from treehouse keeps the
        slots' build caches warm (ROADMAP M45, stage 3). The emptied directory it was in is removed.

        Returns:
            The slot's new path.

        Raises:
            PoolError: It is not a worktree of this clone canopy can vouch for, has changes or a process in it, the
                pool is at its bound, or git could not move it.
        """
        with self._locked():
            if not _sound(self.clone, path):
                raise PoolError(f"{path} is not a worktree of {self.clone} whose git link canopy can vouch for")
            if self._dirty(path):
                raise PoolError(f"{path} has changes")
            try:
                if cwds.inside(self.runner, path):
                    raise PoolError(f"{path} has a process in it")
            except cwds.CwdError as e:
                raise PoolError(str(e)) from e
            rows = self._rows()
            bound = self.slots if self.slots is not None else MAX_SLOTS
            if len(rows) >= bound:
                raise PoolError(self._full(len(rows), bound))
            number = max((int(r.name) for r in rows if r.name.isdigit()), default=0) + 1
            while (self.directory / str(number)).exists():
                number += 1
            target = self.directory / str(number) / self.repo
            target.parent.mkdir(parents=True)
            try:
                self._git.run(self.clone, "worktree", "move", str(path), str(target))
            except PoolError:
                with contextlib.suppress(OSError):
                    target.parent.rmdir()
                raise
            with db.transaction(self.conn):
                sql.execute(self.conn, sql.insert("slots", repo=self.repo, name=str(number), path=str(target)))
            with contextlib.suppress(OSError):
                path.parent.rmdir()
        return target

    def _free(self, path: Path, row: records.PoolSlot) -> ReturnOutcome:
        """Free the held slot at `path`, under the pool's lock: end its processes, reset it to its base, clear its row.

        A slot whose git link canopy cannot vouch for is freed without a reset.

        Returns:
            `RETURNED`, or `FAILED` when a process in it outlived its signals.

        Raises:
            PoolError: The process table could not be read, or git could not reset the slot.
        """
        base = row.base
        if _sound(self.clone, path):
            try:
                if cwds.end(self.runner, path):
                    return ReturnOutcome.FAILED
            except cwds.CwdError as e:
                raise PoolError(str(e)) from e
            base = self._reset_to_base(path, row)
        with db.transaction(self.conn):
            freed = sql.update("slots").set(lease_id=None, lease_holder=None, leased_at=None, base=base, seeded="[]")
            sql.execute(self.conn, freed.where("path = ?", str(path)))
        return ReturnOutcome.RETURNED

    def _lease(self, holder: str, *, base: str | None, fetch: bool, refuse_busy: bool) -> Lease:
        manifest = self._manifest_file()
        if fetch and self._git.ok(self.clone, "remote", "get-url", "origin"):
            self._git.run(self.clone, "fetch", "--quiet", "origin", timeout=_FETCH_TIMEOUT_SECONDS)
        branch = self._resolve_base(base)
        commit = _commit(self._git, self.clone, branch)
        with self._locked():
            self._heal()
            rows = self._rows()
            if refuse_busy and self.slots is not None:
                busy = sum(self._slot(r).status != AVAILABLE for r in rows)
                if busy >= self.slots:
                    raise PoolError(f"{busy} of its slots are busy, and capacity declares {self.slots} for this pool")
            want = _Want(holder, base, branch, commit, manifest)
            for row in rows:
                if row.lease_holder is None and self._reusable(row, branch, commit):
                    return self._reuse(row, want)
            return self._make(rows, want)

    def _reuse(self, row: records.PoolSlot, want: _Want) -> Lease:
        path = Path(row.path)
        _reset(self._git, path, want.commit, json.loads(row.seeded))
        lease = self._claim(path, want)
        self._seed_or_quarantine(path, want.manifest, new=False)
        return lease

    def _make(self, rows: Collection[records.PoolSlot], want: _Want) -> Lease:
        """Make a new slot, under the next free name, and lease it; or reuse a worktree left there with no row.

        Returns:
            The leased slot.

        Raises:
            PoolError: The pool is at its bound, or the worktree could not be made or seeded.
        """
        bound = self.slots if self.slots is not None else MAX_SLOTS
        count = len(rows)
        number = max((int(r.name) for r in rows if r.name.isdigit()), default=0)
        while True:
            if count >= bound:
                raise PoolError(self._full(count, bound))
            number += 1
            path = self.directory / str(number) / self.repo
            if path.parent.is_symlink():
                continue
            if not path.exists() and not path.is_symlink():
                break
            # A worktree a crashed lease made before its row: adopted as an idle slot, then reused if it can be.
            if not path.is_symlink() and _sound(self.clone, path):
                adopted = self._adopt(str(number), path)
                count += 1
                if self._reusable(adopted, want.branch, want.commit):
                    return self._reuse(adopted, want)
        lease = self._insert(str(number), path, want)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._git.run(self.clone, "worktree", "prune")
            self._git.run(self.clone, "worktree", "add", "--quiet", "--detach", str(path), want.commit)
        except (OSError, PoolError) as e:
            self._forget(path)
            raise PoolError(f"could not make slot {number}: {e}") from e
        self._seed_or_quarantine(path, want.manifest, new=True)
        return lease

    def _full(self, count: int, bound: int) -> str:
        if self.slots is not None:
            return f"no slot of the {count} could be reused, and capacity declares {self.slots} for this pool"
        return f"all {count} slots are leased, in use, dirty, or hold unmerged work, and a pool stops at {bound}"

    def _seed_or_quarantine(self, path: Path, manifest: str | None, *, new: bool) -> None:
        """Seed the leased slot at `path`; if that fails, undo what it wrote and refuse the lease.

        A new slot is removed. A reused one is held as quarantined: what made seeding fail is still in it.

        Raises:
            PoolError: seeding failed.
        """
        try:
            planned = self._plan_seed(path, manifest)
            with db.transaction(self.conn):
                seeded = sql.update("slots").set(seeded=json.dumps(planned)).where("path = ?", str(path))
                sql.execute(self.conn, seeded)
            _copy_seeds(self.clone, path, planned)
        except (OSError, PoolError) as e:
            if new:
                self._forget(path)
            else:
                with contextlib.suppress(OSError):
                    _remove_seeded(path, self._seeded(path))
                with db.transaction(self.conn):
                    held = sql.update("slots").set(lease_id=None, lease_holder=QUARANTINED, seeded="[]")
                    sql.execute(self.conn, held.where("path = ?", str(path)))
            raise PoolError(f"failed to seed {path}: {e}") from e

    def _plan_seed(self, path: Path, manifest: str | None) -> list[str]:
        """The paths seeding will write in the slot: the untracked, ignored files of the clone the manifest selects.

        Returns:
            Their paths relative to the slot, sorted.

        Raises:
            PoolError: git could not list them, the committed manifest is not a file, or one is already in the slot.
        """
        text = manifest if manifest is not None else self._committed_manifest(path)
        if not text or not text.strip():
            return []
        with tempfile.NamedTemporaryFile("w", suffix=".worktreeinclude", delete=False) as f:
            f.write(text)
        try:
            selected = self._git.z(self.clone, "ls-files", "--others", "--ignored", f"--exclude-from={f.name}")
        finally:
            Path(f.name).unlink()
        ignored = set(self._git.z(self.clone, "ls-files", "--others", "--ignored", "--exclude-standard"))
        tracked = set(self._git.z(path, "ls-files"))
        planned: list[str] = []
        for rel in sorted(set(selected) & ignored):
            parts = PurePosixPath(rel).parts
            if not parts or PurePosixPath(rel).is_absolute() or ".." in parts or _tracked(rel, tracked):
                continue
            if _lexists(path, parts):
                raise PoolError(f"{rel}: file exists")
            planned.append(rel)
        return planned

    def _committed_manifest(self, path: Path) -> str | None:
        kind = self._git.result(path, "cat-file", "-t", "HEAD:.worktreeinclude")
        if not kind.ok:
            return None
        if kind.stdout.strip() != "blob":
            raise PoolError(".worktreeinclude at the slot's HEAD is not a file")
        return self._git.run(path, "cat-file", "blob", "HEAD:.worktreeinclude")

    def _manifest_file(self) -> str | None:
        if self.include_file is None:
            return None
        try:
            return self.include_file.read_text()
        except (OSError, UnicodeDecodeError) as e:
            raise PoolError(f"failed to read include file {str(self.include_file)!r}: {e}") from e

    def _reusable(self, row: records.PoolSlot, branch: str, commit: str) -> bool:
        """Whether an unleased slot can be reset to `commit` with nothing lost, as treehouse decides (DESIGN §18).

        Returns:
            True when it is a sound worktree of this clone, idle, clean, and its HEAD is an ancestor of `commit` or of
            the branch it was last leased on.
        """
        path = Path(row.path)
        if not _sound(self.clone, path) or self._dirty(path):
            return False
        try:
            if cwds.inside(self.runner, path):
                return False
        except cwds.CwdError:
            return False
        if self._git.ok(path, "merge-base", "--is-ancestor", "HEAD", commit):
            return True
        if not row.base or row.base == branch or not _branch_exists(self._git, self.clone, row.base):
            return False
        return self._git.ok(path, "merge-base", "--is-ancestor", "HEAD", _commit(self._git, self.clone, row.base))

    def _kept(self, path: Path, row: records.PoolSlot) -> list[str]:
        """Why `destroy` keeps the slot, if anything.

        Returns:
            Each reason; empty when the slot is disposable.
        """
        kept: list[str] = []
        if row.lease_holder is not None:
            kept.append(f"leased by {row.lease_holder}")
        try:
            found = cwds.inside(self.runner, path)
        except cwds.CwdError as e:
            kept.append(f"cannot check its processes: {e}")
        else:
            if found:
                kept.append(f"in use by {', '.join(f'{f.name} ({f.pid})' for f in found)}")
        if not _sound(self.clone, path):
            kept.append("damaged: not a worktree of the clone canopy can vouch for")
            return kept
        if self._dirty(path):
            kept.append("dirty")
        default = _merge_ref(self._git, self.clone, self.repo)
        if default is None:
            kept.append("cannot tell the default branch, so cannot tell whether HEAD is merged")
        elif not self._git.ok(path, "merge-base", "--is-ancestor", "HEAD", default) and not self._landed(path, row):
            kept.append(f"HEAD is not merged into {default}")
        return kept

    def _landed(self, path: Path, row: records.PoolSlot) -> bool:
        if not row.base or not _branch_exists(self._git, self.clone, row.base):
            return False
        return self._git.ok(path, "merge-base", "--is-ancestor", "HEAD", _commit(self._git, self.clone, row.base))

    def _reset_to_base(self, path: Path, row: records.PoolSlot) -> str:
        """Reset a returned slot to its lease's base, or the default branch if that base is gone.

        Returns:
            The base it is parked on, empty for the default branch.
        """
        base = row.base
        if not base or not _branch_exists(self._git, path, base):
            base = ""
        branch = base or _default_branch(self._git, self.clone, self.repo)
        _reset(self._git, path, _commit(self._git, path, branch), json.loads(row.seeded))
        return base

    def _resolve_base(self, base: str | None) -> str:
        if base is None:
            return _default_branch(self._git, self.clone, self.repo)
        if base == "HEAD" or not _branch_exists(self._git, self.clone, base):
            raise PoolError(
                f"base branch {base!r} does not exist: no local branch {base} and no remote-tracking branch "
                f"origin/{base}",
            )
        return base

    def _dirty(self, path: Path) -> bool:
        result = self._git.result(path, "status", "--porcelain", "--untracked-files=all")
        return not result.ok or bool(result.stdout.strip())

    def _slot(self, row: records.PoolSlot) -> Slot:
        path = Path(row.path)
        found: list[cwds.Found] = []
        status = LEASED if row.lease_holder is not None else None
        try:
            found = cwds.inside(self.runner, path)
        except cwds.CwdError:
            status = status or UNVERIFIED
        if status is None:
            status = classify(self.runner, self.clone, path, found=found)
        branch, detached, error = ("", False, "")
        if _sound(self.clone, path):
            branch, detached, error = self._branch(path)
        return Slot(
            name=row.name,
            path=path,
            status=status,
            branch=branch,
            detached=detached,
            branch_error=error,
            lease_id=row.lease_id or "",
            lease_holder=row.lease_holder or "",
            leased_at=row.leased_at,
            processes=[Process(pid=f.pid, name=f.name) for f in found],
        )

    def _branch(self, path: Path) -> tuple[str, bool, str]:
        result = self._git.result(path, "symbolic-ref", "--quiet", "--short", "HEAD")
        if result.ok:
            return result.stdout.strip(), False, ""
        if result.returncode == 1:
            return "", True, ""
        return "", False, (result.stderr.strip() or f"git symbolic-ref exited {result.returncode}")[:500]

    def _claim(self, path: Path, want: _Want) -> Lease:
        lease = _new_lease(path, want)
        with db.transaction(self.conn):
            claimed = sql.update("slots").set(
                lease_id=lease.lease_id,
                lease_holder=want.holder,
                leased_at=lease.leased_at,
                base=want.base or "",
                seeded="[]",
            )
            sql.execute(self.conn, claimed.where("path = ?", str(path)))
        return lease

    def _insert(self, name: str, path: Path, want: _Want) -> Lease:
        lease = _new_lease(path, want)
        with db.transaction(self.conn):
            row = sql.insert(
                "slots",
                repo=self.repo,
                name=name,
                path=str(path),
                lease_id=lease.lease_id,
                lease_holder=want.holder,
                leased_at=lease.leased_at,
                base=want.base or "",
            )
            sql.execute(self.conn, row)
        return lease

    def _adopt(self, name: str, path: Path) -> records.PoolSlot:
        with db.transaction(self.conn):
            sql.execute(self.conn, sql.insert("slots", repo=self.repo, name=name, path=str(path)))
        adopted = self._row(path)
        if adopted is None:
            raise PoolError(f"slot {path} vanished from the journal")
        return adopted

    def _forget(self, path: Path) -> None:
        """Remove a slot that never became usable: its worktree, its directory, and its row."""
        if path.exists() and self.clone.is_dir():
            self._git.result(self.clone, "worktree", "remove", "--force", str(path))
        if path.parent.parent == self.directory and not path.parent.is_symlink():
            shutil.rmtree(path.parent, ignore_errors=True)
        with db.transaction(self.conn):
            sql.execute(self.conn, sql.delete("slots").where("path = ?", str(path)))

    def _forget_gone(self, path: Path) -> None:
        """Forget the unheld slot at `path`, whose directory is gone: its worktree's entry in the clone, and its row."""
        if self.clone.is_dir():
            self._git.run(self.clone, "worktree", "prune")
        if path.parent.parent == self.directory and not path.parent.is_symlink():
            # Only an empty container: anything else in it is not the slot's.
            with contextlib.suppress(OSError):
                path.parent.rmdir()
        with db.transaction(self.conn):
            sql.execute(self.conn, sql.delete("slots").where("path = ?", str(path)))

    def _heal(self) -> None:
        """Forget idle slots whose directory is gone; a leased one waits for its return."""
        gone = [r.path for r in self._rows() if r.lease_holder is None and not Path(r.path).exists()]
        if gone:
            with db.transaction(self.conn):
                sql.execute(self.conn, sql.delete("slots").where_in("path", gone))

    def _rows(self) -> list[records.PoolSlot]:
        return (
            records.select(records.PoolSlot)
            .where("repo = ?", self.repo)
            .order_by("CAST(name AS INTEGER), name")
            .all(self.conn)
        )

    def _row(self, path: Path) -> records.PoolSlot | None:
        return records.select(records.PoolSlot).where("path = ?", str(path)).one(self.conn)

    def _seeded(self, path: Path) -> list[str]:
        row = self._row(path)
        return json.loads(row.seeded) if row is not None else []

    @contextlib.contextmanager
    def _locked(self) -> contextlib.Generator[None]:
        self.directory.mkdir(parents=True, exist_ok=True)
        with lock.hold(self.directory / LOCK_NAME, wait=True):
            yield

    @property
    def _git(self) -> _Git:
        return _Git(self.runner)


@dataclass(frozen=True)
class _Git:
    """git through `hostgit.argv` (D107), with optional locks off, failing as `PoolError`."""

    runner: procs.Runner

    def run(self, cwd: Path, *args: str, timeout: float = _GIT_TIMEOUT_SECONDS) -> str:
        result = self.result(cwd, *args, timeout=timeout)
        if not result.ok:
            detail = (result.stderr.strip() or result.stdout.strip())[:500]
            raise PoolError(f"git {args[0]} exited {result.returncode}: {detail}")
        return result.stdout.strip()

    def ok(self, cwd: Path, *args: str) -> bool:
        return self.result(cwd, *args).ok

    def z(self, cwd: Path, *args: str) -> list[str]:
        return [p for p in self.run(cwd, *args, "-z").split("\0") if p]

    def result(self, cwd: Path, *args: str, timeout: float = _GIT_TIMEOUT_SECONDS) -> procs.Result:
        try:
            result = self.runner.run(hostgit.argv(*args), cwd=cwd, env=ENV, timeout=timeout)
        except procs.ProcError as e:
            raise PoolError(f"git {args[0]}: {e}") from e
        if result.timed_out:
            raise PoolError(f"git {args[0]} timed out")
        return result


def classify(runner: procs.Runner, clone: Path, path: Path, *, found: Collection[cwds.Found] | None = None) -> str:
    """Classify an unleased slot of `clone`'s pool with canopy's own checks, changing nothing.

    Reconcile's shadow runs this on treehouse's slots to compare with what treehouse says (ROADMAP M45). `found` is
    the processes already read for the slot, if they were.

    Returns:
        `in-use` with a process in it, `unverified` when the processes cannot be read, `damaged` when it is not a
        worktree of `clone` whose git link canopy can vouch for, `dirty` with changes `git status` reports, else
        `available`.
    """
    if found is None:
        try:
            found = cwds.inside(runner, path)
        except cwds.CwdError:
            return UNVERIFIED
    if found:
        return IN_USE
    if not _sound(clone, path):
        return DAMAGED
    try:
        result = runner.run(
            hostgit.argv("status", "--porcelain", "--untracked-files=all"),
            cwd=path,
            env=ENV,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except procs.ProcError:
        return DAMAGED
    if not result.ok or result.timed_out:
        return DAMAGED
    return DIRTY if result.stdout.strip() else AVAILABLE


def _sound(clone: Path, path: Path) -> bool:
    """Whether `path` is a worktree of `clone` whose `.git` link and `commondir` are as git wrote them (D118).

    Returns:
        True when the slot is a real directory whose `.git` file names a directory under the clone's
        `.git/worktrees/`, and whose `commondir` names the clone's `.git`.
    """
    if path.is_symlink() or not path.is_dir():
        return False
    link = hostgit.read_link(path)
    if link is None:
        return False
    own = hostgit.own_git_dir(path, link)
    if own is None or not own.is_dir():
        return False
    if own.resolve().parent != (clone / ".git" / _WORKTREES).resolve():
        return False
    return not hostgit.commondir_moved(path, link)


def _new_lease(path: Path, want: _Want) -> Lease:
    return Lease(
        path=path,
        lease_id=uuid.uuid4().hex,
        lease_holder=want.holder,
        leased_at=datetime.now(UTC).isoformat(),
        base_branch=want.branch,
    )


def _reset(git: _Git, path: Path, commit: str, seeded: Iterable[str]) -> None:
    """Reset the slot at `path` to `commit`, detached: remove what seeding wrote, restore tracked files, drop untracked.

    Ignored files stay (`clean` without `-x`).
    """
    _remove_seeded(path, seeded)
    git.run(path, "read-tree", "--reset", "-u", commit)
    git.run(path, "update-ref", "--no-deref", "HEAD", commit)
    git.run(path, "clean", "-fd")


def _default_branch(git: _Git, clone: Path, repo: str) -> str:
    """The branch a lease with no base starts from: origin's HEAD, else the branch the clone has checked out.

    Returns:
        The branch's name.

    Raises:
        PoolError: neither names one.
    """
    remote = git.result(clone, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if remote.ok and remote.stdout.strip().startswith("refs/remotes/origin/"):
        return remote.stdout.strip().removeprefix("refs/remotes/origin/")
    local = git.result(clone, "symbolic-ref", "--quiet", "--short", "HEAD")
    if local.ok and local.stdout.strip():
        return local.stdout.strip()
    raise PoolError(f"cannot tell {repo}'s default branch: origin has no HEAD and the clone is detached")


def _merge_ref(git: _Git, clone: Path, repo: str) -> str | None:
    """The ref a slot must be merged into for `destroy`: the default branch as last fetched, or the local one.

    Returns:
        The fully qualified ref, or None when there is none.
    """
    try:
        branch = _default_branch(git, clone, repo)
    except PoolError:
        return None
    for ref in (f"refs/remotes/origin/{branch}", f"refs/heads/{branch}"):
        if git.ok(clone, "show-ref", "--verify", "--quiet", ref):
            return ref
    return None


def _branch_exists(git: _Git, cwd: Path, branch: str) -> bool:
    return any(
        git.ok(cwd, "show-ref", "--verify", "--quiet", ref)
        for ref in (f"refs/heads/{branch}", f"refs/remotes/origin/{branch}")
    )


def _commit(git: _Git, cwd: Path, branch: str) -> str:
    """The commit a slot on `branch` starts from: whichever of the local and the remote-tracking branch is ahead.

    Fully qualified, so a tag of the same name is never taken; origin's on divergence, as treehouse chooses.

    Returns:
        The commit's id.

    Raises:
        PoolError: neither ref exists.
    """
    local, remote = f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"
    has_local = git.ok(cwd, "show-ref", "--verify", "--quiet", local)
    has_remote = git.ok(cwd, "show-ref", "--verify", "--quiet", remote)
    ref = remote
    if has_local and not has_remote:
        ref = local
    elif has_local and not git.ok(cwd, "merge-base", "--is-ancestor", local, remote):
        ahead = git.ok(cwd, "merge-base", "--is-ancestor", remote, local)
        ref = local if ahead else remote
    elif not has_remote:
        raise PoolError(f"no branch {branch} and no origin/{branch}")
    return git.run(cwd, "rev-parse", "--verify", f"{ref}^{{commit}}")


def _tracked(rel: str, tracked: AbstractSet[str]) -> bool:
    """Whether `rel` is tracked in the slot, or is under or above a tracked path.

    Returns:
        True if seeding must not write it.
    """
    if rel in tracked:
        return True
    return any(t.startswith(f"{rel}/") or rel.startswith(f"{t}/") for t in tracked)


def _lexists(slot: Path, parts: Sequence[str]) -> bool:
    """Whether the slot already has something at `parts`, looking through no link.

    Returns:
        True if anything is there, a link or a directory included.
    """
    try:
        fd = _open_dirs(slot, parts[:-1], create=False)
    except FileNotFoundError:
        return False
    try:
        os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    finally:
        os.close(fd)
    return True


def _copy_seeds(clone: Path, slot: Path, planned: Iterable[str]) -> None:
    """Copy each planned path from the clone into the slot, never following a link on either side.

    A regular file keeps its permission bits; a link is written as a regular file holding its target, as treehouse
    writes it; anything else is passed over.

    Raises:
        OSError: a file could not be read or written, or something is in the way, such as a link where a directory
            goes or a file already there.
    """
    for rel in planned:
        parts = PurePosixPath(rel).parts
        source = clone.joinpath(*parts)
        info = source.lstat()
        if stat.S_ISREG(info.st_mode):
            fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as f:
                content = f.read()
            mode = stat.S_IMODE(info.st_mode)
        elif stat.S_ISLNK(info.st_mode):
            content = os.fsencode(source.readlink())
            mode = 0o666
        else:
            continue
        parent = _open_dirs(slot, parts[:-1], create=True)
        try:
            out = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=parent)
        finally:
            os.close(parent)
        with os.fdopen(out, "wb") as f:
            f.write(content)
            os.fchmod(f.fileno(), mode)


def _remove_seeded(slot: Path, seeded: Iterable[str]) -> None:
    """Remove the files seeding wrote, through no link; what is gone already, or is a directory now, is left."""
    for rel in seeded:
        parts = PurePosixPath(rel).parts
        if not parts or ".." in parts:
            continue
        try:
            parent = _open_dirs(slot, parts[:-1], create=False)
        except OSError:
            continue
        try:
            os.unlink(parts[-1], dir_fd=parent)
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            pass
        finally:
            os.close(parent)


def _open_dirs(slot: Path, parts: Iterable[str], *, create: bool) -> int:
    """Open the directory `parts` names under `slot`, one component at a time and through no link.

    Returns:
        An fd open on it, which the caller closes.

    Raises:
        OSError: a component is missing (and not created), or is a link or not a directory.
    """
    fd = os.open(slot, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts:
            if create:
                with contextlib.suppress(FileExistsError):
                    os.mkdir(part, 0o755, dir_fd=fd)
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
    except BaseException:
        os.close(fd)
        raise
    return fd
