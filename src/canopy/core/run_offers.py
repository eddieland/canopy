"""What the runtime offered each agent run as it started (DESIGN §13): MCP servers, skills, and its own tools.

What an agent is offered is canopy's definitions merged with the operator's own runtime config, the repository's, and
the skills in their home, any of which may change between two runs; each costs every model call it is offered to,
used or not. So each run's own is recorded beside its tools, by `probing` the runtime while the run's agent works.
"""

from __future__ import annotations

import contextlib
import sqlite3
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from canopy.core import db, records
from canopy.runtime import offerings

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from pathlib import Path

    from canopy.core.run_models import RunTable
    from canopy.infra import logs, procs
    from canopy.runtime.agents import AgentOffer
    from canopy.runtime.implementation import Version

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
    #: The rules that leave the run only some of a server's tools, by server, each server's in the order they apply.
    server_rules: Mapping[str, Sequence[str]] = field(default_factory=dict)
    skills: Sequence[records.RunOfferedSkill] = ()
    tools: Sequence[records.RunOfferedTool] = ()


@contextlib.contextmanager
def probing(
    conn: sqlite3.Connection,
    table: RunTable,
    run_id: int,
    runner: procs.Runner,
    argv: Sequence[str],
    *,
    version: Version,
    cwd: Path,
    env: Mapping[str, str],
    log: logs.TickAdapter,
) -> Iterator[None]:
    """Ask the runtime what the agent `argv` starts is offered while the block runs it, and record the answer after.

    The runtime `version` runs is asked on a thread of its own, started as `argv` starts it, in `cwd` with `env`, so
    the agent does not wait on it. Leaving the block, also by raising, waits for the answer at most `WAIT_SECONDS` and
    records it on the run. The record is the run's least concern: a journal write that fails is logged, never raised
    over the run's own outcome.
    """
    probe = offerings.Probe(runner, argv, version=version, cwd=cwd, env=env)
    try:
        yield
    finally:
        try:
            record(conn, table, run_id, probe.result(timeout=WAIT_SECONDS))
        except sqlite3.Error:
            log.exception("could not record what the run was offered", extra={"run_table": table, "run_id": run_id})


def record(conn: sqlite3.Connection, table: RunTable, run_id: int, offer: AgentOffer) -> None:
    """Record what the runtime said it offers a run, in place of anything recorded before.

    Only what was offered: a server with reach `none` is not, and nor is a denied skill or tool.
    """
    offered = [s for s in offer.servers if s.reach != "none"]
    rules = [(table, run_id, s.server, i, rule) for s in offered for i, rule in enumerate(s.exceptions)]
    with db.transaction(conn):
        records.delete(records.RunOfferedServer).where(_RUN, table, run_id).run(conn)
        records.delete(records.RunOfferedServerRule).where(_RUN, table, run_id).run(conn)
        records.delete(records.RunOfferedSkill).where(_RUN, table, run_id).run(conn)
        records.delete(records.RunOfferedTool).where(_RUN, table, run_id).run(conn)
        records.insert_rows(records.RunOfferedServer, ("run_table", "run_id", "server", "reach")).many(
            conn,
            [(table, run_id, s.server, s.reach) for s in offered],
        )
        records.insert_rows(records.RunOfferedServerRule, ("run_table", "run_id", "server", "position", "rule")).many(
            conn,
            rules,
        )
        records.insert_rows(records.RunOfferedTool, ("run_table", "run_id", "tool")).many(
            conn,
            [(table, run_id, tool) for tool in offer.tools],
        )
        records.insert_rows(records.RunOfferedSkill, ("run_table", "run_id", "skill")).many(
            conn,
            [(table, run_id, skill) for skill in offer.skills],
        )
        records.insert(
            records.RunOffer,
            run_table=table,
            run_id=run_id,
            agent=offer.agent or None,
            error=offer.error,
            asked_at=db.now(),
        ).or_replace().run(conn)


def of_run(conn: sqlite3.Connection, table: RunTable, run_id: int) -> Offered | None:
    """What a run was offered, its servers, skills, and built-in tools by name.

    Returns:
        The ask and what it found; None for a run canopy never asked about.
    """
    asked = records.select(records.RunOffer).where(_RUN, table, run_id).one(conn)
    if asked is None:
        return None
    servers = records.select(records.RunOfferedServer).where(_RUN, table, run_id).order_by("server")
    rules = records.select(records.RunOfferedServerRule).where(_RUN, table, run_id).order_by("server, position")
    skills = records.select(records.RunOfferedSkill).where(_RUN, table, run_id).order_by("skill")
    tools = records.select(records.RunOfferedTool).where(_RUN, table, run_id).order_by("tool")
    server_rules: dict[str, list[str]] = {}
    for rule in rules.all(conn):
        server_rules.setdefault(rule.server, []).append(rule.rule)
    return Offered(
        asked,
        servers.all(conn),
        server_rules,
        skills.all(conn),
        tools.all(conn),
    )
