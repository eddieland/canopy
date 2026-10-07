-- Notification sinks (DESIGN §20, ROADMAP M10). Point events go to an outbox, written in the transaction that records
-- the fact, and each sink has a cursor: the newest event it delivered. AUTOINCREMENT keeps ids rising after old events
-- are pruned, so an event never gets an id a cursor already passed.
CREATE TABLE notify_events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    grp     TEXT NOT NULL,   -- loop | runs | chores
    kind    TEXT NOT NULL,   -- run.started | run.ended | chore.ended | loop.failing | loop.recovered | loop.sink_failing
    at      TEXT NOT NULL,
    fields  TEXT NOT NULL    -- JSON object; text cut to its limits, one line
);

CREATE TABLE notify_sinks (
    name              TEXT PRIMARY KEY,
    cursor            INTEGER NOT NULL,   -- the newest notify_events id delivered, or passed over
    created_at        TEXT NOT NULL,
    last_delivery_at  TEXT,
    last_digest_at    TEXT,
    failures          INTEGER NOT NULL DEFAULT 0,  -- consecutive failed deliveries
    last_error        TEXT
);

-- The attention list is still a diff of state (D032), now per sink. Every row so far was notify.cmd's, the sink named
-- `default`, and keeps its fingerprint, so an upgrade with notify.cmd set re-notifies nothing.
CREATE TABLE notifications_new (
    sink         TEXT NOT NULL,
    fingerprint  TEXT NOT NULL,
    ticket_key   TEXT,
    reason       TEXT NOT NULL,
    repo         TEXT,
    sent_at      TEXT NOT NULL,
    PRIMARY KEY (sink, fingerprint)
);
INSERT INTO notifications_new (sink, fingerprint, ticket_key, reason, repo, sent_at)
    SELECT 'default', fingerprint, ticket_key, reason, repo, sent_at FROM notifications;
DROP TABLE notifications;
ALTER TABLE notifications_new RENAME TO notifications;
