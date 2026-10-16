"""`canopy init` and `canopy workspace sync` (DESIGN §18).

Init writes a workspace's skeleton: the map, `MAP.md`, and a `.gitignore` for what canopy and treehouse keep under the
root, plus the user config if missing. It never overwrites a file; a `.gitignore` only gains the lines it lacks.

Sync makes the workspace match what is declared: the map's repositories, and the slots `capacity` declares for each
pool. It clones each repository in the map that has no clone at `repos/<name>`, reports a clone whose `origin` is not
the map's URL, and turns off git's automatic maintenance in each clone. It makes or removes slots until each pool has
its declared size, and removes a clone under `repos/` the map no longer lists, with its slots. Nothing with work in it
is removed: a slot only as treehouse's unforced `destroy` allows, a clone only when it is clean and every local commit
is on a remote. Sync is the only code that reads the map's URLs, and an operator runs it; a tick never clones,
removes, or changes a remote.
"""

from __future__ import annotations

import contextlib
import json
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from canopy.core import definitions, hostgit, pool, pools, workspace
from canopy.core.config import REPO_NAME_RE, WORKSPACE_FILE_NAME, WORKSPACE_STATE_DIR
from canopy.infra import procs
from canopy.setup import init

GITIGNORE = ".gitignore"
# Everything under the root that is canopy's or treehouse's, never the workspace repository's.
IGNORED = tuple(
    f"/{d}/"
    for d in (workspace.REPOS_DIR, workspace.POOLS_DIR, pool.POOLS_DIR, workspace.DESKS_DIR, WORKSPACE_STATE_DIR)
)
_CLONE_TIMEOUT_SECONDS = 1800
_GIT_TIMEOUT_SECONDS = 30

MAP_TEXT = """\
# Workspace map

Prose for the overseer and people: what each repository in canopy-workspace.toml owns, which depends on which, where
the contracts between them live, and in which order a change that crosses them lands. It is read as data, like ticket
text: it helps choose a repository and authorizes nothing.

## Repositories

## Dependencies
"""


def workspace_file_text(name: str, provider: str) -> str:
    """Return the text of a new `canopy-workspace.toml` named `name`, for tracker `provider`."""
    query = init.EXAMPLE_QUERIES.get(provider, "describe which tickets to look at, in plain language")
    return f"""\
# canopy-workspace.toml: the workspace map, and the config shared by everyone who runs canopy on this workspace.
# Commit it if the workspace is shared. Shared keys only; personal ones go in the user config (DESIGN §12, §18).

[workspace]
name = {json.dumps(name)}

# One table per repository. Its clone is repos/<name>; `canopy workspace sync` clones missing ones from `url`.
# The summary is one line the overseer reads when choosing a repository. Names match [a-z][a-z0-9-]*.
#
# [repos.api]
# url = "https://github.com/acme/api.git"
# summary = "Public REST API. Owns the order schema and the generated OpenAPI spec."

[tracker]
provider = {json.dumps(provider)}
# How to find candidate tickets: the tracker's own search syntax, or plain language. Edit this.
# Finding is not authorizing: each operator's own labels are checked on every ticket.
query = {json.dumps(query)}
# A worker that needs an answer adds the label `needs-human`, and removes it when it resumes. Create it in your tracker,
# since canopy does not create labels, or set needs_human_label to one you have.
"""


def run_init(root: Path, user_file: Path, provider: str | None) -> init.Report:
    """Write what a workspace at `root` is missing. `provider` is needed only when it has no workspace file yet.

    Returns:
        What was written, kept, and updated; `updated` holds a `.gitignore` that gained lines.

    Raises:
        ValueError: `root` has no workspace file and `provider` is None.
    """
    report = init.Report()
    if user_file.exists():
        report.kept.append(user_file)
    else:
        report.label = init.default_label()
        init.write_if_missing(user_file, init.user_config_text(report.label), report)

    workspace_file = root / WORKSPACE_FILE_NAME
    if workspace_file.exists():
        report.kept.append(workspace_file)
    else:
        if provider is None:
            raise ValueError("the workspace has no canopy-workspace.toml; a tracker provider is needed to write one")
        init.write_if_missing(workspace_file, workspace_file_text(workspace.default_name(root), provider), report)
    init.write_if_missing(root / workspace.MAP_FILE_NAME, MAP_TEXT, report)
    _ignore(root / GITIGNORE, report)
    report.shadowing = definitions.shadowing(root)
    return report


