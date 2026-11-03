"""The tick starts initiatives' plan runs (DESIGN §43): in code, after reconcile and before the overseer.

The overseer never sees one. The operator's submission, or their reply, authorized each run. Guards in code hold them,
whatever any agent asks: one plan run per initiative, at most `policy.max_plan_attempts` of them, never reset (D030),
and every run that holds a slot within `capacity.max_workers`. An initiative the guards hold waits for a later tick
rather than being refused, and a dry tick starts none (D036). Each start leases a slot in the pool of every repository
the initiative names, as `canopy:init:<id>`, all or none, records the run, renders its prompt, and spawns the detached
`canopy _initiative` (`initiative_run.py`).
"""

from __future__ import annotations

import contextlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import agent_models, db, initiatives, plans, pools, prompts
from canopy.core.vocab import RunStatus
from canopy.infra import lock, logs, procs
from canopy.runs import dispatch, initiative_runs

if TYPE_CHECKING:
    from collections.abc import Sequence

    from canopy.core import records
    from canopy.core.context import Context


@dataclass(frozen=True)
class Started:
    """An initiative's plan run the tick started: the initiative, its run, and the pid of its `canopy _initiative`."""

    initiative_id: int
    run_id: int
    pid: int


def start_due(ctx: Context, tick_id: int, log: logs.TickAdapter) -> list[Started]:
    """Start a plan run for each initiative due one that the guards let start now, the oldest first (DESIGN §43).

    Held under the dispatch lock, as every start is. An initiative whose repositories are not all cloned, or whose
    pools have no slot free, waits for a later tick, and those after it are still tried; once the runs that hold a slot
    fill `capacity.max_workers`, the rest wait. The caller starts none on a dry tick.

    Returns:
        The runs it started, in the order it started them.
    """
    started: list[Started] = []
    with lock.hold(ctx.dispatch_lock_path, wait=True):
        for initiative in initiative_runs.due(ctx.conn, ctx.config.policy.max_plan_attempts):
            busy = db.busy_workers(ctx.conn)
            if busy >= ctx.config.capacity.max_workers:
                log.info("initiative plans wait", extra={"initiative": initiative.id, "busy": busy})
                break
            found = _start(ctx, initiative, tick_id, log)
            if found is not None:
                started.append(found)
    return started


def prompt_file(log_path: Path) -> Path:
    """Return the file holding a plan run's rendered prompt: beside its log at `log_path`, as `<run_id>.prompt`."""
    return log_path.with_suffix(".prompt")


def _start(ctx: Context, initiative: records.Initiative, tick_id: int, log: logs.TickAdapter) -> Started | None:
    """Lease a slot in each of `initiative`'s repositories, record its plan run, and spawn its `canopy _initiative`.

    Returns:
        The run, or None when the initiative waits: a repository has no clone here, or its pool no slot.
    """
    fields = {"initiative": initiative.id}
    names = initiatives.repos_of(ctx.conn, initiative.id)
    for name in names:
        repo = ctx.workspace.repo(name)
        if repo is None or not repo.cloned:
            # The tick raises `repo_missing` for a repository in the map with no clone; one gone from the map stays so.
            log.warning("initiative plan waits: a repository has no clone here", extra={**fields, "repo": name})
            return None
    leases = _lease_all(ctx, initiative.id, names, log)
    if leases is None:
        return None
    model = agent_models.of_template(ctx.config.runtime.models, ctx.config.runtime.plan_cmd)
    run_id = initiative_runs.insert_run(
        ctx.conn,
        initiative_id=initiative.id,
        tick_id=tick_id,
        desk=dispatch.desk_path(ctx, initiative_runs.desk_key(initiative.id)),
        leases=leases,
        pool=ctx.config.pools.backend,
        logs_dir=initiative_runs.runs_dir(ctx),
        model=model.name if model is not None else None,
    )
    try:
        pid = _spawn(ctx, initiative, run_id, names)
    except _NotStarted as e:
        log.error("initiative plan run not started", extra={**fields, "run": run_id, "error": str(e)})  # noqa: TRY400
        _give_back(ctx, leases, log)
        return None
    log.info("initiative plan run started", extra={**fields, "run": run_id, "pid": pid})
    return Started(initiative.id, run_id, pid)


