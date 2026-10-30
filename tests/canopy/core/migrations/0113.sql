-- sha256 of 0113_overseer_runs.sql: d2ccc351568b11cd4b555613573b4b0cfada2ee39965d237fae362f1b180f7fc

INSERT INTO overseer_runs (tick_id, subject, started_at, ended_at, status, failure, session_id, cost_usd)
VALUES ((SELECT min(id) FROM ticks), NULL, 'x', 'y', 'failed', 'overseer exited 1', 'ses_o1', 0.25);
