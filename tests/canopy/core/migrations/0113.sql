-- sha256 of 0113_overseer_runs.sql: 7b5ebab2d2435ad787156a705bc6c369a4f4b815d7082c9ab1d0e737c9d3c716

INSERT INTO overseer_runs (tick_id, subject, started_at, ended_at, status, failure, session_id, cost_usd)
VALUES ((SELECT min(id) FROM ticks), NULL, 'x', 'y', 'failed', 'overseer exited 1', 'ses_o1', 0.25);
