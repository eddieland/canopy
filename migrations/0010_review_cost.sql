-- What the agent runtime reported about each review run (DESIGN §13, §21): the session it kept, and what the run cost
-- in dollars and tokens, summed over its model calls, as `runs` records for a worker (0002). NULL when the runtime
-- reported none of it, as a `review_cmd` without OpenCode's JSON events does (D071), and on every review run from
-- before this migration.

ALTER TABLE review_runs ADD COLUMN session_id TEXT;
ALTER TABLE review_runs ADD COLUMN cost_usd REAL;
ALTER TABLE review_runs ADD COLUMN tokens_input INTEGER;
ALTER TABLE review_runs ADD COLUMN tokens_output INTEGER;
ALTER TABLE review_runs ADD COLUMN tokens_reasoning INTEGER;
ALTER TABLE review_runs ADD COLUMN tokens_cache_read INTEGER;
ALTER TABLE review_runs ADD COLUMN tokens_cache_write INTEGER;
