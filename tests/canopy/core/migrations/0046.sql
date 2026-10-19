-- sha256 of 0046_plan_triage.sql: de8e31b7c9e25ed5b25440b7fadacd837fd4b72ad3e2c90c31f2657fd68c0d9c

INSERT INTO run_reads (run_id, repo) VALUES (1, 'repo');
INSERT INTO plan_waivers (ticket_key, run_id, reason, at) VALUES ('OLD-1', 1, 'A typo in a comment.', 'x');
