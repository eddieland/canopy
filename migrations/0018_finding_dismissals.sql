-- Chore findings the operator dismissed (`canopy dismiss chore:NAME ID`, DESIGN §19). A dismissal keeps a finding off
-- the attention list while the chore goes on reporting it: it covers the unbroken run of `ok` runs reporting the id
-- when it was made, so a finding that clears and comes back is listed again. `--undo` deletes the row, and dismissing
-- the id again replaces it. No agent canopy runs can add one.

CREATE TABLE finding_dismissals (
    chore         TEXT NOT NULL,
    finding_id    TEXT NOT NULL,
    dismissed_at  TEXT NOT NULL,
    channel       TEXT NOT NULL CHECK (channel IN ('cli', 'web')),
    PRIMARY KEY (chore, finding_id)
);
