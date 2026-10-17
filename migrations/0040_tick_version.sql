-- The version of canopy that ran each tick (DESIGN §6), as its installed package reports it: a release from its tag, or
-- a development build with its commit. A tick's decisions name it through `tick_id`, so the journal says which release
-- made each one. NULL on every tick from before this migration.

ALTER TABLE ticks ADD COLUMN canopy_version TEXT;