def _lease_all(
    ctx: Context,
    initiative_id: int,
    names: Sequence[str],
    log: logs.TickAdapter,
) -> list[tuple[str, pools.Lease]] | None:
    """Lease a slot in each repository's pool, or none: a slot leased before one that fails goes back.

    Returns:
        Each repository with its lease, or None when one has no slot free.
    """
    leases: list[tuple[str, pools.Lease]] = []
    for name in names:
        try:
            leases.append((name, ctx.pool(name).lease(f"{initiative_runs.HOLDER_KEY}{initiative_id}")))
        except pools.PoolError as e:
            log.warning(
                "initiative plan waits: no slot",
                extra={"initiative": initiative_id, "repo": name, "error": str(e)},
            )
            _give_back(ctx, leases, log)
            return None
    return leases


class _NotStarted(Exception):  # noqa: N818  (an outcome the run is closed with, not an error of the tick's)
    """The run's prompt could not be rendered, or its process started; the run is closed `crashed`, saying why."""


def _spawn(ctx: Context, initiative: records.Initiative, run_id: int, names: Sequence[str]) -> int:
    """Render run `run_id`'s prompt, write it beside its log, and spawn its detached `canopy _initiative`.

    Returns:
        The pid of `canopy _initiative`, which claims the run.

    Raises:
        _NotStarted: the prompt could not be rendered or written, or the process started. The run is closed `crashed`
            with why; the next one waits for the operator's reply, as after any run that failed (DESIGN §43).
        RuntimeError: the run's row is gone, which nothing but a broken journal does.
    """
    run = initiative_runs.get_run(ctx.conn, run_id)
    if run is None:
        raise RuntimeError(f"initiative plan run {run_id} vanished")
    members = [m.ticket_key for m in initiatives.members_of(ctx.conn, initiative.id)]
    values = {
        "INITIATIVE_ID": str(initiative.id),
        "GOAL": initiative.text,
        "DESK": run.desk_path,
        "REPOSITORIES": "\n".join(f"- `{name}`: `{Path(run.desk_path) / name}`" for name in names),
        # None leaves the section out: an initiative may be planned before any ticket of it exists.
        "MEMBERS": "\n".join(f"- {key}" for key in members) or None,
        "MAP": dispatch.map_note(ctx),
        # The operator's replies, each an instruction, the oldest first: what the next plan changes (DESIGN §43).
        "OPERATOR_MESSAGES": "\n\n".join(
            f"Message {m.id}, {m.at}:\n\n{m.body}" for m in initiatives.messages_of(ctx.conn, initiative.id)
        )
        or None,
        "PLAN_OUT": plans.WRITTEN,
        "PLAN_FILE": plans.REPLACED,
        "MAX_PLAN_CHARS": str(plans.MAX_CHARS),
        "TIMEOUT_MINUTES": str(ctx.config.runtime.worker_timeout_minutes),
    }
    log_path = Path(run.log_path)
    try:
        prompt = prompts.render_initiative_plan(ctx.config, values)
        logs.write_private(prompt_file(log_path), prompt)
        # `python -m canopy`, not `canopy` from PATH: the child is this same installation.
        argv = [sys.executable, "-m", "canopy", "_initiative", str(run_id)]
        pid = ctx.runner.spawn(argv, cwd=ctx.repo_root, log_path=log_path)
    except (OSError, prompts.PromptError, procs.ProcError) as e:
        note = json.dumps({"harness": f"could not start the initiative's planner: {e}"})
        initiative_runs.close_run(ctx.conn, run_id, RunStatus.CRASHED, note)
        raise _NotStarted(str(e)) from e
    db.claim_run(ctx.conn, "initiative_runs", run_id, pid)
    return pid


def _give_back(ctx: Context, leases: Sequence[tuple[str, pools.Lease]], log: logs.TickAdapter) -> None:
    """Return slots a start leased and cannot use. A return that fails is left to the next tick's reconcile."""
    for name, lease in leases:
        with contextlib.suppress(pools.PoolError):
            outcome = ctx.pool(name).return_slot(lease.path, lease_id=lease.lease_id, lease_holder=lease.lease_holder)
            log.info("initiative plan's slot returned unused", extra={"repo": name, "outcome": outcome.value})
