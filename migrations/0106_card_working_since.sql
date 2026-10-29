-- When each step a running agent's card names as `working` was first seen working (DESIGN §41): a JSON object from
-- the step's title to the time canopy recorded the first card on which it was working, of the steps working on the
-- latest card alone. A step working longer than the run's last fifth is shown stuck. NULL for a card with no steps
-- working, and on every run from before this migration.
ALTER TABLE runs ADD COLUMN card_working_since TEXT;
ALTER TABLE review_runs ADD COLUMN card_working_since TEXT;