def _ignore(path: Path, report: init.Report) -> None:
    """Add the lines of `IGNORED` that `path` lacks, creating it if missing."""
    if not path.exists():
        path.write_text("# canopy and treehouse keep these under the workspace root.\n" + "\n".join(IGNORED) + "\n")
        report.written.append(path)
        return
    text = path.read_text(encoding="utf-8")
    present = {line.strip() for line in text.splitlines()}
    missing = [line for line in IGNORED if line not in present]
    if not missing:
        report.kept.append(path)
        return
    separator = "" if not text or text.endswith("\n") else "\n"
    path.write_text(text + separator + "\n".join(missing) + "\n", encoding="utf-8")
    report.updated.append(path)


def protection_targets(ws: workspace.Workspace) -> str:
    """Name the repositories the branch protection rules must be configured in (TRUST_MODEL §7).

    Returns:
        Lines for the operator naming each repository in the map, or saying it lists none yet.
    """
    if not ws.repos:
        return "The map lists no repositories yet. Configure the rules in each one you add.\n"
    # Names only: clone URLs are read by `canopy workspace sync` alone, and one may carry a credential.
    lines = ["Configure them in every repository in the map:"]
    lines += [f"  - {r.name}" for r in ws.repos]
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class Checked:
    """What sync found or did for one repository, and what to tell the operator.

    For a clone: `cloned`, `present`, `to clone` in a dry run, or `failed`. For a pool: `slots`, `failed`, or `kept`
    when the pool keeps a surplus slot with work in it; after a switch of `pools.backend`, `moved` or `to move` for
    treehouse's idle slots moved into canopy's pool, and `removed` or `to remove` for canopy's idle slots removed. For
    a clone the map no longer lists: `removed`, `to remove` in a dry run, or `kept` when it has work to lose.
    """

    repo: workspace.Repo
    outcome: str
    detail: str = ""


def repo_arg(arg: str) -> tuple[str, str]:
    """Split a `[NAME=]URL` argument into the repository's name and clone URL.

    Without a name, it is the URL's last path segment without `.git`, reduced to a valid repository name.

    Returns:
        The name and the URL.

    Raises:
        ValueError: the name or URL is not valid. The message says what to pass instead.
    """
    name, sep, url = arg.partition("=")
    # A prefix with no ":" or "/" can only be a name, so an invalid one is refused rather than read as part of a URL.
    if sep and not REPO_NAME_RE.fullmatch(name) and not any(c in name for c in ":/"):
        raise ValueError(f"{arg!r}: repository name {name!r} must match {REPO_NAME_RE.pattern}")
    if not sep or not REPO_NAME_RE.fullmatch(name):
        name, url = "", arg
    error = workspace.url_error(url)
    if error is not None:
        raise ValueError(f"{arg!r}: {error}")
    if not name:
        name = workspace.reduce_name(url.rstrip("/").removesuffix(".git").replace(":", "/").rpartition("/")[2])
        if not name:
            raise ValueError(f"{arg!r}: no repository name in the URL; pass NAME=URL")
    return name, url


@dataclass(frozen=True)
class Added:
    """What `add` did with one `[NAME=]URL`: `added`, or `present` when the map already lists it."""

    name: str
    outcome: str
    detail: str = ""


