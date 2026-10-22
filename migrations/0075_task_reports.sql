-- What a one-off task leaves (DESIGN §36, ROADMAP M61): a run's report is a file in the state directory, as a plan
-- is, and the journal holds its hash as `_task` kept it, never its text. NULL when the run left none.
ALTER TABLE task_runs ADD COLUMN report_sha256 TEXT;

-- The tickets a task's runs reported filing in the project its submission names, each checked on its text alone
-- (D003). A row authorizes nothing: it names no ticket canopy works, and only the operator's label or start does.
CREATE TABLE task_tickets (
    id           INTEGER PRIMARY KEY,
    task_id      INTEGER NOT NULL REFERENCES tasks(id),
    task_run_id  INTEGER NOT NULL REFERENCES task_runs(id),
    key          TEXT NOT NULL,
    at           TEXT NOT NULL,
    UNIQUE (task_id, key)
);
CREATE INDEX task_tickets_run ON task_tickets(task_run_id);
