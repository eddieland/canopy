"""Kicking flaky checks (DESIGN §23): after a `resume` for `ci` whose worker judged a failed check flaky.

Such a worker changes nothing for the check and pushes nothing, so no new run of the PR's checks would come. Under
`trust.max_flaky_kicks` the harness, never the worker, starts one: in each of the run's slots where origin still has the
branch where the run found it, it rebases the branch onto its base (`checkpoint.rebase_for_kick`), records the kick,
and pushes it with a lease on that head, the one forced push this allows (TRUST_MODEL T1). A head gets at most that
many kicks; a push of work starts a head of its own. A slot that is not kicked, for the limit, a rebase that stops or
would drop a change, or a push that fails, is named in the run's note, and the overseer asks the operator to rerun its
checks, as without kicks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import db
from canopy.core.vocab import ResumeReason, RunKind, RunStatus
from canopy.runs import checkpoint, flaky_kicks

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence

    from canopy.core.context import Context
    from canopy.infra import logs

#: The key that sets how many kicks a head gets, as a note names it.
KEY = "trust.max_flaky_kicks"


@dataclass(frozen=True)
class Kicks:
    """What a run's kicks did: the repositories whose branch was kicked, and a note for each slot that was not."""

    kicked: Sequence[str] = ()
    notes: Sequence[str] = ()
    #: Whether the run left a failed check as flaky, as a `resume` for `ci` that ended `done`: what the sinks hear of
    #: (`ci.flaky`), kicked or not.
    flaky: bool = False


def after_run(
    ctx: Context,
    run: sqlite3.Row,
    status: RunStatus,
    *,
    flaky: bool,
    places: Sequence[tuple[checkpoint.Git, str, checkpoint.Start]],
    log: logs.TickAdapter,
) -> Kicks:
    """Kick the branch in each of `places`, a slot's git, its base, and where it started, if the run is one to kick.

    That is a `resume` for `ci` that ended `done` with `flaky` true, under a `trust.max_flaky_kicks` above 0.

    Returns:
        Whether the run left a check flaky, the repositories kicked, and a note for each slot not kicked, saying why;
        nothing kicked and no notes without `trust.max_flaky_kicks`.
    """
    run_id = int(run["id"])
    if not (flaky and status is RunStatus.DONE and run["kind"] == RunKind.RESUME):
        return Kicks()
    if ResumeReason.CI not in db.run_reasons(ctx.conn, [run_id]).get(run_id, ()):
        return Kicks()
    limit = ctx.config.trust.max_flaky_kicks
    if not limit:
        return Kicks(flaky=True)
    branch = str(run["branch"])
    kicked: list[str] = []
    notes: list[str] = []
    for git, base, start in places:
        try:
            note = _kick(ctx, run_id, git, branch=branch, base=base, start=start, limit=limit, log=log)
        except checkpoint.SetupError as e:
            note = f"{git.where}not kicked: {str(e).removeprefix(git.where)}"
        if note is None:
            kicked.append(git.name)
        elif note:
            notes.append(note)
    return Kicks(kicked, notes, flaky=True)


def _kick(
    ctx: Context,
    run_id: int,
    git: checkpoint.Git,
    *,
    branch: str,
    base: str,
    start: checkpoint.Start,
    limit: int,
    log: logs.TickAdapter,
) -> str | None:
    """Kick `branch` in one slot, if origin has it where the run found it and its head has kicks left.

    Returns:
        None when it was kicked; "" when the run pushed to it, which starts its checks anyway; else why it was not.

    Raises:
        SetupError: a git step failed.
    """
    head = checkpoint.remote_head(git, branch)
    if not start.pushed or head != start.pushed:
        return ""
    spent = flaky_kicks.spent(ctx.conn, git.name, branch, head)
    if spent >= limit:
        return f"{git.where}not kicked: {branch} has had {spent} kick(s) since its work was pushed, {KEY}'s limit"
    made = checkpoint.rebase_for_kick(git, branch, base, head)
    # Recorded before the push: a `_run` that dies between them counts a kick that may not have happened, never the
    # other way, so a head never gets more than its kicks.
    flaky_kicks.record(ctx.conn, run_id, repo=git.name, branch=branch, from_head=head, to_head=made)
    try:
        checkpoint.push_kick(git, branch, head)
    except checkpoint.SetupError:
        flaky_kicks.forget(ctx.conn, run_id, git.name)
        raise
    log.info(
        "flaky checks kicked",
        extra={"run_id": run_id, "repo": git.name, "branch": branch, "from": head, "to": made, "kick": spent + 1},
    )
    return None
