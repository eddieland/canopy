-- sha256 of 0075_task_reports.sql: 2ee6670fe605d349a95a056132fea4ea655aa6f5310b9288ba6f1df12ac64509

UPDATE task_runs SET report_sha256 = 'abc' WHERE id = (SELECT min(id) FROM task_runs);
INSERT INTO task_tickets (task_id, task_run_id, key, at)
VALUES ((SELECT min(id) FROM tasks), (SELECT min(id) FROM task_runs), 'PROJ-9', 'x');
