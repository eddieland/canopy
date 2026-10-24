-- A review's finding held for the operator may be `late` too (DESIGN §21, Answers and rebuttals): a later review's
-- finding on a line unchanged since the PR's first reviewed commit, which names no earlier finding.
--
-- SQLite cannot change a CHECK in place, so `review_holds` is rebuilt with every row it had. No table references it.

CREATE TEMP TABLE review_holds_0089 AS SELECT * FROM review_holds;
DROP TABLE review_holds;

CREATE TABLE review_holds (
    review_run_id     INTEGER NOT NULL REFERENCES review_runs(id),
    finding           INTEGER NOT NULL CHECK (finding > 0),
    kind              TEXT NOT NULL CHECK (kind IN ('rebuttal', 'late')),
    rebuts_run_id     INTEGER REFERENCES review_runs(id),
    rebuts_finding    INTEGER CHECK (rebuts_finding > 0),
    held_at           TEXT NOT NULL,
    released_at       TEXT,
    released_channel  TEXT CHECK (released_channel IN ('cli', 'web')),
    CHECK (kind != 'rebuttal' OR (rebuts_run_id IS NOT NULL AND rebuts_finding IS NOT NULL)),
    CHECK (kind != 'late' OR (rebuts_run_id IS NULL AND rebuts_finding IS NULL)),
    CHECK ((released_at IS NULL) = (released_channel IS NULL)),
    PRIMARY KEY (review_run_id, finding)
);

INSERT INTO review_holds (
    review_run_id, finding, kind, rebuts_run_id, rebuts_finding, held_at, released_at, released_channel
)
SELECT review_run_id, finding, kind, rebuts_run_id, rebuts_finding, held_at, released_at, released_channel
FROM temp.review_holds_0089;
DROP TABLE temp.review_holds_0089;