def add(ws: workspace.Workspace, entries: Iterable[tuple[str, str]]) -> list[Added]:
    """Add each `(name, url)` to the map as a `[repos.<name>]` table, unless the map already lists that URL.

    Nothing is written if any entry conflicts: a name the map gives another URL, or a name given twice.

    Returns:
        What was done with each entry, in order: `added`, or `present` under the name the map lists the URL by.

    Raises:
        ValueError: an entry conflicts. The message names it.
    """
    listed = {r.name: str(r.url) for r in ws.repos}
    added: list[Added] = []
    tables: list[str] = []
    for name, url in entries:
        same = next((n for n, u in listed.items() if _same_url(u, url)), None)
        if same is not None:
            added.append(Added(same, "present", "the map already lists it"))
            continue
        if name in listed:
            raise ValueError(f"{name}: the map already has a repository by that name; pass NAME=URL for this one")
        listed[name] = url
        # json.dumps writes a TOML basic string: its escapes are valid TOML.
        tables.append(f'\n[repos.{name}]\nurl = {json.dumps(url)}\nsummary = ""  # one line for the overseer\n')
        added.append(Added(name, "added"))
    if tables:
        text = ws.map_file.read_text(encoding="utf-8")
        separator = "" if not text or text.endswith("\n") else "\n"
        # Written whole and renamed into place, so an interrupted add leaves the old map, never part of one.
        partial = ws.map_file.with_name(ws.map_file.name + ".tmp")
        partial.write_text(text + separator + "".join(tables), encoding="utf-8")
        partial.replace(ws.map_file)
        workspace.load(ws.root)  # what was written must read back; it is checked before writing, so it does
    return added


def missing(ws: workspace.Workspace) -> list[workspace.Repo]:
    """Return the map's repositories with no clone, which sync would clone."""
    return [r for r in ws.repos if not r.cloned]


def clone(runner: procs.Runner, ws: workspace.Workspace, repo: workspace.Repo) -> Checked:
    """Clone `repo` from the map's URL into `repos/<name>`.

    Returns:
        `cloned`, or `failed` with why: something not a clone is in the way, or git could not clone it.
    """
    if repo.path.is_symlink() or (repo.path.exists() and (not repo.path.is_dir() or any(repo.path.iterdir()))):
        return Checked(repo, "failed", f"{repo.path} exists and is not a clone; move it away and sync again")
    repo.path.parent.mkdir(parents=True, exist_ok=True)
    args = hostgit.argv("clone", "--quiet", "--", str(repo.url), str(repo.path))
    try:
        result = runner.run(args, cwd=ws.root, env=hostgit.ENV, timeout=_CLONE_TIMEOUT_SECONDS)
    except procs.ProcError as e:
        return Checked(repo, "failed", str(e))
    if not result.ok:
        status = "timed out" if result.timed_out else f"exited {result.returncode}"
        output = (result.stderr.strip() or result.stdout.strip()).replace(str(repo.url), shown(str(repo.url)))
        return Checked(repo, "failed", f"git clone {status}: {output[:500]}")
    return Checked(repo, "cloned")


def check_origin(runner: procs.Runner, repo: workspace.Repo) -> Checked:
    """Report whether an existing clone's `origin` is the map's URL. Nothing is changed either way.

    Returns:
        `present`, with a detail naming both URLs when they differ, or `failed` when git cannot read the origin.
    """
    try:
        result = runner.run(
            hostgit.argv("remote", "get-url", "origin"), cwd=repo.path, env=hostgit.ENV, timeout=_GIT_TIMEOUT_SECONDS
        )
    except procs.ProcError as e:
        return Checked(repo, "failed", str(e))
    if not result.ok:
        return Checked(repo, "failed", f"the clone has no origin; the map says {repo.url}")
    origin = result.stdout.strip()
    if _same_url(origin, str(repo.url)):
        return Checked(repo, "present")
    return Checked(
        repo, "present", f"origin is {shown(origin)}, but the map says {shown(str(repo.url))}; canopy changes no remote"
    )


def turn_off_auto_maintenance(runner: procs.Runner, repo: workspace.Repo) -> Checked | None:
    """Turn off git's automatic maintenance in the clone's own config, which every slot of its pool shares.

    `hostgit.argv` turns it off for the harness's git; this is for the git it does not run, the worker's and
    treehouse's, since a fetch or commit in one slot otherwise starts it on the git directory every other slot uses.

    Returns:
        None once both keys are set, or `failed` with why git could not set one.
    """
    for key, value in hostgit.AUTO_MAINTENANCE_OFF:
        try:
            result = runner.run(
                hostgit.argv("config", "--local", key, value),
                cwd=repo.path,
                env=hostgit.ENV,
                timeout=_GIT_TIMEOUT_SECONDS,
            )
        except procs.ProcError as e:
            return Checked(repo, "failed", str(e))
        if not result.ok:
            return Checked(
                repo, "failed", f"git config {key} exited {result.returncode}: {result.stderr.strip()[:500]}"
            )
    return None


