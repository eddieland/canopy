"""Remote branches canopy made that nothing in the journal names any more, for `canopy gc --dry-run` (DESIGN §26).

`canopy gc` deletes no remote branch: deleting one is outward-facing and may lose work (§22). The dry run lists those
the operator may delete. A branch is listed only when canopy's ownership of it is plain twice over: its name is the
one canopy gives, `<branch_prefix><KEY>-<slug>` for the ticket a run of it worked on or `<branch_prefix>task/<id>` for
the task, and this journal holds a run on it in that repository. A branch only one of those shows, such as one another
workspace sharing the remote and the prefix pushed, is never listed; nor is one an open run works on or stacks on, a
ticket or its unit names, or a task not stopped works on, since a reply may run it again.

Branches are read from each primary clone's remote-tracking refs, as its pool last fetched them, so the list may name
a branch already deleted on the remote. Nothing here fetches, and nothing is deleted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import hostgit, sql
from canopy.core.vocab import RunStatus
from canopy.infra import procs
from canopy.runs import dispatch, tasks

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from canopy.core.context import Context

#: The remote every primary clone pushes to and fetches from.
REMOTE = "origin"
_FOR_EACH_REF_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class Branch:
    """A remote branch canopy made that no open run, unit, or task names: the operator's to delete, never canopy's."""

    #: The repository, by the map's name for it.
    repo: str
    #: The branch's name on the remote, `trust.branch_prefix` and all.
    name: str
    #: The commit its remote-tracking ref in the primary clone is at.
    head: str
    #: The ticket whose runs worked on it, or None for a task's branch.
    ticket: str | None
    #: The task whose runs worked on it, or None for a ticket's branch.
    task: int | None


def unnamed(ctx: Context, notes: list[str]) -> list[Branch]:
    """The remote branches canopy made in each primary clone that no open run, unit, or task names, changing nothing.

    A clone git cannot read is left out, with a note saying so; one that is not there is `measure`'s to note.

    Returns:
        The branches, by repository in the map's order, then by name.
    """
    prefix = ctx.config.trust.branch_prefix
    named = _named(ctx.conn, prefix)
    found: list[Branch] = []
    for repo in ctx.workspace.repos:
        made = _made(ctx.conn, prefix, repo.name)
        if not made or not repo.cloned:
            continue
        heads = _remote_heads(ctx.runner, repo.path, prefix)
        if heads is None:
            notes.append(f"{repo.name}: git for-each-ref failed in {repo.path}")
            continue
        for name, head in sorted(heads.items()):
            owner = made.get(name)
            if owner is not None and name not in named:
                found.append(Branch(repo.name, name, head, *owner))
    return found


def _named(conn: sqlite3.Connection, prefix: str) -> set[str]:
    """Every branch the journal still names, in any repository.

    A ticket's or its unit's, an open run's and the branch it stacks on, and a task's while it is not stopped.

    Returns:
        Their names.
    """
    open_runs = sql.select("id").from_("runs").where("status = ?", RunStatus.RUNNING)
    open_tasks = sql.select("id").from_("tasks").where("stopped_at IS NULL")
    names = sql.union(
        sql.select("branch").from_("tickets").where("branch IS NOT NULL"),
        sql.select("branch").from_("ticket_units").where("branch IS NOT NULL"),
        sql.select("branch").from_("runs").where("status = ?", RunStatus.RUNNING),
        sql.select("base_branch").from_("run_slots").where("base_branch IS NOT NULL AND run_id IN ({})", open_runs),
        sql.select("branch").from_("task_runs").where("status = ? OR task_id IN ({})", RunStatus.RUNNING, open_tasks),
        sql.select("base_branch").from_("task_runs").where("status = ?", RunStatus.RUNNING),
    )
    found = {str(r[0]) for r in sql.execute(conn, names)}
    found.update(tasks.branch(prefix, int(r[0])) for r in sql.execute(conn, open_tasks))
    return found


def _made(conn: sqlite3.Connection, prefix: str, repo: str) -> dict[str, tuple[str | None, int | None]]:
    """The branches this journal's runs worked on in `repo` under the name canopy gives them, and whose they are.

    Returns:
        Each branch's name, and the ticket or the task it is of, as `Branch`'s last two fields.
    """
    made: dict[str, tuple[str | None, int | None]] = {}
    runs = sql.select("r.ticket_key, r.branch").unique().from_("runs r").join("run_slots s ON s.run_id = r.id")
    for r in sql.execute(conn, runs.where("s.repo = ?", repo)):
        key, branch = str(r["ticket_key"]), str(r["branch"])
        start = f"{prefix}{key}-"
        if branch.startswith(start) and dispatch.valid_slug(branch.removeprefix(start)):
            made[branch] = (key, None)
    task_runs = sql.select("task_id, branch").unique().from_("task_runs").where("repo = ?", repo)
    for r in sql.execute(conn, task_runs):
        task_id, branch = int(r["task_id"]), str(r["branch"])
        if branch == tasks.branch(prefix, task_id):
            made[branch] = (None, task_id)
    return made


def _remote_heads(runner: procs.Runner, clone: Path, prefix: str) -> dict[str, str] | None:
    """The remote-tracking refs under `prefix` in `clone`, as its last fetch left them; nothing is fetched.

    Returns:
        Each branch's name on the remote and the commit it is at, or None when git could not run or failed.
    """
    tracking = f"refs/remotes/{REMOTE}/"
    try:
        done = runner.run(
            hostgit.argv("for-each-ref", "--format=%(objectname) %(refname)", f"{tracking}{prefix}"),
            cwd=clone,
            env=hostgit.ENV,
            timeout=_FOR_EACH_REF_TIMEOUT_SECONDS,
        )
    except procs.ProcError:
        return None
    if not done.ok:
        return None
    heads: dict[str, str] = {}
    for line in done.stdout.splitlines():
        head, _, ref = line.partition(" ")
        if ref.startswith(tracking):
            heads[ref.removeprefix(tracking)] = head
    return heads
