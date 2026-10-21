-- Revising a review's draft with an agent (DESIGN §34, ROADMAP M43). The operator's note on a draft asks for a
-- revision while it is newer than the draft's newest version: `after_version` is the newest version when the note was
-- written, so a note is newer exactly while no version has been made since. A note is the operator's alone, written
-- through their channels (`canopy reply review:ID`), never by an agent; it is the reviser's only instruction.
CREATE TABLE review_draft_notes (
    id             INTEGER PRIMARY KEY,
    draft_id       INTEGER NOT NULL REFERENCES review_drafts(id),
    after_version  INTEGER NOT NULL CHECK (after_version > 0),
    body           TEXT NOT NULL,
    channel        TEXT NOT NULL CHECK (channel IN ('cli', 'web')),
    created_at     TEXT NOT NULL
);
CREATE INDEX review_draft_notes_draft ON review_draft_notes(draft_id, after_version);

-- Revisions the operator granted a draft beyond `policy.max_revisions_per_draft` (`canopy grant review:ID revision`).
-- Rows are only added: a draft's limit is the policy's plus the sum of its grants, and every revision still counts
-- (D030). No agent canopy runs can add one.
CREATE TABLE review_draft_grants (
    id          INTEGER PRIMARY KEY,
    draft_id    INTEGER NOT NULL REFERENCES review_drafts(id),
    runs        INTEGER NOT NULL CHECK (runs > 0),
    granted_at  TEXT NOT NULL
);
CREATE INDEX review_draft_grants_draft ON review_draft_grants(draft_id);

-- A revision is a review run at the same commit as the review whose draft it revises: `revises` names that draft and
-- `revises_version` the version it read. Both NULL for a review, which every list of a PR's reviews keeps to.
ALTER TABLE review_runs ADD COLUMN revises INTEGER REFERENCES review_drafts(id);
ALTER TABLE review_runs ADD COLUMN revises_version INTEGER CHECK ((revises IS NULL) = (revises_version IS NULL));
CREATE INDEX review_runs_revises ON review_runs(revises) WHERE revises IS NOT NULL;