def shown(url: str) -> str:
    """Return `url` fit to print: a credential in it (`https://user:token@host/...`) is replaced with `***`."""
    parts = urlsplit(url)
    if not parts.scheme or "@" not in parts.netloc:
        return url
    return urlunsplit(parts._replace(netloc="***@" + parts.netloc.rpartition("@")[2]))


def _same_url(a: str, b: str) -> bool:
    def norm(url: str) -> str:
        return url.rstrip("/").removesuffix(".git")

    return norm(a) == norm(b)


def converge_pool(pool: pools.Pool, repo: workspace.Repo, want: int, *, dry_run: bool) -> Checked:
    """Make or remove slots until `repo`'s pool, `pool`, has `want`.

    Slots are made by leasing as `canopy-sync` until the pool is big enough, then returning every one of those leases;
    one a crashed sync left is returned first. Surplus slots are removed highest name first, and only available ones,
    with treehouse's unforced `destroy`: a busy one stays until a later sync finds it idle. A new slot is seeded from
    the pool's include file, as a run's lease would seed it, before its `post_create` hooks run.

    Returns:
        `slots` with the pool's size, `kept` when treehouse keeps a surplus slot with work in it, or `failed` when the
        pool could not be read or grown.
    """
    try:
        slots = pool.status()
        if not dry_run and _return_sync_leases(slots, pool):
            slots = pool.status()
        if len(slots) < want:
            return _fill(repo, pool, slots, want, dry_run=dry_run)
        if len(slots) > want:
            return _trim(repo, pool, slots, want, dry_run=dry_run)
    except pools.PoolError as e:
        return Checked(repo, "failed", f"its pool: {e}")
    return Checked(repo, "slots", f"{want} of {want}")


def _return_sync_leases(slots: Sequence[pools.Slot], pool: pools.Pool) -> bool:
    """Return the slots a sync that died left leased. Returns whether there were any.

    Raises:
        pools.PoolError: one could not be returned.
    """
    left = [s for s in slots if s.lease_holder == pools.SYNC_HOLDER and s.lease_id]
    for slot in left:
        outcome = pool.return_slot(slot.path, lease_id=slot.lease_id, lease_holder=slot.lease_holder)
        if outcome is not pools.ReturnOutcome.RETURNED:
            raise pools.PoolError(f"returning {slot.path}, left leased by a sync, said {outcome.value}")
    return bool(left)


def _fill(
    repo: workspace.Repo,
    pool: pools.Pool,
    slots: Sequence[pools.Slot],
    want: int,
    *,
    dry_run: bool,
) -> Checked:
    """Lease until the pool has `want` slots, then return every lease. treehouse makes a slot when none is available.

    Returns:
        `slots` with how many were made, or `failed` when a lease failed or one could not be returned.
    """
    if dry_run:
        return Checked(repo, "slots", f"{len(slots)} of {want}, would make {want - len(slots)}")
    known = {s.path for s in slots}
    held: list[pools.Lease] = []
    error: pools.PoolError | None = None
    try:
        # Each lease holds a different slot, so `want` leases are always enough to reach `want` slots.
        while len(known) < want and len(held) < want:
            leased = pool.lease_as(pools.SYNC_HOLDER, fetch=False)
            held.append(leased)
            known.add(leased.path)
    except pools.PoolError as e:
        error = e
    finally:
        unreturned = _return_leases(held, pool)
    made = len(known) - len(slots)
    detail = f"{len(known)} of {want}, made {made}"
    if error is not None:
        hint = "if treehouse makes the pool, its max_trees (treehouse.toml or ~/.config/treehouse/) may be lower"
        detail += f": {error} ({hint})"
    if unreturned:
        detail += f"; {unreturned} still leased as {pools.SYNC_HOLDER}, returned by the next sync"
    return Checked(repo, "failed" if error is not None or unreturned else "slots", detail)


def _return_leases(held: Iterable[pools.Lease], pool: pools.Pool) -> int:
    """Return sync's leases. Returns how many could not be returned."""
    unreturned = 0
    for leased in held:
        outcome: pools.ReturnOutcome | None = None
        with contextlib.suppress(pools.PoolError):
            outcome = pool.return_slot(leased.path, lease_id=leased.lease_id, lease_holder=leased.lease_holder)
        unreturned += outcome is not pools.ReturnOutcome.RETURNED
    return unreturned


