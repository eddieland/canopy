-- sha256 of 0068_tasks.sql: 776a394a5408d7fca6d5dfce7419277cb3cc420669c58b10c8a71f79235f6cbc

INSERT INTO tasks (text, repo, project, channel, submitted_at)
VALUES ('Find out why the build is slow.', 'repo', 'PROJ', 'cli', 'x');

INSERT INTO task_runs (
    task_id, tick_id, branch, repo, slot_path, lease_id, lease_holder, base_branch, pool, started_at, status, log_path
)
VALUES (
    (SELECT min(id) FROM tasks), (SELECT min(id) FROM ticks), 'agent/task/1', 'repo', '/pool/1/repo', 'l1',
    'canopy:task:1', 'main', 'treehouse', 'x', 'done', 'l'
);
