-- One-off tasks (DESIGN §36, ROADMAP M61): work the operator submits in their own words, about no ticket. A task's
-- submission is its authorization: only the operator's channels write a row here, and `stopped_at` is set once, by
-- `canopy stop task:N`, and never cleared. Rows are never deleted, so a stopped task's runs and spend stay to read.
-- `project` is the tracker project its tickets go in, NULL when the submission names none.
CREATE TABLE tasks (
    id            INTEGER PRIMARY KEY,
    text          TEXT NOT NULL,
    repo          TEXT NOT NULL,
    project       TEXT,
    submitted_at  TEXT NOT NULL,
    channel       TEXT NOT NULL CHECK (channel IN ('cli', 'web')),
    stopped_at    TEXT
);

-- Each run of a task, apart from `runs`, whose ticket and tick a task has neither: the tick that started it, the
-- task's branch, the one slot it leased, and how it ended, with the lifecycle every table of detached runs shares
-- (DESIGN §6). `head` is the commit the branch held on origin once the run's push was verified, NULL when nothing was
-- pushed. `git_link` is what the slot's `.git` file held when `_task` started, as `run_slots.git_link` is a worker's.
-- One run per task at a time, whatever the code asks for.
CREATE TABLE task_runs (
    id                        INTEGER PRIMARY KEY,
    task_id                   INTEGER NOT NULL REFERENCES tasks(id),
    tick_id                   INTEGER NOT NULL REFERENCES ticks(id),
    repo                      TEXT NOT NULL,
    branch                    TEXT NOT NULL,
    head                      TEXT,
    slot_path                 TEXT NOT NULL,
    lease_id                  TEXT NOT NULL,
    lease_holder              TEXT NOT NULL,
    base_branch               TEXT NOT NULL,
    pool                      TEXT NOT NULL CHECK (pool IN ('treehouse', 'canopy')),
    git_link                  BLOB,
    pid                       INTEGER,
    agent_pid                 INTEGER,
    started_at                TEXT NOT NULL,
    ended_at                  TEXT,
    status                    TEXT NOT NULL DEFAULT 'running' CHECK (
        status IN ('running', 'done', 'blocked', 'failed', 'unknown', 'unpushed', 'crashed', 'timeout', 'stopped')
    ),
    result_json               TEXT,
    log_path                  TEXT NOT NULL,
    session_id                TEXT,
    cost_usd                  REAL,
    tokens_input              INTEGER,
    tokens_output             INTEGER,
    tokens_reasoning          INTEGER,
    tokens_cache_read         INTEGER,
    tokens_cache_write        INTEGER,
    tokens_peak_context       INTEGER,
    tokens_first_call         INTEGER,
    tokens_first_cache_write  INTEGER,
    definitions_digest        TEXT
);
CREATE UNIQUE INDEX task_runs_one_running ON task_runs(task_id) WHERE status = 'running';
CREATE INDEX task_runs_task ON task_runs(task_id, id);
CREATE INDEX task_runs_running ON task_runs(status) WHERE status = 'running';
CREATE INDEX task_runs_spent ON task_runs(started_at, cost_usd);
CREATE INDEX task_runs_ended ON task_runs(ended_at);

-- A task run's report and question are messages in the task's conversation (subject `task`, its id), naming their run
-- here: `run_id` names a worker's run, which a task run is not.
ALTER TABLE messages ADD COLUMN task_run_id INTEGER REFERENCES task_runs(id);

-- A task run's tool calls are recorded as any run's are. SQLite cannot change a CHECK in place, so `run_tools` is
-- rebuilt with every row it had; nothing references it.
CREATE TABLE run_tools_0068 (
    run_table     TEXT NOT NULL CHECK (run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs', 'task_runs')),
    run_id        INTEGER NOT NULL,
    tool          TEXT NOT NULL,
    calls         INTEGER NOT NULL,
    errors        INTEGER NOT NULL,
    result_chars  INTEGER NOT NULL,
    PRIMARY KEY (run_table, run_id, tool)
) WITHOUT ROWID;
INSERT INTO run_tools_0068 (run_table, run_id, tool, calls, errors, result_chars)
    SELECT run_table, run_id, tool, calls, errors, result_chars FROM run_tools;
DROP TABLE run_tools;
ALTER TABLE run_tools_0068 RENAME TO run_tools;
