-- What the operator has seen (DESIGN §22): a subject whose result is new to them until they open it, in the web UI or
-- the CLI. A row is one subject, named as its reference names it (`review:4` is kind `review`, subject `4`), so a new
-- kind of subject takes a value of `kind` and no table of its own. A mark is the operator's alone, as a dismissal is:
-- it authorizes nothing, no agent reads it, and seeing a subject again records nothing new.
--
-- Every review run that had ended is taken as seen, so the reviews from before this are not all new at once. Those
-- rows have no channel: no channel saw them.
CREATE TABLE seen (
    kind     TEXT NOT NULL CHECK (kind IN ('review')),
    subject  TEXT NOT NULL,
    at       TEXT NOT NULL,
    channel  TEXT CHECK (channel IN ('cli', 'web')),
    PRIMARY KEY (kind, subject)
);

INSERT INTO seen (kind, subject, at)
SELECT 'review', CAST(id AS TEXT), ended_at FROM review_runs WHERE ended_at IS NOT NULL;
