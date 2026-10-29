-- Each running agent's status card (DESIGN §8, §27, ROADMAP M65): where a worker's, planner's, or reviewer's work
-- stands, as it last told canopy's `status` tool, read from the call it printed. The run is named by `run_table` and
-- `run_id`, as in `run_tools`: a worker or plan run in `runs`, or a review in `review_runs`. Each call replaces the
-- whole card, and the run keeps its last one after it ends. It is the agent's text, shown to the operator and to no
-- agent.
-- `done` is a JSON array of `{"what", "proof"}`, and `next` of strings. `calls_since` counts the tool calls the run
-- made after it, so a card says how old it is in calls as in minutes.
CREATE TABLE run_cards (
    run_table   TEXT NOT NULL CHECK (run_table IN ('runs', 'review_runs')),
    run_id      INTEGER NOT NULL,
    summary     TEXT NOT NULL,
    now         TEXT NOT NULL,
    done        TEXT NOT NULL CHECK (json_valid(done)),
    next        TEXT NOT NULL CHECK (json_valid(next)),
    stuck       TEXT,
    updated_at  TEXT NOT NULL,
    calls_since INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (run_table, run_id)
) WITHOUT ROWID;
