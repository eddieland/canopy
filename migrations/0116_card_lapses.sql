-- How often a running run's card went stale (DESIGN §41), so the journal says it after the run has ended. `card_lapses`
-- counts each time it went from fresh to stale, as canopy found it at a tool call the run ended; `card_stale` says
-- whether its card as it stands, or the run with none yet, has been counted so, until a new card makes it fresh again.
-- A run that ended stale and not counted so lapses once more as it ended, which its row's `ended_at` says, so that
-- lapse is read, not written. 0 on a run whose card never went stale, and on every run from before this migration.
ALTER TABLE runs ADD COLUMN card_lapses INTEGER NOT NULL DEFAULT 0;
ALTER TABLE runs ADD COLUMN card_stale INTEGER NOT NULL DEFAULT 0 CHECK (card_stale IN (0, 1));
ALTER TABLE review_runs ADD COLUMN card_lapses INTEGER NOT NULL DEFAULT 0;
ALTER TABLE review_runs ADD COLUMN card_stale INTEGER NOT NULL DEFAULT 0 CHECK (card_stale IN (0, 1));
ALTER TABLE task_runs ADD COLUMN card_lapses INTEGER NOT NULL DEFAULT 0;
ALTER TABLE task_runs ADD COLUMN card_stale INTEGER NOT NULL DEFAULT 0 CHECK (card_stale IN (0, 1));
