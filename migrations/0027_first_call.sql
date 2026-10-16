-- What an agent run's first model call was sent, from the cache or not, and what it wrote to the cache (DESIGN §13):
-- all of the run's fixed overhead is in that call, so less the prompt canopy sent it is the overhead, and a large write
-- is a cold start. And the digest of the definitions snapshot the run loaded (`core/definitions.py`), so a change to a
-- prompt, an override, or a definition splits the runs into before and after. NULL when the runtime reported nothing,
-- the first call's too when it made no model call, and all three on every run from before this migration.

ALTER TABLE runs ADD COLUMN tokens_first_call INTEGER;
ALTER TABLE runs ADD COLUMN tokens_first_cache_write INTEGER;
ALTER TABLE runs ADD COLUMN definitions_digest TEXT;
ALTER TABLE ticks ADD COLUMN tokens_first_call INTEGER;
ALTER TABLE ticks ADD COLUMN tokens_first_cache_write INTEGER;
ALTER TABLE ticks ADD COLUMN definitions_digest TEXT;
ALTER TABLE chore_runs ADD COLUMN tokens_first_call INTEGER;
ALTER TABLE chore_runs ADD COLUMN tokens_first_cache_write INTEGER;
ALTER TABLE chore_runs ADD COLUMN definitions_digest TEXT;
ALTER TABLE review_runs ADD COLUMN tokens_first_call INTEGER;
ALTER TABLE review_runs ADD COLUMN tokens_first_cache_write INTEGER;
ALTER TABLE review_runs ADD COLUMN definitions_digest TEXT;
