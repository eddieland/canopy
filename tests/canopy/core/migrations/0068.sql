-- sha256 of 0068_tasks.sql: 200c7b783bf3b832beee520fe529a1e2d74995996a4a2c679e2c7e40572701bf

INSERT INTO tasks (id, text, repo, project, submitted_at, channel)
VALUES (1, 'Explore the cache.', 'repo', NULL, 'x', 'cli');
INSERT INTO task_runs (
    id, task_id, tick_id, repo, branch, slot_path, lease_id, lease_holder, base_branch, pool, started_at, log_path
)
VALUES (1, 1, 1, 'repo', 'agent/task/1', '/s', 'l1', 'canopy:task:1', 'main', 'canopy', 'x', '/t/1.log');
INSERT INTO messages (subject_kind, subject_id, at, source, kind, channel, body, task_run_id)
VALUES ('task', '1', 'x', 'worker', 'report', 'run', 'Found it.', 1);
INSERT INTO run_tools (run_table, run_id, tool, calls, errors, result_chars) VALUES ('task_runs', 1, 'bash', 2, 0, 40);
