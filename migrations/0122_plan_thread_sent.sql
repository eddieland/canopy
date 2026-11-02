-- When the operator last sent a plan comment to a planner, as it stands, in a request for changes (DESIGN §25). A
-- planner whose run started after it has read the comment, so an approval's notes leave it out rather than send the
-- implement what the plan already answered. Cleared when the comment's words, its replies, or its resolution change,
-- since it then says something no planner has read. NULL for a comment never sent, and for every one from before this
-- migration.
ALTER TABLE plan_threads ADD COLUMN sent_at TEXT;
