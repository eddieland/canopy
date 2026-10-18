-- Why each `resume` runs (DESIGN §8): one row per reason its dispatch named with `--reason`. The cooldown reads them,
-- holding a `resume` whose only reason is `ci`, and the status views show them beside the run's kind. Other kinds,
-- and runs from before reasons existed, have none.

CREATE TABLE run_reasons (
    run_id  INTEGER NOT NULL REFERENCES runs(id),
    reason  TEXT NOT NULL CHECK (reason IN ('ci', 'review', 'reply', 'conflict', 'no_pr', 'retarget')),
    PRIMARY KEY (run_id, reason)
);
