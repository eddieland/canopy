-- An epic takes attachments as a ticket and a task do (DESIGN §22, §43): its plan runs, and every run of each ticket
-- that is its member, read them as data. SQLite cannot widen a CHECK in place, so the table is rebuilt with every row
-- it holds, and its index made again.
CREATE TABLE attachments_new (
    id               INTEGER PRIMARY KEY,
    subject_kind     TEXT NOT NULL CHECK (subject_kind IN ('ticket', 'task', 'epic')),
    subject_id       TEXT NOT NULL,
    name             TEXT NOT NULL,
    size             INTEGER NOT NULL CHECK (size > 0),
    sha256           TEXT NOT NULL,
    channel          TEXT NOT NULL CHECK (channel IN ('cli', 'web')),
    added_at         TEXT NOT NULL,
    removed_at       TEXT,
    removed_channel  TEXT CHECK (removed_channel IN ('cli', 'web')),
    CHECK ((removed_at IS NULL) = (removed_channel IS NULL))
);

INSERT INTO attachments_new (
    id, subject_kind, subject_id, name, size, sha256, channel, added_at, removed_at, removed_channel
)
SELECT id, subject_kind, subject_id, name, size, sha256, channel, added_at, removed_at, removed_channel
FROM attachments;

DROP TABLE attachments;

ALTER TABLE attachments_new RENAME TO attachments;

CREATE UNIQUE INDEX attachments_name ON attachments(subject_kind, subject_id, name) WHERE removed_at IS NULL;
