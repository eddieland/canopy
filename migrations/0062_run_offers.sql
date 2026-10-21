-- What the runtime offered each agent run (DESIGN §13), asked as the run started, by its own command: a tick's
-- overseer, a worker or plan run, a chore run, or a review run, named by `run_table` and `run_id` as in `run_tools`.
-- A run from before canopy asked, or whose command it never ran, has no row.

-- Each run canopy asked about: the agent its command runs, and canopy's words for why the runtime could not say, NULL
-- when it said. `agent` is NULL when the command names none.
CREATE TABLE run_offers (
    run_table  TEXT NOT NULL CHECK (run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs')),
    run_id     INTEGER NOT NULL,
    agent      TEXT,
    error      TEXT,
    asked_at   TEXT NOT NULL,
    PRIMARY KEY (run_table, run_id),
    CHECK (agent IS NOT NULL OR error IS NOT NULL)
) WITHOUT ROWID;

-- Each MCP server a run that said was offered: `all` of its tools or only `some`. A server its config turns off, or
-- whose every tool the agent's rules deny, is not among them.
CREATE TABLE run_offered_servers (
    run_table  TEXT NOT NULL CHECK (run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs')),
    run_id     INTEGER NOT NULL,
    server     TEXT NOT NULL,
    reach      TEXT NOT NULL CHECK (reach IN ('all', 'some')),
    PRIMARY KEY (run_table, run_id, server)
) WITHOUT ROWID;

-- Each skill a run that said was offered, by name.
CREATE TABLE run_offered_skills (
    run_table  TEXT NOT NULL CHECK (run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs')),
    run_id     INTEGER NOT NULL,
    skill      TEXT NOT NULL,
    PRIMARY KEY (run_table, run_id, skill)
) WITHOUT ROWID;
