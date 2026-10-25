-- The runs the overseer asks for, recorded, not spawned (DESIGN §40, ROADMAP M40): a dispatch, a review, a revision of
-- a review's draft, or a chore's run, its guards checked at the ask. The tick spawns each once the overseer's run has
-- ended, under its guards again; until then it counts as running in every guard's count. One the tick did not spawn is
-- closed `unstarted` as the tick closes, or by the next tick when this one died, and counts toward no limit.
CREATE TABLE recorded_runs (
    id           INTEGER PRIMARY KEY,
    tick_id      INTEGER NOT NULL REFERENCES ticks(id),
    kind         TEXT NOT NULL CHECK (kind IN ('dispatch', 'review', 'revision', 'chore')),
    -- The verb's request as the overseer made it, JSON, which the spawn makes again.
    request      TEXT NOT NULL,
    -- What it holds while it waits: its ticket (a dispatch's, or a review's of one of the loop's own PRs), a review's
    -- or a revision's PR and persona, and a chore's name.
    ticket_key   TEXT,
    pr_url       TEXT,
    persona      TEXT,
    chore        TEXT,
    status       TEXT NOT NULL DEFAULT 'recorded' CHECK (status IN ('recorded', 'started', 'refused', 'unstarted')),
    -- The run it started as, in its kind's table: `runs`, `review_runs`, or `chore_runs`.
    run_id       INTEGER,
    recorded_at  TEXT NOT NULL,
    closed_at    TEXT
);
