-- What a running worker's, planner's, or reviewer's agent says of where its work stands, its card (DESIGN §41): the
-- input of its latest `status` call, as canopy read it from the events the agent printed and validated it, as JSON;
-- when canopy read it; and how many tool calls the agent had made by then. `tool_calls` counts every tool call the
-- run's events have ended so far, so the calls since the card are what it says less `card_calls`. The card stays once
-- the run ends. NULL, and 0 calls, on a run that never called `status`, and on every run from before this migration.
ALTER TABLE runs ADD COLUMN card_json TEXT;
ALTER TABLE runs ADD COLUMN card_at TEXT;
ALTER TABLE runs ADD COLUMN card_calls INTEGER;
ALTER TABLE runs ADD COLUMN tool_calls INTEGER NOT NULL DEFAULT 0;
ALTER TABLE review_runs ADD COLUMN card_json TEXT;
ALTER TABLE review_runs ADD COLUMN card_at TEXT;
ALTER TABLE review_runs ADD COLUMN card_calls INTEGER;
ALTER TABLE review_runs ADD COLUMN tool_calls INTEGER NOT NULL DEFAULT 0;
