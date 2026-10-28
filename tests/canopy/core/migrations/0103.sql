-- sha256 of 0103_flaky_kicks.sql: 59bc6f66aca523719404cf573ff344e380bf9f7607e5e7fbdebd0ff04f1e882c

INSERT INTO flaky_kicks (run_id, repo, branch, from_head, to_head, kicked_at)
VALUES (1, 'repo', 'agent/PROJ-1-work', 'a1', 'b2', 'x');
