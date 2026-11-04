-- The pushes a worker's or a task's run made after canopy showed it a checklist (DESIGN §42): the commit its branch
-- was at when canopy's `pre-push` held the push, or printed the list in the run's last stretch, and the commit of the
-- next push it let through, so the diff between them is what the run changed after being shown the list. A hold the
-- run never pushed after is closed by the commit the run left on origin. The commits are what the hook wrote in the
-- slot's own git directory, untrusted and checked to be commit ids; the diff between them, kept beside the run's log,
-- is all that names what changed, since the held commit may never reach origin. A row names the run in `run_id` or
-- the task run in `task_run_id`, never both, and a row's rowid is the order the run was shown its lists.
CREATE TABLE checklist_pushes (
    run_id       INTEGER REFERENCES runs(id),
    task_run_id  INTEGER REFERENCES task_runs(id),
    repo         TEXT NOT NULL,
    shown_sha    TEXT NOT NULL,
    pushed_sha   TEXT NOT NULL,
    CHECK ((run_id IS NULL) != (task_run_id IS NULL))
);

CREATE INDEX checklist_pushes_by_run ON checklist_pushes (run_id);
CREATE INDEX checklist_pushes_by_task_run ON checklist_pushes (task_run_id);
