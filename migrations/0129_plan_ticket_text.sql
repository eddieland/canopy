-- The ticket's text as the tracker connector last observed it when its plan was approved (DESIGN §25): a SHA-256, hex,
-- of its title and of its description, each recorded with the approval, the operator's or the planner's, and again
-- with each approval after. An `implement` on the plan is refused while the ticket's observed text differs, naming
-- which changed. NULL for a plan never approved, one approved while the ticket was not observed, and every one approved
-- before this migration: such an approval is never stale for its ticket's text.
ALTER TABLE plans ADD COLUMN approved_title_sha256 TEXT;
ALTER TABLE plans ADD COLUMN approved_body_sha256 TEXT CHECK (
    (approved_title_sha256 IS NULL) = (approved_body_sha256 IS NULL)
    AND (approved_body_sha256 IS NULL OR approved_at IS NOT NULL)
);
