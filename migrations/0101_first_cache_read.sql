-- What an agent run's first model call read from the cache (DESIGN §13): the share of what it was sent that it read is
-- whether the run's fixed prefix came from the cache, and a provider that reports no cache writes (OpenAI's) says so
-- only through it. NULL when the runtime reported nothing, when the run made no model call, and on every run from
-- before this migration.

ALTER TABLE runs ADD COLUMN tokens_first_cache_read INTEGER;
ALTER TABLE ticks ADD COLUMN tokens_first_cache_read INTEGER;
ALTER TABLE chore_runs ADD COLUMN tokens_first_cache_read INTEGER;
ALTER TABLE review_runs ADD COLUMN tokens_first_cache_read INTEGER;
ALTER TABLE task_runs ADD COLUMN tokens_first_cache_read INTEGER;
