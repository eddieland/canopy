-- The submission id the web's form drew when it was rendered (DESIGN §43), sent again unchanged on a retry, so a retry
-- whose first try was recorded finds that epic rather than recording a second. NULL for an epic the CLI submitted,
-- and for every epic from before this migration.
ALTER TABLE epics ADD COLUMN submission TEXT;
CREATE UNIQUE INDEX epics_submission ON epics(channel, submission) WHERE submission IS NOT NULL;
