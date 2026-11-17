-- How long each skill a run was offered says it is (DESIGN §13): the characters of its description, as the runtime
-- read it when the run started. With the skill's name it is the front matter the runtime's list of skills carries
-- into every model call of the run, loaded or not, so what an offered skill costs can be told from the journal.
-- NULL for a skill offered before canopy kept it; 0 for one whose front matter says nothing of it.
ALTER TABLE run_offered_skills ADD COLUMN description_chars INTEGER;
