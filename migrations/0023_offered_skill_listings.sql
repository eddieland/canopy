-- What each skill a run was offered adds to every model call of the run (DESIGN §13): the characters of its entry in
-- the list of skills the runtime writes into each call's system prompt, as the runtime read the skill when the run
-- started. The entry holds its name and description and what else the runtime lists it with, not the rest of its
-- front matter, and rides in every call, loaded or not, so what an offered skill costs can be told from the journal.
-- NULL for a skill offered before canopy kept it; 0 for one the list leaves out.
ALTER TABLE run_offered_skills ADD COLUMN listing_chars INTEGER;
