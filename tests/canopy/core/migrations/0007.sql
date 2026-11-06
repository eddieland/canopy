-- sha256 of 0007_run_changes.sql: dbe48f199fd3f2a8d6308791e2826541a86fedbdc4c0d47aa51212a525562095

INSERT INTO run_changes (run_id, repo, start_sha, end_sha, merge_base_sha, change_kept, branch_kept)
VALUES ((SELECT min(id) FROM runs), 'repo', 'a1', 'b2', 'a1', 1, 1);
INSERT INTO run_changes (task_run_id, repo, start_sha, start_on_base, missing)
VALUES ((SELECT min(id) FROM task_runs), 'repo', 'c3', 1, 'the run left no branch on origin');