def _slot_order(slot: pools.Slot) -> tuple[int, str]:
    # treehouse names slots 1, 2, ...; the highest are removed first, so the pool keeps its lowest names.
    return (int(slot.name) if slot.name.isdigit() else -1, slot.name)


def _trim(
    repo: workspace.Repo,
    pool: pools.Pool,
    slots: Sequence[pools.Slot],
    want: int,
    *,
    dry_run: bool,
) -> Checked:
    """Remove available slots, highest name first, until the pool has `want`. Busy slots stay.

    A slot treehouse keeps, because it has work in it, is passed over for the next available one.

    Returns:
        `slots` with what was removed and any busy surplus left, or `kept` when treehouse kept a slot with work in it
        and the pool is still over `want`.
    """
    surplus = len(slots) - want
    idle = sorted((s for s in slots if s.status == pools.AVAILABLE), key=_slot_order, reverse=True)
    if dry_run:
        names = ", ".join(s.name for s in idle[:surplus]) or "none"
        return Checked(repo, "slots", f"{len(slots)} of {want}, would remove {names}")
    removed: list[str] = []
    kept: list[str] = []
    for slot in idle:
        if len(removed) == surplus:
            break
        why = pool.destroy(slot.path)
        if why is None:
            removed.append(slot.name)
        else:
            kept.append(f"slot {slot.name} kept: {why}")
    left = len(slots) - len(removed)
    detail = f"{left} of {want}, removed {', '.join(removed) or 'none'}"
    if left == want:
        return Checked(repo, "slots", detail)
    if kept:
        # treehouse keeps a slot with work in it, which only the operator can resolve.
        return Checked(repo, "kept", "; ".join((detail, *kept)))
    return Checked(repo, "slots", f"{detail}; {left - want} over, busy; a later sync removes them once idle")


def move_slots(source: pools.Pool, into: pool.CanopyPool, repo: workspace.Repo, *, dry_run: bool) -> Checked | None:
    """Move each idle slot of treehouse's pool, `source`, into canopy's, `into`, keeping its ignored files.

    What a switch to `pools.backend = "canopy"` asks of sync (DESIGN §18, ROADMAP M45): the slots and their build
    caches carry over. A slot that is not idle stays where it is, its lease goes back to treehouse when its run ends,
    and a later sync moves it.

    Returns:
        None when treehouse's pool has no idle slot; else `moved`, `to move` in a dry run, or `kept` with each slot
        that could not move, or when treehouse's pool cannot be read.
    """
    try:
        idle = sorted((s for s in source.status() if s.status == pools.AVAILABLE), key=_slot_order)
    except pools.PoolError as e:
        hint = "remove .treehouse/ once it holds nothing you need"
        return Checked(repo, "kept", f"treehouse's pool cannot be read, so its idle slots stay ({hint}): {e}")
    if not idle:
        return None
    if dry_run:
        return Checked(repo, "to move", f"{len(idle)} idle treehouse slots into {pool.POOLS_DIR}/")
    moved: list[str] = []
    kept: list[str] = []
    for slot in idle:
        try:
            into.move_in(slot.path)
        except pools.PoolError as e:
            kept.append(f"slot {slot.name} stays in treehouse's pool: {e}")
        else:
            moved.append(slot.name)
    detail = f"moved {len(moved)} of {len(idle)} idle treehouse slots into {pool.POOLS_DIR}/"
    return Checked(repo, "kept", "; ".join((detail, *kept))) if kept else Checked(repo, "moved", detail)


