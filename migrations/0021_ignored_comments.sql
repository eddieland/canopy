-- A comment `connect.ignore_comments` names is observed like any other and marked ignored (DESIGN §30): the journal
-- keeps what its source held, and nothing canopy derives or hands an agent rests on it. An ignored comment takes no
-- journal number (§35) until a later read finds it no longer ignored, so no cursor passes it unseen; an ignored
-- review, which keeps its state, is numbered as any review is.
ALTER TABLE observed_reviews ADD COLUMN ignored INTEGER NOT NULL DEFAULT 0 CHECK (ignored IN (0, 1));
ALTER TABLE observed_comments ADD COLUMN ignored INTEGER NOT NULL DEFAULT 0 CHECK (ignored IN (0, 1));
