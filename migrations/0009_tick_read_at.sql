-- When each tick read the journal for its overseer's state, recorded with `message_id` (DESIGN §6 step 3): a run, chore
-- run, or review run that started or ended after it, the tick could not have seen. Idle pacing reads it (§6). NULL on
-- every tick from before this migration, and on a tick that stopped before reading.

ALTER TABLE ticks ADD COLUMN read_at TEXT;
