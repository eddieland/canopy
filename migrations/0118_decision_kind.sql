-- The kind of run a refused dispatch asked for (DESIGN §11), so the health report can say what a guard refused, ticket
-- and kind, without reading it from the guard's reason. NULL on any other decision, and on every refusal recorded
-- before this migration.
ALTER TABLE decisions ADD COLUMN kind TEXT
    CHECK (kind IN ('implement', 'fix-ci', 'resume', 'split', 'plan', 'needs-plan', 'feedback-plan'));
