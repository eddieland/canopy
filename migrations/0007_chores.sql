-- Chores (DESIGN §19, ROADMAP M9): recurring agent runs the operator defines and the overseer delegates. A chore run
-- holds no slot and works on no ticket, so it is not a `runs` row. Its result is a summary and findings, kept as the
-- validated result in `result_json`.
CREATE TABLE chore_runs (
    id           INTEGER PRIMARY KEY,
    tick_id      INTEGER NOT NULL REFERENCES ticks(id),
    chore        TEXT NOT NULL,
    pid          INTEGER,           -- canopy _chore
    agent_pid    INTEGER,           -- the chore's agent, which leads its own process group
    started_at   TEXT NOT NULL,
    ended_at     TEXT,
    status       TEXT NOT NULL DEFAULT 'running',  -- running | ok | failed | unknown | timeout | crashed
    result_json  TEXT,
    log_path     TEXT NOT NULL
);
CREATE INDEX chore_runs_chore ON chore_runs(chore, started_at);
CREATE INDEX chore_runs_running ON chore_runs(status) WHERE status = 'running';

-- A decision about a chore carries its name and no ticket key: `dispatch:chore`, `wait`, `refused:<guard>`, and the
-- harness's `attention:chore_failed`.
ALTER TABLE decisions ADD COLUMN chore TEXT;
