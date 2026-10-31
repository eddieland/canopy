-- A one-off task's run answers its repository's checklist too (DESIGN §36, §42), as a worker run does: its answers are
-- kept with the worker runs', so `canopy checklist` counts them together, each row naming the run in `run_id` or the
-- task run in `task_run_id`, never both. SQLite cannot drop a NOT NULL or a primary key in place, so
-- `checklist_answers` is rebuilt with every row it had, each keeping its rowid, by which an item's list order is read;
-- nothing references it, and it has no index.
CREATE TABLE checklist_answers_0114 (
    run_id       INTEGER REFERENCES runs(id),
    repo         TEXT NOT NULL,
    item         TEXT NOT NULL,
    answer       TEXT NOT NULL CHECK (answer IN ('pass', 'fixed', 'held', 'n/a', 'unanswered')),
    reason       TEXT,
    task_run_id  INTEGER REFERENCES task_runs(id),
    CHECK ((answer = 'held') = (reason IS NOT NULL)),
    CHECK ((run_id IS NULL) != (task_run_id IS NULL)),
    UNIQUE (run_id, repo, item),
    UNIQUE (task_run_id, repo, item)
);
INSERT INTO checklist_answers_0114 (rowid, run_id, repo, item, answer, reason)
    SELECT rowid, run_id, repo, item, answer, reason FROM checklist_answers;
DROP TABLE checklist_answers;
ALTER TABLE checklist_answers_0114 RENAME TO checklist_answers;
