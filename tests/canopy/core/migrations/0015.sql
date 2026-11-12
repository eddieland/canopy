-- sha256 of 0015_run_commits.sql: 712c308fd82fe32a232174df280cbb2bfc28efcd7778c98e00b1cfffa7dc70ae

INSERT INTO run_commits (run_id, repo, position, sha, subject, canopy_trailer, prefixed, harness_pushed)
VALUES ((SELECT min(id) FROM runs), 'repo', 0, 'b2', 'PROJ-1: a change', 1, 1, 1);
INSERT INTO run_commits (task_run_id, repo, position, sha, subject, runtime_trailer)
VALUES ((SELECT min(id) FROM task_runs), 'repo', 0, 'c3', 'a task''s change', 1);
