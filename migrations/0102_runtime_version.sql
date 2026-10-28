-- The version of the agent runtime that ran each agent run, as its session's record names it (DESIGN §13): a change to
-- how the runtime lays out a run's prompt, which no digest of canopy's definitions shows, splits the runs into before
-- and after. NULL where the record names none, and on every run read before this migration.

ALTER TABLE run_model_reads ADD COLUMN runtime_version TEXT;
