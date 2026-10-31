-- sha256 of 0114_task_checklist_answers.sql: 1f9a231292cd38b4e8b6c7b11f57aa3596d2f8a08a7d8cc69dfb7629855abaf8

-- Rebuilds checklist_answers, which keeps the row 0112 seeded, a worker run's; this one is a task run's.
INSERT INTO checklist_answers (repo, item, answer, reason, task_run_id)
VALUES ('repo', 'newspaper', 'fixed', NULL, (SELECT min(id) FROM task_runs));
