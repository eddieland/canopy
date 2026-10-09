-- Messages kept for mailbox sinks (DESIGN §20): a sink with `mailbox = true` runs no command, and its messages wait
-- here for `canopy-notify-relay` on another machine to collect, over SSH (`canopy notify read`) or the web UI's
-- listener. Rows go after 7 days, or when the sink leaves the config.

CREATE TABLE notify_mailbox (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    sink     TEXT NOT NULL,
    at       TEXT NOT NULL,
    message  TEXT NOT NULL   -- one message, rendered in the sink's format
);

CREATE INDEX notify_mailbox_sink ON notify_mailbox (sink, id);
