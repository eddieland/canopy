-- What `canopy loop` knew about each tick it ran (DESIGN §6, Idle pacing; ROADMAP M33): whether the tick was idle by
-- `pacing.idle`, 1 or 0, and what ended the wait before it: `start` (the loop's first tick), `timer` (the wait ran its
-- length), `gate` (a gate shortened the wait and it ran out), `message`, `run`, or `key`. Spend on idle ticks, and what
-- woke the ticks that cost, is read from them. NULL on a tick the loop did not run, such as a hand-run `canopy tick`,
-- and on every tick from before this migration.

ALTER TABLE ticks ADD COLUMN idle INTEGER;
ALTER TABLE ticks ADD COLUMN woken_by TEXT;
