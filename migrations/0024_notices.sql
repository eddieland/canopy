-- The operator's notices to workers (`canopy notice`, DESIGN §8, §22): a passing condition, such as a CI outage, that
-- every run that builds, tests, or reads CI hears while it lasts. A notice is in force from `set_at` until
-- `lapses_at`, or until `ended_at` if the operator cleared it (`canopy notice --clear`) or set another, which ends it.
-- At most one is in force; a lapsed one reads as none, so nothing deletes it. Rows stay, so the overseer can tell
-- which failed checks ran while one was in force (§7). `channel` and `ended_channel` are `cli` or `web`.

CREATE TABLE notices (
    id             INTEGER PRIMARY KEY,
    body           TEXT NOT NULL,
    set_at         TEXT NOT NULL,
    channel        TEXT NOT NULL,
    lapses_at      TEXT NOT NULL,
    ended_at       TEXT,
    ended_channel  TEXT
);
CREATE INDEX notices_set ON notices(set_at);
