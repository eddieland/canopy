-- Whether a tick's state block told the overseer to run the tracker query (DESIGN §7, Spacing the query): 1 or 0.
-- With `tracker.query_every_minutes` set, the next tick runs it again once that long has passed since the newest live
-- `ok` tick that ran it. NULL on every tick from before this migration, each of which was told to run it.

ALTER TABLE ticks ADD COLUMN query_due INTEGER;
