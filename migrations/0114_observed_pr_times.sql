-- A PR's times as canopy's reader last read them (DESIGN §30), each NULL where the reader printed none, as on a PR read
-- before canopy read them: when it was opened; when it last became ready for review, its creation for one opened ready
-- and NULL while it is a draft; when a review of it was first asked for at or after that; and when it merged and when
-- it closed.
ALTER TABLE observed_prs ADD COLUMN created_at TEXT;
ALTER TABLE observed_prs ADD COLUMN ready_at TEXT;
ALTER TABLE observed_prs ADD COLUMN review_requested_at TEXT;
ALTER TABLE observed_prs ADD COLUMN merged_at TEXT;
ALTER TABLE observed_prs ADD COLUMN closed_at TEXT;
