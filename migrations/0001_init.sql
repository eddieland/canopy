-- canopy journal. Loop facts only. World facts are re-read from their source.
-- Applied by db.py inside a transaction; recorded in schema_migrations.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    applied_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- One row per tick. tick_id tags every log line and decision.
CREATE TABLE ticks (
    id          INTEGER PRIMARY KEY,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    dry_run     INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'running',  -- running | ok | overseer_failed | lock_busy
    summary     TEXT
);

-- One row per ticket key ever seen. Cursors make ticks incremental.
-- phase is the last derived phase, for display only; never read as truth.
CREATE TABLE tickets (
    key                 TEXT PRIMARY KEY,
    repo                TEXT NOT NULL,
    first_seen_at       TEXT NOT NULL,
    last_seen_at        TEXT NOT NULL,
    phase               TEXT,
    branch              TEXT,
    pr_url              TEXT,
    last_comment_id     TEXT,
    last_review_id      TEXT,
    last_ci_run_id      TEXT,
    fix_ci_attempts     INTEGER NOT NULL DEFAULT 0,
    resume_attempts     INTEGER NOT NULL DEFAULT 0,
    cooldown_until      TEXT,
    needs_human_since   TEXT,
    done                INTEGER NOT NULL DEFAULT 0
);

-- One row per worker execution. Source for capacity, crash detection, attempts.
CREATE TABLE runs (
    id            INTEGER PRIMARY KEY,
    tick_id       INTEGER NOT NULL REFERENCES ticks(id),
    ticket_key    TEXT NOT NULL REFERENCES tickets(key),
    kind          TEXT NOT NULL,                  -- implement | fix-ci | resume
    slot_path     TEXT NOT NULL,
    lease_id      TEXT NOT NULL,
    lease_holder  TEXT NOT NULL,
    pid           INTEGER,
    base_branch   TEXT,
    branch        TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    ended_at      TEXT,
    status        TEXT NOT NULL DEFAULT 'running',
        -- running | done | blocked | failed | unknown | unpushed | crashed | timeout
    result_json   TEXT,                           -- summary only; never raw logs
    log_path      TEXT NOT NULL
);
CREATE INDEX runs_running ON runs(status) WHERE status = 'running';
CREATE INDEX runs_ticket  ON runs(ticket_key, started_at);

-- One row per overseer decision. Audit log and prompt evaluation corpus.
CREATE TABLE decisions (
    id          INTEGER PRIMARY KEY,
    tick_id     INTEGER NOT NULL REFERENCES ticks(id),
    ticket_key  TEXT,
    action      TEXT NOT NULL,   -- dispatch:<kind> | wait | skip | attention:<reason> | refused:<guard>
    rationale   TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX decisions_tick ON decisions(tick_id);

-- Attention items already notified, by fingerprint, so diffs never re-notify.
CREATE TABLE notifications (
    fingerprint  TEXT PRIMARY KEY,   -- sha256(ticket_key + reason + detail)
    ticket_key   TEXT NOT NULL,
    reason       TEXT NOT NULL,
    sent_at      TEXT NOT NULL
);

INSERT INTO schema_migrations (version, name) VALUES (1, 'init');
