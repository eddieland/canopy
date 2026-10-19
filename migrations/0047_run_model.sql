-- The model canopy asked a run's worker to run on, a `provider/model` id rendered into its definition (DESIGN §13, The
-- worker's model): empty for the runtime's default, and for a kind whose model canopy does not choose. Runs from before
-- this migration are empty too, whatever their template chose.
ALTER TABLE runs ADD COLUMN model TEXT NOT NULL DEFAULT '';
