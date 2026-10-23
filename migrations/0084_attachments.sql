-- Files the operator attaches to a ticket or a task (DESIGN §22): text someone sent them, such as a design doc, for
-- the subject's runs to read as data. Only the operator's channels write a row, refused inside a tick or any run. The
-- text is kept beside the journal, `<state_dir>/attachments/<subject_kind>.<subject_id>/<id>.txt`, and `sha256` and
-- `size` are of it as written. `name` is what runs see it as, unique among the subject's attachments not removed. A
-- removed attachment keeps its row, with when and through which channel, and its file is deleted.
CREATE TABLE attachments (
    id               INTEGER PRIMARY KEY,
    subject_kind     TEXT NOT NULL CHECK (subject_kind IN ('ticket', 'task')),
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
CREATE UNIQUE INDEX attachments_name ON attachments(subject_kind, subject_id, name) WHERE removed_at IS NULL;
