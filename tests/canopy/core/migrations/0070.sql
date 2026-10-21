-- sha256 of 0070_task_run_models.sql: adf36c5e1c53c7d3c94c8807375ba239c9ed21f2120d1a6b36db4ecba51e2e5e

INSERT INTO run_model_reads (run_table, run_id, status, error, attempts, read_at)
VALUES ('task_runs', 1, 'found', NULL, 1, 'x');
INSERT INTO run_models (run_table, run_id, model, replies, cost_usd)
VALUES ('task_runs', 1, 'anthropic/claude-x', 2, 0.25);
