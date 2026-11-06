-- What a worker's or a task's run changed in one repository (DESIGN §45), read by the harness from the run's slot as it
-- ended, after its push and before a flaky kick: the commit it started from, origin's branch then or, when origin had
-- no branch, the base's commit (`start_on_base`); the commit it left on origin, NULL when origin has no branch; and the
-- merge base of the diffed commit with the base as the slot last fetched it. A slot the run left unpushed names the
-- last commit the run made there in `unpushed_sha`, whose diffs are kept as work not on origin; NULL for a slot that
-- pushed. Two diffs are kept beside the run's log, the run's own change and the branch against its base, and
-- `change_kept` and `branch_kept` say whether each was; `missing` says why one was not. A run that crashed before any
-- git ran in its slot has a row with no commits and `missing` saying so. A row names the run in `run_id` or the task
-- run in `task_run_id`, never both, and is never removed (§26).
CREATE TABLE run_changes (
    run_id          INTEGER REFERENCES runs(id),
    task_run_id     INTEGER REFERENCES task_runs(id),
    repo            TEXT NOT NULL,
    start_sha       TEXT,
    start_on_base   INTEGER NOT NULL DEFAULT 0,
    end_sha         TEXT,
    merge_base_sha  TEXT,
    unpushed_sha    TEXT,
    change_kept     INTEGER NOT NULL DEFAULT 0,
    branch_kept     INTEGER NOT NULL DEFAULT 0,
    missing         TEXT,
    CHECK ((run_id IS NULL) != (task_run_id IS NULL))
);

CREATE INDEX run_changes_by_run ON run_changes (run_id);
CREATE INDEX run_changes_by_task_run ON run_changes (task_run_id);
