-- What the agent runtime reported about each tick's overseer run (DESIGN §6, §13): the session it kept, and what it
-- cost in dollars and tokens, summed over its model calls, as `runs` records for a worker (0002). NULL when the runtime
-- reported none of it, as an `overseer_cmd` without OpenCode's JSON events does (D071), and on every tick from before
-- this migration. A tick's cost is its overseer's alone: each run it dispatched records its own.

ALTER TABLE ticks ADD COLUMN session_id TEXT;
ALTER TABLE ticks ADD COLUMN cost_usd REAL;
ALTER TABLE ticks ADD COLUMN tokens_input INTEGER;
ALTER TABLE ticks ADD COLUMN tokens_output INTEGER;
ALTER TABLE ticks ADD COLUMN tokens_reasoning INTEGER;
ALTER TABLE ticks ADD COLUMN tokens_cache_read INTEGER;
ALTER TABLE ticks ADD COLUMN tokens_cache_write INTEGER;
