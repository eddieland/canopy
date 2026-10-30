-- A one-off task's run keeps its agent's progress, its card, as a worker's, planner's, and reviewer's runs do (DESIGN
-- §41): the columns 0105, 0106, and 0107 gave `runs` and `review_runs`, read and written the same way. A task's run
-- asks no question on its card, so its question's three stay NULL. NULL, and 0 calls, on a run that never called
-- `status`, and on every run from before this migration.
ALTER TABLE task_runs ADD COLUMN card_json TEXT;
ALTER TABLE task_runs ADD COLUMN card_at TEXT;
ALTER TABLE task_runs ADD COLUMN card_calls INTEGER;
ALTER TABLE task_runs ADD COLUMN tool_calls INTEGER NOT NULL DEFAULT 0;
ALTER TABLE task_runs ADD COLUMN card_working_since TEXT;
ALTER TABLE task_runs ADD COLUMN card_asked_at TEXT;
ALTER TABLE task_runs ADD COLUMN card_answer TEXT CHECK (card_answer IN ('A', 'B', 'C', 'D', 'E'));
ALTER TABLE task_runs ADD COLUMN card_answered_at TEXT;
