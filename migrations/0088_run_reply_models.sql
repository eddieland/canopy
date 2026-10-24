-- The model that wrote each reply of a run more than one model served (DESIGN §13, Each agent's model), read from the
-- runtime's record of the run's session with `run_models`, so its transcript names the model of each call. A reply is
-- the runtime's `message`, which each event of the call that wrote it names in the run's log; `model` is named as
-- `run_models.model` names it. None for a run one model served, which `run_models` names.
CREATE TABLE run_reply_models (
    run_table  TEXT NOT NULL CHECK (run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs', 'task_runs')),
    run_id     INTEGER NOT NULL,
    message    TEXT NOT NULL,
    model      TEXT NOT NULL,
    PRIMARY KEY (run_table, run_id, message)
) WITHOUT ROWID;

-- Read again each run more than one model served, so its replies' models are recorded. Its models stay, and are shown,
-- till a read that finds the session replaces them; one that fails or finds the session gone keeps them.
DELETE FROM run_model_reads
WHERE status = 'found'
    AND (run_table, run_id) IN (
        SELECT run_table, run_id FROM run_models GROUP BY run_table, run_id HAVING count(*) > 1
    );
