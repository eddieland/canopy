-- The persona each worker run and review ran in (DESIGN §31): its name, and the sha256 of its text as the prompt
-- carried it, so the operator can compare one persona's work with another's, and a persona edited between two runs
-- splits them. Both NULL for a run no persona reaches, such as a feedback plan, and for every run from before canopy
-- recorded them.
ALTER TABLE runs ADD COLUMN persona TEXT;
ALTER TABLE runs ADD COLUMN persona_digest TEXT CHECK ((persona IS NULL) = (persona_digest IS NULL));
ALTER TABLE review_runs ADD COLUMN persona TEXT;
ALTER TABLE review_runs ADD COLUMN persona_digest TEXT CHECK ((persona IS NULL) = (persona_digest IS NULL));
