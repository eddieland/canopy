"""What the runtime offered each agent run, MCP servers and skills, asked as the run started (DESIGN §13).

What an agent is offered is canopy's definitions merged with the operator's own runtime config, the repository's, and
the skills in their home, any of which may change between two runs; each costs every model call it is offered to,
used or not. So each run's own is recorded beside its tools, by `probing` the runtime while the run's agent works.
"""

from __future__ import annotations

import contextlib
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from canopy.core import db, records, sql
from canopy.runtime import offerings

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from pathlib import Path

    from canopy.core.run_models import RunTable
    from canopy.infra import logs, procs
    from canopy.runtime.agents import AgentOffer

#: How long a run that has ended waits for the runtime to say what it was offered: the ask started with the run, so
#: only a run shorter than the ask waits at all.
WAIT_SECONDS = 60
# The rows of one run, by its table and id.
_RUN: Final = "run_table = ? AND run_id = ?"


@dataclass(frozen=True)
class Offered:
    """What one agent run was offered, as `of_run` reads it back."""

    asked: records.RunOffer
    servers: Sequence[records.RunOfferedServer] = ()
    skills: Sequence[records.RunOfferedSkill] = ()


@contextlib.contextmanager
def probing(
    conn: sqlite3.Connection,
    table: RunTable,
    run_id: int,
    runner: procs.Runner,
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    log: logs.TickAdapter,
) -> Iterator[None]:
    """Ask the runtime what the agent `argv` starts is offered while the block runs it, and record the answer after.

    The runtime is asked on a thread of its own, started as `argv` starts it, in `cwd` with `env`, so the agent does not
    wait on it. Leaving the block, also by raising, waits for the answer at most `WAIT_SECONDS` and records it on the
    run. The record is the run's least concern: a journal write that fails is logged, never raised over the run's own
    outcome.
    """
    probe = offerings.Probe(runner, argv, cwd=cwd, env=env)
    try:
        yield
    finally:
        try:
            record(conn, table, run_id, probe.result(timeout=WAIT_SECONDS))
        except sqlite3.Error:
            log.exception("could not record what the run was offered", extra={"run_table": table, "run_id": run_id})


def record(conn: sqlite3.Connection, table: RunTable, run_id: int, offer: AgentOffer) -> None:
    """Record what the runtime said it offers a run, in place of anything recorded before.

    Only what was offered: a server with reach `none` is not, and nor is a denied skill.
    """
    servers = [(table, run_id, s.server, s.reach) for s in offer.servers if s.reach != "none"]
    with db.transaction(conn):
        sql.execute(conn, sql.delete("run_offered_servers").where(_RUN, table, run_id))
        sql.execute(conn, sql.delete("run_offered_skills").where(_RUN, table, run_id))
        sql.execute_many(
            conn,
            sql.insert_rows("run_offered_servers", ("run_table", "run_id", "server", "reach")),
            servers,
        )
        sql.execute_many(
            conn,
            sql.insert_rows("run_offered_skills", ("run_table", "run_id", "skill")),
            [(table, run_id, skill) for skill in offer.skills],
        )
        sql.execute(
            conn,
            sql.insert(
                "run_offers",
                run_table=table,
                run_id=run_id,
                agent=offer.agent or None,
                error=offer.error,
                asked_at=db.now(),
            ).or_replace(),
        )


def of_run(conn: sqlite3.Connection, table: RunTable, run_id: int) -> Offered | None:
    """What a run was offered, its servers and skills by name.

    Returns:
        The ask and what it found; None for a run canopy never asked about.
    """
    asked = records.fetch_one(conn, records.RunOffer, sql.select("*").from_("run_offers").where(_RUN, table, run_id))
    if asked is None:
        return None
    servers = sql.select("*").from_("run_offered_servers").where(_RUN, table, run_id).order_by("server")
    skills = sql.select("*").from_("run_offered_skills").where(_RUN, table, run_id).order_by("skill")
    return Offered(
        asked,
        records.fetch_all(conn, records.RunOfferedServer, servers),
        records.fetch_all(conn, records.RunOfferedSkill, skills),
    )
