-- What a resumed worker answered of each review finding it was handed (DESIGN §21, Answers and rebuttals): `fixed`,
-- or `declined` with its reason, in its own words, by the finding's number in its review run. The next review of the
-- PR reads them as data. A worker answers only findings of its own ticket's reviews; the harness checks that.
CREATE TABLE review_answers (
    run_id         INTEGER NOT NULL REFERENCES runs(id),
    review_run_id  INTEGER NOT NULL REFERENCES review_runs(id),
    finding        INTEGER NOT NULL CHECK (finding > 0),
    answer         TEXT NOT NULL CHECK (answer IN ('fixed', 'declined')),
    reason         TEXT,
    CHECK (answer != 'declined' OR reason IS NOT NULL),
    PRIMARY KEY (run_id, review_run_id, finding)
);

-- A review finding the harness holds for the operator: it starts no `resume` and reaches no worker until the operator
-- sends it, which releases it, or dismisses it. `rebuttal` is a later review's answer to a finding the worker declined,
-- named by that earlier review run and finding.
CREATE TABLE review_holds (
    review_run_id     INTEGER NOT NULL REFERENCES review_runs(id),
    finding           INTEGER NOT NULL CHECK (finding > 0),
    kind              TEXT NOT NULL CHECK (kind IN ('rebuttal')),
    rebuts_run_id     INTEGER REFERENCES review_runs(id),
    rebuts_finding    INTEGER CHECK (rebuts_finding > 0),
    held_at           TEXT NOT NULL,
    released_at       TEXT,
    released_channel  TEXT CHECK (released_channel IN ('cli', 'web')),
    CHECK (kind != 'rebuttal' OR (rebuts_run_id IS NOT NULL AND rebuts_finding IS NOT NULL)),
    CHECK ((released_at IS NULL) = (released_channel IS NULL)),
    PRIMARY KEY (review_run_id, finding)
);
