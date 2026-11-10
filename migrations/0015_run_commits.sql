-- The commits in what a worker's or a task's run changed in one repository (DESIGN §45), read by the harness's `git
-- log` of the run's range as it ended, after its push and before a flaky kick: those the commit its diff is of holds
-- that neither the commit it started from nor its base, as the slot last fetched it, does. `run_changes.commit_count`
-- is how many there were, NULL when canopy read none, as for a run with no commit to read to, one whose read failed,
-- and every row from before this migration. `run_commits` holds them, a row each, at most the newest
-- `run_changes.MAX_COMMITS`, in order from the oldest at `position` 0: its id; its subject, the branch's text, cut and
-- every hidden character named; whether it carries canopy's trailers, and its prefix, each NULL when the run's marks
-- named none (TRUST_MODEL T5), a fixup counting as prefixed; whether it carries a `Co-authored-by` trailer not
-- canopy's, as the runtime's own attribution is; and whether the harness's own push after the worker, not the worker,
-- put it on origin. A row names the run in `run_id` or the task run in `task_run_id`, never both, as a `run_changes`
-- row does, and is never removed (§26).
ALTER TABLE run_changes ADD COLUMN commit_count INTEGER;

CREATE TABLE run_commits (
    run_id           INTEGER REFERENCES runs(id),
    task_run_id      INTEGER REFERENCES task_runs(id),
    repo             TEXT NOT NULL,
    position         INTEGER NOT NULL,
    sha              TEXT NOT NULL,
    subject          TEXT NOT NULL,
    canopy_trailer   INTEGER,
    prefixed         INTEGER,
    runtime_trailer  INTEGER NOT NULL DEFAULT 0,
    harness_pushed   INTEGER NOT NULL DEFAULT 0,
    CHECK ((run_id IS NULL) != (task_run_id IS NULL))
);

CREATE INDEX run_commits_by_run ON run_commits (run_id);
CREATE INDEX run_commits_by_task_run ON run_commits (task_run_id);
