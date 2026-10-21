-- The text of each persona a run or a review was given, once per digest (DESIGN §31): what `runs.persona_digest` and
-- `review_runs.persona_digest` name, kept so the operator reads the instructions a run read after its persona's file
-- is edited or gone. Written with the run that first carries the digest, and never changed: a text is its digest's.
CREATE TABLE persona_texts (
    digest       TEXT PRIMARY KEY,
    text         TEXT NOT NULL,
    recorded_at  TEXT NOT NULL
);
