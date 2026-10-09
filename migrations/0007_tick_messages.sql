-- The newest message in the journal when each tick read it, before its harness items and the overseer's state block
-- (DESIGN §6 step 3): every message up to it was there for that tick to see. NULL on every tick from before this
-- migration. The web UI marks an operator message after the latest `ok` tick's as waiting for the next tick (§22).

ALTER TABLE ticks ADD COLUMN message_id INTEGER;
