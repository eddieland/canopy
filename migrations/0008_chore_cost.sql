-- What the agent runtime reported about each chore run (DESIGN §13, §19): the session it kept, and what the run cost in
-- dollars and tokens, summed over its model calls, as `runs` records for a worker (0002). NULL when the runtime
-- reported none of it, as a chore `cmd` without OpenCode's JSON events does (D071), and on every chore run from before
-- this migration.

ALTER TABLE chore_runs ADD COLUMN session_id TEXT;
ALTER TABLE chore_runs ADD COLUMN cost_usd REAL;
ALTER TABLE chore_runs ADD COLUMN tokens_input INTEGER;
ALTER TABLE chore_runs ADD COLUMN tokens_output INTEGER;
ALTER TABLE chore_runs ADD COLUMN tokens_reasoning INTEGER;
ALTER TABLE chore_runs ADD COLUMN tokens_cache_read INTEGER;
ALTER TABLE chore_runs ADD COLUMN tokens_cache_write INTEGER;
