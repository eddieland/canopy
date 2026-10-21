-- One-off tasks (DESIGN §36): work the operator hands canopy in their own words, about no ticket. Only the operator's
-- channels write a row, refused inside a tick or any run: the submission is the authorization, and its text their
-- instruction. A task is stopped, never deleted, so its runs stay to read. `repo` is the repository it runs in, by its
-- name in the map; `project` the tracker project its tickets may go in, NULL for none.
CREATE TABLE tasks (
    id            INTEGER PRIMARY KEY,
    text          TEXT NOT NULL,
    repo          TEXT NOT NULL,
    project       TEXT,
    channel       TEXT NOT NULL CHECK (channel IN ('cli', 'web')),
    submitted_at  TEXT NOT NULL,
    stopped_at    TEXT
);

-- A task's runs, each started by a tick before its overseer, in a slot of the task's repository's pool leased as
-- `canopy:task:<id>`. A task has no ticket, so its runs are not `runs` rows. `branch` is `<branch_prefix>task/<id>`,
-- a shape no ticket's branch takes; `head` the commit it was at on origin when the run ended, NULL when nothing was
-- pushed. `git_link` is what the slot's `.git` file held when the run started, as `run_slots.git_link`.
CREATE TABLE task_runs (
    id                        INTEGER PRIMARY KEY,
    task_id                   INTEGER NOT NULL REFERENCES tasks(id),
    tick_id                   INTEGER NOT NULL REFERENCES ticks(id),
    branch                    TEXT NOT NULL,
    repo                      TEXT NOT NULL,
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
    head                      TEXT,
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
CREATE INDEX task_runs_task ON task_runs(task_id, started_at);
CREATE INDEX task_runs_running ON task_runs(status) WHERE status = 'running';
-- What `canopy spend` and `health` read a window of, as `runs_spent` (migration 0022).
CREATE INDEX task_runs_spent ON task_runs(started_at, cost_usd);
