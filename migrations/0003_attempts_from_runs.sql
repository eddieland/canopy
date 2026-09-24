-- Attempt counts and the fix-ci cooldown are derived from `runs` (D030): every dispatched run is an attempt, and the
-- cooldown runs from the end of the ticket's latest fix-ci run. The counters and cooldown column were never written.
ALTER TABLE tickets DROP COLUMN fix_ci_attempts;
ALTER TABLE tickets DROP COLUMN resume_attempts;
ALTER TABLE tickets DROP COLUMN cooldown_until;
