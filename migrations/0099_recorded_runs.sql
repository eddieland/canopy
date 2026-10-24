-- The runs the overseer asks for, recorded at the ask and started by its tick once the overseer's run ends (DESIGN §8,
-- ROADMAP M40 stage 1), so no run is ever the overseer's descendant. A recorded run counts as running in every guard
-- until its tick starts it, a guard refuses it then, or the tick ends without starting it.
CREATE TABLE recorded_runs (
    id           INTEGER PRIMARY KEY,
    tick_id      INTEGER NOT NULL REFERENCES ticks(id),
    -- The run table it starts in: a worker run, a review, a revision of a review's draft, or a chore run.
    kind         TEXT NOT NULL CHECK (kind IN ('dispatch', 'review', 'revision', 'chore')),
    -- What it holds while recorded: a dispatch's ticket, a review's ticket if it names one, and its PR and persona,
    -- a revision's PR, a chore's name.
    ticket_key   TEXT,
    pr           TEXT,
    persona      TEXT,
    chore        TEXT,
    -- Its place in §7's order, which its tick starts it in with the harness's own dispatches.
    rank         INTEGER NOT NULL,
    -- The overseer's request, validated at the ask, as JSON.
    request      TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'recorded' CHECK (status IN ('recorded', 'started', 'refused', 'unstarted')),
    -- The run it started, in the table `kind` names.
    run_id       INTEGER,
    recorded_at  TEXT NOT NULL,
    ended_at     TEXT
);

CREATE INDEX recorded_runs_open ON recorded_runs(status) WHERE status = 'recorded';
