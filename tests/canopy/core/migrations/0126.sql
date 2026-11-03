-- sha256 of 0126_epic_runs.sql: e8a27a98d243fa56048e9e12c06385b8c35c0d806b5e4eb955fd4918ede49efc

INSERT INTO epic_runs (id, epic_id, tick_id, desk_path, started_at, status, log_path)
VALUES (1, 1, 1, '/w/desks/init-1', 'x', 'done', '/s/epic-runs/1.log');
INSERT INTO epic_run_slots (run_id, repo, slot_path, lease_id, lease_holder, base_branch, pool)
VALUES (1, 'api', '/w/slots/api-1', 'l1', 'canopy:epic:1', 'main', 'canopy');
INSERT INTO run_model_reads (run_table, run_id, status, error, attempts, read_at, runtime_version)
VALUES ('epic_runs', 1, 'found', NULL, 1, 'x', NULL);
INSERT INTO run_models (run_table, run_id, model, replies, cost_usd)
VALUES ('epic_runs', 1, 'anthropic/claude-x', 2, 0.25);
INSERT INTO run_tools (run_table, run_id, tool, calls, errors, result_chars)
VALUES ('epic_runs', 1, 'read', 2, 0, 120);
INSERT INTO run_reply_models (run_table, run_id, message, model)
VALUES ('epic_runs', 1, 'msg_1', 'anthropic/claude-x');
