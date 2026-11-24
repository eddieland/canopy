-- A review finding less severe than `review.min_severity` is held for the operator as `severity`: it reaches no worker
-- and raises no item until they send it (DESIGN §21, Answers and rebuttals). SQLite cannot alter a CHECK, so the table
-- is rebuilt with every row it had. No table references it, and it has no index.
CREATE TABLE review_holds_new (
    review_run_id     INTEGER NOT NULL REFERENCES review_runs(id),
    finding           INTEGER NOT NULL CHECK (finding > 0),
    kind              TEXT NOT NULL CHECK (kind IN ('rebuttal', 'late', 'severity')),
    rebuts_run_id     INTEGER REFERENCES review_runs(id),
    rebuts_finding    INTEGER CHECK (rebuts_finding > 0),
    held_at           TEXT NOT NULL,
    released_at       TEXT,
    released_channel  TEXT CHECK (released_channel IN ('cli', 'web')),
    CHECK ((kind = 'rebuttal') = (rebuts_run_id IS NOT NULL AND rebuts_finding IS NOT NULL)),
    CHECK (kind = 'rebuttal' OR (rebuts_run_id IS NULL AND rebuts_finding IS NULL)),
    CHECK ((released_at IS NULL) = (released_channel IS NULL)),
    PRIMARY KEY (review_run_id, finding)
);
INSERT INTO review_holds_new SELECT * FROM review_holds;
DROP TABLE review_holds;
ALTER TABLE review_holds_new RENAME TO review_holds;
