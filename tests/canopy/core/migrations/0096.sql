-- sha256 of 0096_runtime_sessions.sql: 9457797a9f5e6ce1b23c1159dc386aba5a47f3e758a643829487d3c50ac8da85

INSERT INTO runtime_sessions (
    session_id, parent_id, directory, started_at, updated_at, updated_ms, cost_usd, tokens_input, tokens_output,
    tokens_reasoning, tokens_cache_read, tokens_cache_write, read_at
) VALUES ('ses_1', NULL, '/work/api', 'x', 'x', 1, 0.5, 1, 2, 3, 4, 5, 'x');
INSERT INTO runtime_session_models (session_id, model, replies, cost_usd)
VALUES ('ses_1', 'anthropic/claude-x', 2, 0.5);
INSERT INTO runtime_session_reads (id, cursor_updated_ms, cursor_session_id, status, error, skipped, read_at)
VALUES (1, 1, 'ses_1', 'found', NULL, 0, 'x');
