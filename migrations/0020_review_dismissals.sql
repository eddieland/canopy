-- Review findings the operator dismissed (`canopy dismiss review:ID N`, DESIGN §21), by the finding's number in its
-- run, from 1. A dismissed finding stays on the review's page, marked, and is left out of what a `resume` hands a
-- worker and of the overseer's state block. A finding has no id that lasts from one commit's review to the next, so a
-- dismissal is of one run's finding only. `--undo` deletes the row. No agent canopy runs can add one.

CREATE TABLE review_dismissals (
    review_run_id  INTEGER NOT NULL REFERENCES review_runs(id),
    finding        INTEGER NOT NULL CHECK (finding > 0),
    dismissed_at   TEXT NOT NULL,
    channel        TEXT NOT NULL CHECK (channel IN ('cli', 'web')),
    PRIMARY KEY (review_run_id, finding)
);
