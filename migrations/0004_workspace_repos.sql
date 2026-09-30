-- Workspaces (DESIGN §18). A run records the repository in the map it leased from, so reconcile and `_run` return its
-- slot to that repository's pool. NULL on runs from before workspaces: the workspace of one's only repository.
ALTER TABLE runs ADD COLUMN repo TEXT;

-- An attention item may be about a repository rather than a ticket (`repo_missing`); it then has no ticket key.
ALTER TABLE decisions ADD COLUMN repo TEXT;

-- Notified items are identified by ticket, reason, and repository, and a repository's item has no ticket. SQLite cannot
-- drop NOT NULL in place, so the table is rebuilt; existing rows keep their fingerprints and so are not notified again.
CREATE TABLE notifications_new (
    fingerprint  TEXT PRIMARY KEY,   -- sha256 of ticket_key, reason, and repo when there is one
    ticket_key   TEXT,
    reason       TEXT NOT NULL,
    repo         TEXT,
    sent_at      TEXT NOT NULL
);
INSERT INTO notifications_new (fingerprint, ticket_key, reason, sent_at)
    SELECT fingerprint, ticket_key, reason, sent_at FROM notifications;
DROP TABLE notifications;
ALTER TABLE notifications_new RENAME TO notifications;
