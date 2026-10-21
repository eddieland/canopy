-- More of what the runtime offered each agent run (DESIGN §13), beside `run_offers`: the runtime's own tools, and the
-- rules that leave a run only `some` of a server's tools. A run recorded before them has none of either.

-- Each of the runtime's built-in tools a run that said was offered, by name. Its MCP servers' tools are not among them.
CREATE TABLE run_offered_tools (
    run_table  TEXT NOT NULL CHECK (run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs')),
    run_id     INTEGER NOT NULL,
    tool       TEXT NOT NULL,
    PRIMARY KEY (run_table, run_id, tool)
) WITHOUT ROWID;

-- Each rule that makes a server's reach `some`, in the order they apply, the last that matches a tool winning:
-- `offer` or `deny`, then the tool names it matches as the runtime's patterns write them.
CREATE TABLE run_offered_server_rules (
    run_table  TEXT NOT NULL CHECK (run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs')),
    run_id     INTEGER NOT NULL,
    server     TEXT NOT NULL,
    position   INTEGER NOT NULL,
    rule       TEXT NOT NULL,
    PRIMARY KEY (run_table, run_id, server, position)
) WITHOUT ROWID;
