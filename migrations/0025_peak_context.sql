-- The most tokens one of an agent run's model calls was sent, from the cache or not (DESIGN §13): how large its
-- context grew. The summed counts cannot say it, since each call reads again what the calls before it were sent. NULL
-- when the runtime reported nothing, and on every run from before this migration.

ALTER TABLE runs ADD COLUMN tokens_peak_context INTEGER;
ALTER TABLE ticks ADD COLUMN tokens_peak_context INTEGER;
ALTER TABLE chore_runs ADD COLUMN tokens_peak_context INTEGER;
ALTER TABLE review_runs ADD COLUMN tokens_peak_context INTEGER;
