"""`canopy chore history`: a chore's earlier runs, read back on demand (DESIGN §19, History).

A run's prompt carries the latest ended run and the open findings. This reads the rest: each earlier run's status,
summary, and findings, and one run's findings in full. A chore's own run reads only its own chore's runs; the overseer
reads none, since its state block carries what it decides a chore on.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from canopy.core import conversation, db

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping

    from canopy.core import records

# Set for a chore's agent to the workspace's root, so `canopy chore history` finds its journal from a `cwd` outside it.
WORKSPACE_ENV = "CANOPY_CHORE_WORKSPACE"
# What a chore's agent sees as CANOPY_RUN_ID: `chore-<run id>`, or for a try that records nothing, which has no row,
# `chore-try:<name>`.
RUN_PREFIX = "chore-"
TRY_PREFIX = "chore-try:"
DEFAULT_LIMIT = 10
MAX_LIMIT = 50


class Refused(Exception):  # noqa: N818  (an outcome the caller is told about, not an error)
    """The history cannot be read from here. `guard` names why."""

    def __init__(self, guard: str, reason: str) -> None:
        """Name the guard and say why it refused."""
        super().__init__(f"{guard}: {reason}")
        self.guard = guard
        self.reason = reason


def command(name: str) -> str:
    """Return the command a run of chore `name` is told reads its earlier runs.

    Returns:
        `canopy chore history <name>`.
    """
    return f"canopy chore history {name}"


def check_reader(conn: sqlite3.Connection, name: str, environ: Mapping[str, str] | None = None) -> bool:
    """Refuse unless whoever runs this may read chore `name`'s history: the operator, or a run of that chore.

    Returns:
        True inside a run of the chore, False in the operator's shell.

    Raises:
        Refused: (`inside_tick`) the overseer runs it; (`not_chore`) a worker's or a review's run does; (`other_chore`)
            a run of another chore does.
    """
    env = os.environ if environ is None else environ
    run_env = env.get(conversation.RUN_ID_ENV)
    if not run_env:
        if env.get(conversation.TICK_ID_ENV):
            raise Refused("inside_tick", "the overseer's state block carries each chore's latest run and findings")
        return False
    own = _own_chore(conn, run_env)
    if own is None:
        raise Refused("not_chore", "only the operator and a chore's own runs read a chore's history")
    if own != name:
        raise Refused("other_chore", f"this is a run of chore {own}, which reads only its own runs")
    return True


def runs(conn: sqlite3.Connection, name: str, limit: int, before: int | None = None) -> list[records.ChoreRun]:
    """Return chore `name`'s runs, newest first: at most `limit`, and only those before run id `before` if given."""
    return db.chore_runs(conn, name, limit, before=before)


def run_of(conn: sqlite3.Connection, name: str, run_id: int) -> records.ChoreRun:
    """Return chore `name`'s run `run_id`.

    Returns:
        The run's row.

    Raises:
        Refused: (`unknown`) no run of the chore has that id.
    """
    run = db.get_chore_run(conn, run_id)
    if run is None or run.chore != name:
        raise Refused("unknown", f"chore {name} has no run {run_id}")
    return run


def _own_chore(conn: sqlite3.Connection, run_env: str) -> str | None:
    """The chore whose run CANOPY_RUN_ID's value `run_env` names.

    Returns:
        The chore's name, or None for any other run, a worker's or a review's.
    """
    if run_env.startswith(TRY_PREFIX):
        return run_env.removeprefix(TRY_PREFIX) or None
    number = run_env.removeprefix(RUN_PREFIX)
    if number == run_env or not number.isdigit():
        return None
    run = db.get_chore_run(conn, int(number))
    return run.chore if run is not None else None
