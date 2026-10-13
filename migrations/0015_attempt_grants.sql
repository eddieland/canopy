-- Runs the operator granted a unit beyond its policy attempt limit (`canopy grant`, DESIGN §8, §22). Rows are only
-- added: a unit's limit for a kind is the policy's plus the sum of its grants of that kind, and every run still counts
-- (D030). No agent canopy runs can add one.

CREATE TABLE attempt_grants (
    id          INTEGER PRIMARY KEY,
    ticket_key  TEXT NOT NULL REFERENCES tickets(key),
    repo        TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('implement', 'fix-ci', 'resume')),
    runs        INTEGER NOT NULL CHECK (runs > 0),
    granted_at  TEXT NOT NULL
);
