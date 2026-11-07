-- sha256 of 0012_run_change_counts.sql: c961885c7019967ff1c6d8408349b0abaee03a2cdc538ee8c09578650b3153f1

INSERT INTO run_change_files (run_id, repo, path, added, removed)
VALUES ((SELECT min(id) FROM runs), 'repo', 'a.txt', 3, 1);
INSERT INTO run_change_files (task_run_id, repo, path, old_path)
VALUES ((SELECT min(id) FROM task_runs), 'repo', 'logo.png', 'old.png');
