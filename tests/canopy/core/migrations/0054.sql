-- sha256 of 0054_run_models.sql: 3db7e46cb3fc267e17281a2b10ca4fd19994e0af6f5ed81086504e05740eda3c

INSERT INTO run_model_reads (run_table, run_id, status, error, attempts, read_at)
VALUES ('runs', 1, 'found', NULL, 1, 'x');
INSERT INTO run_models (run_table, run_id, model, replies, cost_usd) VALUES ('runs', 1, 'anthropic/claude-x', 4, 0.5);
