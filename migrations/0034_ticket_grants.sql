-- Runs the operator granted a ticket beyond its policy attempt limit for a kind counted per ticket (`canopy grant KEY
-- plan`, DESIGN §22, §25). A plan covers every repository the ticket will touch, so its limit is the ticket's, not a
-- unit's, and `attempt_grants` holds only units'. Rows are only added; every run still counts (D030). No agent canopy
-- runs can add one.

CREATE TABLE ticket_grants (
    id          INTEGER PRIMARY KEY,
    ticket_key  TEXT NOT NULL REFERENCES tickets(key),
    kind        TEXT NOT NULL CHECK (kind IN ('plan')),
    runs        INTEGER NOT NULL CHECK (runs > 0),
    granted_at  TEXT NOT NULL
);
