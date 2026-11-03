-- sha256 of 0125_initiative_runs.sql: 6769f46e1e8dba200c84898ff8f9c8aaa931500640d03454107abb97bb8fe870

INSERT INTO initiative_runs (id, initiative_id, tick_id, desk_path, started_at, status, log_path)
VALUES (1, 1, 1, '/w/desks/init-1', 'x', 'done', '/s/initiative-runs/1.log');
INSERT INTO initiative_run_slots (run_id, repo, slot_path, lease_id, lease_holder, base_branch, pool)
VALUES (1, 'api', '/w/slots/api-1', 'l1', 'canopy:init:1', 'main', 'canopy');
INSERT INTO run_model_reads (run_table, run_id, status, error, attempts, read_at, runtime_version)
VALUES ('initiative_runs', 1, 'found', NULL, 1, 'x', NULL);
INSERT INTO run_models (run_table, run_id, model, replies, cost_usd)
VALUES ('initiative_runs', 1, 'anthropic/claude-x', 2, 0.25);
INSERT INTO run_tools (run_table, run_id, tool, calls, errors, result_chars)
VALUES ('initiative_runs', 1, 'read', 2, 0, 120);
INSERT INTO run_reply_models (run_table, run_id, message, model)
VALUES ('initiative_runs', 1, 'msg_1', 'anthropic/claude-x');
