-- When each step on a running agent's card last changed (DESIGN §41), as the harness keeps it beside the card: a JSON
-- array, one entry per step of `card_json`, in its order, each with `held`, how many seconds before `card_at` a card
-- first gave the step its status and stage, and `stuck_after`, for a `working` step, how many seconds after that it is
-- shown stuck, a fifth of the run's timeout, else null. Kept from `card_at`, so they move with it. Rewritten with each
-- card. NULL on a run with no card, and on every run from before this migration.
ALTER TABLE runs ADD COLUMN card_steps_json TEXT;
ALTER TABLE review_runs ADD COLUMN card_steps_json TEXT;
