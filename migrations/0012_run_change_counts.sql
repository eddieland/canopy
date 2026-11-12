-- How much a worker's or a task's run changed in one repository (DESIGN §45), counted by the harness's `git diff
-- --numstat` of the run's own change as it ended, so a run's page and its ticket's runs list name it without reading
-- a kept diff. On `run_changes`, the totals: how many files it touched and how many lines it added and removed, a
-- binary file's lines counting none; NULL when canopy counted nothing, as for a run with no commit to count to, one
-- whose count failed, and every row from before this migration. `run_change_files` holds the files counted, a row
-- each, at most a review diff's many: its path, its old path when git found it renamed, and its lines added and
-- removed, NULL for a binary file. A row names the run in `run_id` or the task run in `task_run_id`, never both, as a
-- `run_changes` row does, and is never removed (§26).
ALTER TABLE run_changes ADD COLUMN files_changed INTEGER;
ALTER TABLE run_changes ADD COLUMN lines_added INTEGER;
ALTER TABLE run_changes ADD COLUMN lines_removed INTEGER;

CREATE TABLE run_change_files (
    run_id          INTEGER REFERENCES runs(id),
    task_run_id     INTEGER REFERENCES task_runs(id),
    repo            TEXT NOT NULL,
    path            TEXT NOT NULL,
    old_path        TEXT,
    added           INTEGER,
    removed         INTEGER,
    CHECK ((run_id IS NULL) != (task_run_id IS NULL))
);

CREATE INDEX run_change_files_by_run ON run_change_files (run_id);
CREATE INDEX run_change_files_by_task_run ON run_change_files (task_run_id);
