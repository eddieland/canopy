-- How long each ticket plan is (DESIGN §25), measured once from its file as its planner wrote it, so the Plans report
-- reads it here rather than reading every plan's file again. A cache: every row can be measured again from the plan's
-- original, which is never written again. `version` is the measuring model's (`plan_metrics.VERSION`); a row of an
-- older one is measured again, and until then not read. `problem` says why a plan could not be measured, its original
-- gone or not the file written, and its measurements are then NULL, so it is not tried again.
CREATE TABLE plan_metrics (
    plan_id      INTEGER PRIMARY KEY REFERENCES plans(id),
    version      INTEGER NOT NULL,
    measured_at  TEXT NOT NULL,
    problem      TEXT,
    words        INTEGER,
    lines        INTEGER,
    code_blocks  INTEGER,
    tables       INTEGER,
    diagrams     INTEGER,
    CHECK (
        (problem IS NULL AND words IS NOT NULL AND lines IS NOT NULL AND code_blocks IS NOT NULL AND tables IS NOT NULL
            AND diagrams IS NOT NULL)
        OR (problem IS NOT NULL AND coalesce(words, lines, code_blocks, tables, diagrams) IS NULL)
    )
);
