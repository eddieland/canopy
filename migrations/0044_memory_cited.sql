-- What a run said of each memory rendered into its prompt (DESIGN §28): `used` for one in its `memory_used`, `wrong`
-- for one in its `memory_wrong`, NULL for one it cited in neither. So a memory names the runs that relied on it, not
-- only how many did. NULL on every read from before this migration, whose runs are counted in `memories.use_count`
-- but not named.

ALTER TABLE memory_reads ADD COLUMN cited TEXT CHECK (cited IN ('used', 'wrong'));
