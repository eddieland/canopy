-- sha256 of 0028_compactions_and_limits.sql: 524e3df52cb9cf94fda6fa4765f63bb71e413b7c69200d086cfef9b8e1a2aafc

-- Adds columns to two tables and creates `model_limits`: a model listed with both its limits.
INSERT INTO model_limits (model, input_limit, context_limit, listed_at)
VALUES ('github-copilot/claude-opus-4.8-fast', 168000, 200000, '2026-11-25T10:00:00Z');
