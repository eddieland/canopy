-- A task's runs (DESIGN §36) have their models read as every other agent run's are (DESIGN §13, Each agent's model).
-- SQLite cannot change a CHECK in place, so `run_model_reads` and `run_models` are rebuilt with every row they had,
-- their `run_table` naming `task_runs` too; nothing references them.
CREATE TABLE run_model_reads_0070 (
    run_table  TEXT NOT NULL CHECK (run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs', 'task_runs')),
    run_id     INTEGER NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('found', 'missing', 'failed')),
    error      TEXT,
    attempts   INTEGER NOT NULL,
    read_at    TEXT NOT NULL,
    PRIMARY KEY (run_table, run_id),
    CHECK ((status = 'failed') = (error IS NOT NULL))
) WITHOUT ROWID;
INSERT INTO run_model_reads_0070 (run_table, run_id, status, error, attempts, read_at)
    SELECT run_table, run_id, status, error, attempts, read_at FROM run_model_reads;
DROP TABLE run_model_reads;
ALTER TABLE run_model_reads_0070 RENAME TO run_model_reads;

CREATE TABLE run_models_0070 (
    run_table  TEXT NOT NULL CHECK (run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs', 'task_runs')),
    run_id     INTEGER NOT NULL,
    model      TEXT NOT NULL,
    replies    INTEGER NOT NULL,
    cost_usd   REAL NOT NULL,
    PRIMARY KEY (run_table, run_id, model)
) WITHOUT ROWID;
INSERT INTO run_models_0070 (run_table, run_id, model, replies, cost_usd)
    SELECT run_table, run_id, model, replies, cost_usd FROM run_models;
DROP TABLE run_models;
ALTER TABLE run_models_0070 RENAME TO run_models;
