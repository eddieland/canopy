-- sha256 of 0004_checklist_pushes.sql: 4cd8ed8b6d6016aa8b2291ae305741161b57a8fa977f021ac70dcc4c474d63af

INSERT INTO checklist_pushes (run_id, repo, shown_sha, pushed_sha)
VALUES ((SELECT min(id) FROM runs), 'repo', 'a1', 'b2');
INSERT INTO checklist_pushes (task_run_id, repo, shown_sha, pushed_sha)
VALUES ((SELECT min(id) FROM task_runs), 'repo', 'c3', 'd4');
