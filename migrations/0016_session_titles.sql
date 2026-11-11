-- Each of the runtime's sessions' title, and when the runtime archived it, kept while `sessions.search` is `titles`
-- (DESIGN §13, ROADMAP M72): the title on one line, nothing hidden in it, at most `MAX_TITLE` characters; NULL when the
-- session has none, the read keeps no title, or it ran in a directory `sessions.exclude` names. `archived_at` is NULL
-- when the runtime did not archive it, or the read keeps no title. `runtime_session_reads.titles` is what the read
-- keeps titles under: `sessions.exclude` as a JSON array, NULL while it keeps none. A read under another setting starts
-- again from the first session, so every one is read under it; one that keeps none drops every title first.
ALTER TABLE runtime_sessions ADD COLUMN title TEXT;

ALTER TABLE runtime_sessions ADD COLUMN archived_at TEXT;

ALTER TABLE runtime_session_reads ADD COLUMN titles TEXT;
