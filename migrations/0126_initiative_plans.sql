-- An initiative's plans (DESIGN §43), one per plan run that wrote one, as `plans` holds a ticket's (§25). A plan's text
-- is never here: it is the file `<state_dir>/initiatives/<initiative_id>/<run_id>.md`, which the row is recorded after.
-- `sha256` and `size` are the file's as the planner wrote it; the approved hash is the file's when the operator
-- approved it, their edits included, and `approved_channel` how they did. Only the operator approves one. A new plan
-- supersedes the one before it, so an initiative has at most one plan waiting or approved; an approved plan stays
-- readable once superseded, as what the next approval is compared with. Rows are never deleted.
CREATE TABLE initiative_plans (
    id                INTEGER PRIMARY KEY,
    initiative_id     INTEGER NOT NULL REFERENCES initiatives(id),
    run_id            INTEGER NOT NULL UNIQUE REFERENCES initiative_runs(id),
    created_at        TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'approved', 'superseded')),
    sha256            TEXT NOT NULL,
    size              INTEGER NOT NULL,
    approved_sha256   TEXT,
    approved_at       TEXT,
    approved_channel  TEXT CHECK (approved_channel IN ('cli', 'web')),
    CHECK ((approved_sha256 IS NULL) = (approved_at IS NULL) AND (approved_at IS NULL) = (approved_channel IS NULL)),
    CHECK (status != 'approved' OR approved_at IS NOT NULL),
    CHECK (status != 'proposed' OR approved_at IS NULL)
);
CREATE UNIQUE INDEX initiative_plans_current ON initiative_plans(initiative_id) WHERE status != 'superseded';
CREATE INDEX initiative_plans_of ON initiative_plans(initiative_id, id);
