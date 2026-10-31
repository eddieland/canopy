-- sha256 of 0115_task_checklist_answers.sql: 0a802ead5523fd4a5ceb7aabc044690dd7db8ba9616a0169e7034d6c8b5d1408

-- Rebuilds checklist_answers, which keeps the row 0112 seeded, a worker run's; this one is a task run's.
INSERT INTO checklist_answers (repo, item, answer, reason, task_run_id)
VALUES ('repo', 'newspaper', 'fixed', NULL, (SELECT min(id) FROM task_runs));
