-- Plans before implementing (DESIGN §25, ROADMAP M44): one row per plan a plan run wrote, and the ticket's own plan
-- setting. A plan's text is never here: it is the file `<state_dir>/plans/<ticket_key>/<run_id>.md`, which the row is
-- recorded after. `sha256` and `size` are the file's as the planner wrote it; the approved hash is the file's when the
-- operator approved it, their edits included, and `approved_channel` how they did. A new plan, a request for one, or a
-- skip supersedes the one before it, so a ticket has at most one plan waiting or approved. Rows are never deleted.

CREATE TABLE plans (
    id                INTEGER PRIMARY KEY,
    ticket_key        TEXT NOT NULL REFERENCES tickets(key),
    run_id            INTEGER NOT NULL UNIQUE REFERENCES runs(id),
    created_at        TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'approved', 'superseded')),
    sha256            TEXT NOT NULL,
    size              INTEGER NOT NULL,
    approved_sha256   TEXT,
    approved_at       TEXT,
    approved_channel  TEXT,
    CHECK ((approved_sha256 IS NULL) = (approved_at IS NULL) AND (approved_at IS NULL) = (approved_channel IS NULL)),
    CHECK (status != 'approved' OR approved_at IS NOT NULL),
    CHECK (status != 'proposed' OR approved_at IS NULL)
);
CREATE UNIQUE INDEX plans_current ON plans(ticket_key) WHERE status != 'superseded';
CREATE INDEX plans_ticket ON plans(ticket_key, id);

-- Whether this ticket is planned whatever `policy.plan` says: `plan` asks for one, `skip` waives it, NULL follows the
-- policy. Set only by the operator's channels (DESIGN §22), never by the overseer or a worker.
ALTER TABLE tickets ADD COLUMN plan_setting TEXT CHECK (plan_setting IN ('plan', 'skip'));
