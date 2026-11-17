"""What the mock journal's agent runs were offered of MCP servers and tools (DESIGN §13), for the Tools report.

Each run the runtime answered for (`skill_use`) is offered what its agent's definition leaves it. The overseer reads
the tracker's server and the forge's. A worker has the runtime's own tools, the forge's
server, the tracker's, and an error tracker's that no run calls, which is the page's finding: a server offered run
after run and never called. A planner and a reviewer are offered only some of the forge's tools, by their rules, and
no tool that writes. What the runs called is the calls the other fixtures recorded, so a tool offered and never called,
as `glob` and `grep` are, is one this fixture offers and none of them names.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from canopy.core import records
from canopy.runtime import agents

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping, Sequence

#: The runtime's own tools an agent that reads is offered, and those one that writes is offered besides.
_READS: Final = ("bash", "glob", "grep", "read", "skill")
_WRITES: Final = (*_READS, "edit", "write")
#: What each agent's runs are offered: its servers, each with its reach, and the runtime's own tools.
_OFFERED: Final[Mapping[str, tuple[Mapping[str, str], Sequence[str]]]] = {
    agents.OVERSEER: ({"github": "all", "jira": "all"}, ("bash",)),
    agents.WORKER: ({"github": "all", "jira": "all", "sentry": "all"}, _WRITES),
    agents.PRIVATE_WORKER: ({"jira": "all", "sentry": "all"}, _WRITES),
    agents.PLANNER: ({"github": "some", "jira": "all"}, _READS),
    agents.REVIEWER: ({"github": "some", "jira": "all"}, _READS),
    agents.CHORE: ({"github": "all"}, _WRITES),
}


def seed(conn: sqlite3.Connection) -> None:
    """Record the servers and tools each run the runtime answered for was offered, by the agent its offer names.

    After `skill_use.seed`, which records the offers themselves.
    """
    answered = records.select(records.RunOffer).where("error IS NULL").all(conn)
    servers: list[tuple[str, int, str, str]] = []
    tools: list[tuple[str, int, str]] = []
    for offer in answered:
        # A chore's copy of the chores' agent is offered what the chores' is.
        reach, own = _OFFERED.get(offer.agent or "", _OFFERED[agents.CHORE])
        servers += [(offer.run_table, offer.run_id, name, some) for name, some in reach.items()]
        tools += [(offer.run_table, offer.run_id, tool) for tool in own]
    records.insert_rows(records.RunOfferedServer, ("run_table", "run_id", "server", "reach")).many(conn, servers)
    records.insert_rows(records.RunOfferedTool, ("run_table", "run_id", "tool")).many(conn, tools)
