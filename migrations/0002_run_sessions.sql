-- What the agent runtime reported about each worker run (DESIGN §11, §13): the session it kept, and what the run cost
-- in dollars and tokens, summed over its model calls. NULL when the runtime reported none of it, as a command template
-- without OpenCode's JSON events does (D071), and on every run from before this migration.

ALTER TABLE runs ADD COLUMN session_id TEXT;
ALTER TABLE runs ADD COLUMN cost_usd REAL;
ALTER TABLE runs ADD COLUMN tokens_input INTEGER;
ALTER TABLE runs ADD COLUMN tokens_output INTEGER;
ALTER TABLE runs ADD COLUMN tokens_reasoning INTEGER;
ALTER TABLE runs ADD COLUMN tokens_cache_read INTEGER;
ALTER TABLE runs ADD COLUMN tokens_cache_write INTEGER;
