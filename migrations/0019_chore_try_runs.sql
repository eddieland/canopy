-- A chore run the operator started by hand (`canopy chore try`, DESIGN §19) has no tick, so `chore_runs.tick_id`
-- becomes nullable: NULL is a try, a number the tick whose overseer started the run. SQLite cannot drop a NOT NULL
-- constraint in place, so the table is rebuilt with every row and column it had. Nothing references `chore_runs`.

CREATE TABLE chore_runs_new (
    id                  INTEGER PRIMARY KEY,
    tick_id             INTEGER REFERENCES ticks(id),  -- NULL for a run the operator started with `canopy chore try`
    chore               TEXT NOT NULL,
    pid                 INTEGER,           -- canopy _chore, or the `canopy chore try` running it in the foreground
    agent_pid           INTEGER,           -- the chore's agent, which leads its own process group
    started_at          TEXT NOT NULL,
    ended_at            TEXT,
    status              TEXT NOT NULL DEFAULT 'running',  -- running | ok | failed | unknown | timeout | crashed
    result_json         TEXT,
    log_path            TEXT NOT NULL,
    session_id          TEXT,
    cost_usd            REAL,
    tokens_input        INTEGER,
    tokens_output       INTEGER,
    tokens_reasoning    INTEGER,
    tokens_cache_read   INTEGER,
    tokens_cache_write  INTEGER
);
INSERT INTO chore_runs_new (
    id, tick_id, chore, pid, agent_pid, started_at, ended_at, status, result_json, log_path, session_id, cost_usd,
    tokens_input, tokens_output, tokens_reasoning, tokens_cache_read, tokens_cache_write
)
SELECT
    id, tick_id, chore, pid, agent_pid, started_at, ended_at, status, result_json, log_path, session_id, cost_usd,
    tokens_input, tokens_output, tokens_reasoning, tokens_cache_read, tokens_cache_write
FROM chore_runs;
DROP TABLE chore_runs;
ALTER TABLE chore_runs_new RENAME TO chore_runs;
CREATE INDEX chore_runs_chore ON chore_runs(chore, started_at);
CREATE INDEX chore_runs_running ON chore_runs(status) WHERE status = 'running';
