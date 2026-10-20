-- The derivation, in shadow (DESIGN §30, ROADMAP M36): what each tick derived in code of §7's table, from the
-- observations and the journal, beside the overseer's decisions, which it never touches. A row is one subject a tick
-- derived: a ticket's own phases, `repo` NULL, or a unit's. `phases` is a JSON list of every row of §7 that held,
-- since §7 has no order between them yet; empty when none did, and when the subject depends on an observation stale or
-- missing, which `stale` then names. `overseer_phase` is the phase the journal held for the subject when the tick
-- closed: the overseer's, kept here since the journal keeps only a ticket's latest. Agreement is computed from these
-- and the tick's decisions, never stored, so a fix to the comparison reads every tick already recorded.
CREATE TABLE derivations (
    id              INTEGER PRIMARY KEY,
    tick_id         INTEGER NOT NULL REFERENCES ticks(id),
    ticket_key      TEXT NOT NULL,
    repo            TEXT,
    -- A ticket's own row: whether it is a candidate (DESIGN §17), and whether the tracker said it is closed. NULL on a
    -- unit's row, and on a stale one.
    candidate       INTEGER CHECK (candidate IN (0, 1)),
    closed          INTEGER CHECK (closed IN (0, 1)),
    phases          TEXT NOT NULL,
    stale           TEXT,
    overseer_phase  TEXT CHECK (
        overseer_phase IN (
            'ready', 'blocked', 'running', 'pushed_no_pr', 'conflicted', 'ci_running', 'ci_red', 'review_pending',
            'review_findings', 'changes_requested', 'untrusted_review', 'green_unreviewed', 'approved', 'merged',
            'needs_human', 'human_replied', 'split', 'plan_proposed'
        )
    ),
    CHECK (repo IS NULL OR (candidate IS NULL AND closed IS NULL)),
    CHECK (stale IS NULL OR (phases = '[]' AND candidate IS NULL AND closed IS NULL))
);
CREATE INDEX derivations_tick ON derivations(tick_id);
