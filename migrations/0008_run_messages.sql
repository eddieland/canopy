-- The operator's message to a running worker's, planner's, or one-off task's run (DESIGN §44): an operator message on
-- the run's subject, as any reply is, naming the run it was sent to, a ticket's in `to_run_id` and a task's in
-- `to_task_run_id`. `delivered_at` is when canopy first wrote it where the run's agent reads it, its answers
-- directory, and `fetched_at` when the agent first read it there, through canopy's `messages` tool. NULL for every
-- other message, and for every message from before this migration.
ALTER TABLE messages ADD COLUMN to_run_id INTEGER REFERENCES runs(id);
ALTER TABLE messages ADD COLUMN to_task_run_id INTEGER REFERENCES task_runs(id);
ALTER TABLE messages ADD COLUMN delivered_at TEXT;
ALTER TABLE messages ADD COLUMN fetched_at TEXT;
-- The messages a run fetched, which the loop reads past once that run reports (DESIGN §44), found without a scan.
CREATE INDEX messages_fetched ON messages(fetched_at) WHERE fetched_at IS NOT NULL;
