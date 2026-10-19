-- When a ticket last changed (DESIGN §22): its row made, or its phase, title, done flag, plan setting, or a unit's
-- phase or PR set to a value it did not already hold. The web UI weighs a ticket's and its PRs' activity by it rather
-- than by `last_seen_at`, which every tick that names the ticket moves, so a tick that sets what was already there is
-- no activity. A journal from before this starts each ticket at its last sighting; every row is made with it set.
ALTER TABLE tickets ADD COLUMN changed_at TEXT NOT NULL DEFAULT '';
UPDATE tickets SET changed_at = last_seen_at;

-- The tickets list and the PRs list read the tickets that changed last, in place of the ones a tick saw last.
CREATE INDEX tickets_changed ON tickets(changed_at);
