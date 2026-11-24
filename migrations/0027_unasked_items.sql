-- A checklist item canopy's `pre-push` never asked of a run, since no push it made changed a path the item names, is
-- recorded `unasked`, the harness's, apart from the worker's `n/a` (DESIGN §42). SQLite cannot alter a CHECK, so the
-- table is rebuilt with every row it had, each keeping its rowid, which is its item's place in its list. No table
-- references it, and it has no index but its UNIQUE constraints'.
CREATE TABLE checklist_answers_new (
    run_id       INTEGER REFERENCES runs(id),
    repo         TEXT NOT NULL,
    item         TEXT NOT NULL,
    answer       TEXT NOT NULL CHECK (answer IN ('pass', 'fixed', 'held', 'n/a', 'unanswered', 'unasked')),
    reason       TEXT,
    task_run_id  INTEGER REFERENCES task_runs(id),
    CHECK ((answer = 'held') = (reason IS NOT NULL)),
    CHECK ((run_id IS NULL) != (task_run_id IS NULL)),
    UNIQUE (run_id, repo, item),
    UNIQUE (task_run_id, repo, item)
);
INSERT INTO checklist_answers_new (rowid, run_id, repo, item, answer, reason, task_run_id)
SELECT rowid, run_id, repo, item, answer, reason, task_run_id FROM checklist_answers;
DROP TABLE checklist_answers;
ALTER TABLE checklist_answers_new RENAME TO checklist_answers;