def drop_idle(source: pools.Pool, repo: workspace.Repo, *, dry_run: bool) -> Checked | None:
    """Remove each idle slot of canopy's pool, `source`, after a switch back to treehouse.

    Switching back costs only warm caches (ROADMAP M45): treehouse makes fresh slots, and canopy's are removed as
    sync's trim removes a slot, so one with anything to lose is kept.

    Returns:
        None when canopy's pool has no idle slot; else `removed`, `to remove` in a dry run, or `kept` with each slot
        the pool kept, or when the pool cannot be read.
    """
    try:
        idle = sorted((s for s in source.status() if s.status == pools.AVAILABLE), key=_slot_order)
    except pools.PoolError as e:
        return Checked(repo, "kept", f"canopy's pool cannot be read, so its idle slots stay: {e}")
    if not idle:
        return None
    if dry_run:
        return Checked(repo, "to remove", f"{len(idle)} idle slots of canopy's pool")
    kept = [f"slot {s.name} kept: {why}" for s in idle if (why := source.destroy(s.path)) is not None]
    detail = f"removed {len(idle) - len(kept)} of {len(idle)} idle slots of canopy's pool"
    return Checked(repo, "kept", "; ".join((detail, *kept))) if kept else Checked(repo, "removed", detail)


def undeclared(ws: workspace.Workspace) -> list[workspace.Repo]:
    """Return what is under `repos/` that the map does not list, which sync removes. Dot entries are left alone."""
    repos_dir = ws.root / workspace.REPOS_DIR
    if repos_dir.is_symlink() or not repos_dir.is_dir():
        return []
    names = {r.name for r in ws.repos}
    found = (p for p in repos_dir.iterdir() if p.name not in names and not p.name.startswith("."))
    return [workspace.Repo(name=p.name, path=p) for p in sorted(found)]


def remove(runner: procs.Runner, pool: pools.Pool, repo: workspace.Repo, *, dry_run: bool) -> Checked:
    """Remove a clone the map no longer lists, and its slots in `pool`, unless anything in them could be lost.

    Returns:
        `removed`, `to remove` in a dry run, or `kept` with what could be lost or the slot the pool kept.
    """
    blocked, slots = _removable(runner, repo, pool)
    if blocked is not None:
        return Checked(repo, "kept", blocked)
    if dry_run:
        return Checked(repo, "to remove", f"{repo.path} and its {len(slots)} slots")
    for slot in slots:
        try:
            why = pool.destroy(slot.path)
        except pools.PoolError as e:
            why = str(e)
        if why is not None:
            return Checked(repo, "kept", f"slot {slot.name} kept: {why}")
    shutil.rmtree(repo.path)
    return Checked(repo, "removed", f"{repo.path} and its {len(slots)} slots")


def _removable(runner: procs.Runner, repo: workspace.Repo, pool: pools.Pool) -> tuple[str | None, Sequence[pools.Slot]]:
    """Say why the clone cannot be removed, or None, and return its pool's slots.

    Returns:
        The reason or None, and the pool's slots, which are empty when there is a reason before the pool is read.
    """
    if repo.path.is_symlink() or not repo.path.is_dir() or not repo.cloned:
        return f"{repo.path} is not a clone; canopy removes only clones", []
    unsaved = _unsaved(runner, repo.path)
    if unsaved:
        return f"{unsaved}; push or discard it, then sync again", []
    try:
        slots = pool.status()
    except pools.PoolError as e:
        return f"its pool cannot be read: {e}", []
    busy = [f"slot {s.name} is {s.status}" for s in slots if s.status != pools.AVAILABLE]
    return ("; ".join(busy) if busy else None), slots


def _unsaved(runner: procs.Runner, path: Path) -> str | None:
    """Say what in the clone at `path` would be lost by removing it, or None if nothing would.

    Returns:
        The first thing found, or why git could not check, or None.
    """
    checks = (
        # Ignored files too: a primary clone holds local config that `.worktreeinclude` seeds into slots (DESIGN §9).
        (("status", "--porcelain", "--ignored"), "it has uncommitted, untracked, or ignored files"),
        (("stash", "list"), "it has stashed changes"),
        # Commits that no remote-tracking ref has, on a branch, a tag, or a detached HEAD: never pushed, as far as this
        # clone knows.
        (
            ("rev-list", "--max-count=1", "HEAD", "--branches", "--tags", "--not", "--remotes"),
            "it has commits no remote has",
        ),
    )
    for args, reason in checks:
        try:
            result = runner.run(hostgit.argv(*args), cwd=path, env=hostgit.ENV, timeout=_GIT_TIMEOUT_SECONDS)
        except procs.ProcError as e:
            return f"git {args[0]} failed: {e}"
        if not result.ok:
            return f"git {args[0]} exited {result.returncode}"
        if result.stdout.strip():
            return reason
    return None
