-- An epic's plan runs (DESIGN §43): each started by a tick in code, before its overseer, in a desk of a slot per
-- repository the epic names, leased as `canopy:epic:<id>`. An epic has no ticket, so its runs are not
-- `runs` rows; its slots are `epic_run_slots` rows. `message_id` is the newest message about the epic its
-- prompt carried, so a reply after it asks for the next plan. A plan run pushes nothing, so it has no branch or head.
CREATE TABLE epic_runs (
    id                        INTEGER PRIMARY KEY,
    epic_id             INTEGER NOT NULL REFERENCES epics(id),
    tick_id                   INTEGER NOT NULL REFERENCES ticks(id),
    desk_path                 TEXT NOT NULL,
    pid                       INTEGER,
    agent_pid                 INTEGER,
    started_at                TEXT NOT NULL,
    ended_at                  TEXT,
    status                    TEXT NOT NULL DEFAULT 'running' CHECK (
        status IN ('running', 'done', 'blocked', 'failed', 'unknown', 'crashed', 'timeout', 'stopped')
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
    tokens_first_cache_read   INTEGER,
    definitions_digest        TEXT,
    message_id                INTEGER REFERENCES messages(id),
    model                     TEXT,
    tool_calls                INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX epic_runs_of ON epic_runs(epic_id, id);
CREATE INDEX epic_runs_running ON epic_runs(status) WHERE status = 'running';

-- The slots an epic's plan run leased, one per repository, each returned when the run ends or reconcile finds it
-- dead. `git_link` is what the slot's `.git` file held when the run started, as `run_slots.git_link`.
CREATE TABLE epic_run_slots (
    run_id        INTEGER NOT NULL REFERENCES epic_runs(id),
    repo          TEXT NOT NULL,
    slot_path     TEXT NOT NULL,
    lease_id      TEXT NOT NULL,
    lease_holder  TEXT NOT NULL,
    base_branch   TEXT NOT NULL,
    pool          TEXT NOT NULL CHECK (pool IN ('treehouse', 'canopy')),
    git_link      BLOB,
    PRIMARY KEY (run_id, repo)
);

-- Their models, tool calls, and replies are read as every other agent run's are (DESIGN §13). SQLite cannot change a
-- CHECK in place, so each table naming a run table is rebuilt with every row it had, `epic_runs` added; nothing
-- references them.
CREATE TABLE run_model_reads_0125 (
    run_table        TEXT NOT NULL CHECK (
        run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs', 'task_runs', 'epic_runs')
    ),
    run_id           INTEGER NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('found', 'missing', 'failed')),
    error            TEXT,
    attempts         INTEGER NOT NULL,
    read_at          TEXT NOT NULL,
    runtime_version  TEXT,
    PRIMARY KEY (run_table, run_id),
    CHECK ((status = 'failed') = (error IS NOT NULL))
) WITHOUT ROWID;
INSERT INTO run_model_reads_0125 (run_table, run_id, status, error, attempts, read_at, runtime_version)
    SELECT run_table, run_id, status, error, attempts, read_at, runtime_version FROM run_model_reads;
DROP TABLE run_model_reads;
ALTER TABLE run_model_reads_0125 RENAME TO run_model_reads;

CREATE TABLE run_models_0125 (
    run_table  TEXT NOT NULL CHECK (
        run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs', 'task_runs', 'epic_runs')
    ),
    run_id     INTEGER NOT NULL,
    model      TEXT NOT NULL,
    replies    INTEGER NOT NULL,
    cost_usd   REAL NOT NULL,
    PRIMARY KEY (run_table, run_id, model)
) WITHOUT ROWID;
INSERT INTO run_models_0125 (run_table, run_id, model, replies, cost_usd)
    SELECT run_table, run_id, model, replies, cost_usd FROM run_models;
DROP TABLE run_models;
ALTER TABLE run_models_0125 RENAME TO run_models;

CREATE TABLE run_tools_0125 (
    run_table     TEXT NOT NULL CHECK (
        run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs', 'task_runs', 'epic_runs')
    ),
    run_id        INTEGER NOT NULL,
    tool          TEXT NOT NULL,
    calls         INTEGER NOT NULL,
    errors        INTEGER NOT NULL,
    result_chars  INTEGER NOT NULL,
    PRIMARY KEY (run_table, run_id, tool)
) WITHOUT ROWID;
INSERT INTO run_tools_0125 (run_table, run_id, tool, calls, errors, result_chars)
    SELECT run_table, run_id, tool, calls, errors, result_chars FROM run_tools;
DROP TABLE run_tools;
ALTER TABLE run_tools_0125 RENAME TO run_tools;

CREATE TABLE run_reply_models_0125 (
    run_table  TEXT NOT NULL CHECK (
        run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs', 'task_runs', 'epic_runs')
    ),
    run_id     INTEGER NOT NULL,
    message    TEXT NOT NULL,
    model      TEXT NOT NULL,
    PRIMARY KEY (run_table, run_id, message)
) WITHOUT ROWID;
INSERT INTO run_reply_models_0125 (run_table, run_id, message, model)
    SELECT run_table, run_id, message, model FROM run_reply_models;
DROP TABLE run_reply_models;
ALTER TABLE run_reply_models_0125 RENAME TO run_reply_models;
