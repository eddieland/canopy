-- Forgetting a ticket's work (DESIGN §22): `canopy forget` clears what canopy knows of a ticket's branch and PRs so
-- its next `implement` starts over, and marks where the loop's view of the ticket now begins. Earlier runs and
-- messages stay in the journal: `show` prints them and attempt limits count them (D030), but the loop reads only what
-- came after.

-- When the operator last forgot the ticket's work; NULL if never.
ALTER TABLE tickets ADD COLUMN forgotten_at TEXT;
-- The ticket's newest run and newest message at that moment. The loop's reads skip runs and messages up to these.
ALTER TABLE tickets ADD COLUMN forgotten_run_id INTEGER;
ALTER TABLE tickets ADD COLUMN forgotten_message_id INTEGER;
