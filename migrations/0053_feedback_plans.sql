-- Plans before feedback runs (DESIGN §32, ROADMAP M54): one row per plan a feedback plan run wrote for what came back
-- to a ticket's PRs, and one per item it covers. As a ticket's plan's (0033), a plan's text is never here: it is the
-- file `<state_dir>/plans/<ticket_key>/<run_id>.md`, which the row is recorded after. The repositories it covers are
-- its run's slots. A new feedback plan supersedes the one before it, so a ticket has at most one waiting or approved.
-- An approval goes ahead once: the `resume` that starts on it is recorded as spending it, in the transaction that
-- inserts that run. Rows are never deleted.

CREATE TABLE feedback_plans (
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
    spent_run_id      INTEGER UNIQUE REFERENCES runs(id),
    CHECK ((approved_sha256 IS NULL) = (approved_at IS NULL) AND (approved_at IS NULL) = (approved_channel IS NULL)),
    CHECK (status != 'approved' OR approved_at IS NOT NULL),
    CHECK (status != 'proposed' OR approved_at IS NULL),
    CHECK (spent_run_id IS NULL OR approved_at IS NOT NULL)
);
CREATE UNIQUE INDEX feedback_plans_current ON feedback_plans(ticket_key) WHERE status != 'superseded';
CREATE INDEX feedback_plans_ticket ON feedback_plans(ticket_key, id);

-- Each item a feedback plan covers, in the order its result line named them: a review or a review comment of one of
-- its PRs, by the id the `vcs` source observed (DESIGN §29), what the plan proposes for it, and for a change or a
-- decline the reply it would draft. Model text, bounded as a draft's; never an instruction.
CREATE TABLE feedback_plan_items (
    plan_id   INTEGER NOT NULL REFERENCES feedback_plans(id),
    number    INTEGER NOT NULL CHECK (number > 0),
    pr_url    TEXT NOT NULL,
    item      TEXT NOT NULL CHECK (item IN ('review', 'comment')),
    item_id   INTEGER NOT NULL,
    proposal  TEXT NOT NULL CHECK (proposal IN ('change', 'decline', 'ask', 'leave')),
    reply     TEXT,
    PRIMARY KEY (plan_id, number),
    UNIQUE (plan_id, pr_url, item, item_id)
);

-- The approved feedback plan a `resume` was dispatched to follow, the one its `{{PLAN}}` names and its run spent.
ALTER TABLE runs ADD COLUMN feedback_plan_id INTEGER REFERENCES feedback_plans(id);

-- A unit's feedback plan runs are granted as its other kinds are (`canopy grant KEY feedback-plan`). SQLite cannot
-- change a CHECK in place, so `attempt_grants` is rebuilt with every row it had; nothing references it.
CREATE TABLE attempt_grants_0053 (
    id          INTEGER PRIMARY KEY,
    ticket_key  TEXT NOT NULL REFERENCES tickets(key),
    repo        TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('implement', 'fix-ci', 'resume', 'feedback-plan')),
    runs        INTEGER NOT NULL CHECK (runs > 0),
    granted_at  TEXT NOT NULL
);
INSERT INTO attempt_grants_0053 (id, ticket_key, repo, kind, runs, granted_at)
    SELECT id, ticket_key, repo, kind, runs, granted_at FROM attempt_grants;
DROP TABLE attempt_grants;
ALTER TABLE attempt_grants_0053 RENAME TO attempt_grants;
