-- Which models served each agent run (DESIGN §13, Each agent's model), read from the runtime's own record of the run's
-- session after the run ended: a tick's overseer, a worker or plan run, a chore run, or a review run, named by
-- `run_table` and `run_id` as in `run_tools`. Past runs are read too, a few each tick, so no row says a run has none.

-- Each run whose session canopy asked the runtime about, and how its last read ended: `found`, its models in
-- `run_models`; `missing`, the runtime keeps no such session; or `failed`, with canopy's words for why in `error`.
-- `attempts` counts the reads. A `found` or `missing` run is not read again.
CREATE TABLE run_model_reads (
    run_table  TEXT NOT NULL CHECK (run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs')),
    run_id     INTEGER NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('found', 'missing', 'failed')),
    error      TEXT,
    attempts   INTEGER NOT NULL,
    read_at    TEXT NOT NULL,
    PRIMARY KEY (run_table, run_id),
    CHECK ((status = 'failed') = (error IS NOT NULL))
) WITHOUT ROWID;

-- Each model a `found` run's session names as having written its replies: how many it wrote, and what they cost in
-- US dollars, as the runtime priced them. None for a session that made no model call.
CREATE TABLE run_models (
    run_table  TEXT NOT NULL CHECK (run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs')),
    run_id     INTEGER NOT NULL,
    model      TEXT NOT NULL,
    replies    INTEGER NOT NULL,
    cost_usd   REAL NOT NULL,
    PRIMARY KEY (run_table, run_id, model)
) WITHOUT ROWID;
