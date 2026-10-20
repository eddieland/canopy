-- Review notes (DESIGN §28): what a review of one of the loop's own PRs leaves for its ticket's later reviews, read by
-- no worker. Empty while `memory.review_notes` is off, as it is by default. Apart from `memories`, whose runs are
-- workers': a review run's id is `review_runs`'s, and nothing that reads a worker's memory reads these. `body` is NULL
-- once the operator forgot or purged the row. Nothing is edited in place: a newer note under a key supersedes the one
-- before it, which stays.

CREATE TABLE review_notes (
    id              INTEGER PRIMARY KEY,
    ticket_key      TEXT NOT NULL REFERENCES tickets(key),
    key             TEXT NOT NULL,
    body            TEXT,
    status          TEXT NOT NULL CHECK (status IN ('active', 'superseded', 'invalid')),
    -- The harness's words for the latest change of status, such as `superseded by review note 41`.
    why             TEXT,
    review_run_id   INTEGER NOT NULL REFERENCES review_runs(id),
    -- The commit the review read.
    sha             TEXT NOT NULL,
    supersedes      INTEGER REFERENCES review_notes(id),
    created_at      TEXT NOT NULL,
    invalidated_at  TEXT
);
CREATE UNIQUE INDEX review_notes_active ON review_notes(ticket_key, key) WHERE status = 'active';
CREATE INDEX review_notes_ticket ON review_notes(ticket_key, status);
CREATE INDEX review_notes_run ON review_notes(review_run_id);

-- What a review's prompt was rendered under, for each review of a ticket started while `memory.review_notes` was not
-- off: the mode, and the entries `_review` refused from its result, as a JSON list. A review with no row was rendered
-- with review notes off, and writes none whatever it sends.
CREATE TABLE review_memory (
    review_run_id  INTEGER PRIMARY KEY REFERENCES review_runs(id),
    review_notes   TEXT NOT NULL CHECK (review_notes IN ('record', 'use')),
    refused        TEXT NOT NULL DEFAULT '[]'
);

-- Each review note rendered into a review's prompt. Only these notes' keys count in that review's `drop_review_notes`.
CREATE TABLE review_note_reads (
    review_run_id  INTEGER NOT NULL REFERENCES review_runs(id),
    note_id        INTEGER NOT NULL REFERENCES review_notes(id),
    PRIMARY KEY (review_run_id, note_id)
);
CREATE INDEX review_note_reads_note ON review_note_reads(note_id);
