-- canopy journal. Loop facts only. World facts are re-read from their source.
-- Applied by db.py inside a transaction; recorded in schema_migrations.
-- The schema as of v0.1: the migrations before it were squashed into this one (D068).

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
    status      TEXT NOT NULL DEFAULT 'running',
        -- running | ok | skipped | overseer_failed | reconcile_failed | abandoned
    summary     TEXT
);

-- One row per ticket key ever seen. The comment cursor makes ticks incremental. Attempt counts and the fix-ci cooldown
-- are derived from `runs` (D030). phase is the ticket's own last derived phase, for display only; never read as truth.
-- branch is the ticket's branch name, fixed by its first implement and the same in every unit.
CREATE TABLE tickets (
    key                 TEXT PRIMARY KEY,
    repo                TEXT NOT NULL,   -- the workspace root
    first_seen_at       TEXT NOT NULL,
    last_seen_at        TEXT NOT NULL,
    phase               TEXT,
    branch              TEXT,
    last_comment_id     TEXT,
    needs_human_since   TEXT,
    done                INTEGER NOT NULL DEFAULT 0
);

-- One row per worker execution. Source for capacity, crash detection, attempts. Its slots are in `run_slots`.
CREATE TABLE runs (
    id            INTEGER PRIMARY KEY,
    tick_id       INTEGER NOT NULL REFERENCES ticks(id),
    ticket_key    TEXT NOT NULL REFERENCES tickets(key),
    kind          TEXT NOT NULL,                  -- implement | fix-ci | resume | split
    pid           INTEGER,                        -- canopy _run
    branch        TEXT NOT NULL,                  -- empty for a split, which works on none
    started_at    TEXT NOT NULL,
    ended_at      TEXT,
    status        TEXT NOT NULL DEFAULT 'running',
        -- running | done | blocked | failed | unknown | unpushed | crashed | timeout
    result_json   TEXT,                           -- summary only; never raw logs
    log_path      TEXT NOT NULL,
    -- The worker agent, which leads its own process group, so if `_run` is killed outright, reconcile can still stop
    -- the worker before returning its slots.
    worker_pid    INTEGER
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
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    -- An attention item may be about a repository or a ticket's unit; one about a repository has no ticket key.
    repo        TEXT,
    -- A decision about a chore carries its name and no ticket key: `dispatch:chore`, `wait`, `refused:<guard>`, and
    -- the harness's `attention:chore_failed`.
    chore       TEXT,
    -- A decision about a PR the loop reviews carries its URL: `dispatch:review`, `wait`, `refused:<guard>`, and
    -- `attention:<reason>`. An agent PR's decisions also carry its ticket key.
    pr          TEXT
);
CREATE INDEX decisions_tick ON decisions(tick_id);

-- Attention items each notification sink was told about and that are still open, so a diff never re-notifies (D032).
CREATE TABLE notifications (
    sink         TEXT NOT NULL,
    fingerprint  TEXT NOT NULL,   -- sha256 of ticket_key, reason, and repo when there is one
    ticket_key   TEXT,
    reason       TEXT NOT NULL,
    repo         TEXT,
    sent_at      TEXT NOT NULL,
    PRIMARY KEY (sink, fingerprint)
);

-- Units and joint runs (DESIGN §18). A ticket's work is divided into units, one per repository it changes, each with
-- its own branch, PR, phase, and review and ci cursors; the comment cursor and the ticket's own phase stay on
-- `tickets`. A run may lease a slot in several repositories, one `run_slots` row each.
CREATE TABLE ticket_units (
    ticket_key      TEXT NOT NULL REFERENCES tickets(key),
    repo            TEXT,
    branch          TEXT,
    pr_url          TEXT,
    phase           TEXT,
    last_review_id  TEXT,
    last_ci_run_id  TEXT,
    UNIQUE (ticket_key, repo)
);

CREATE TABLE run_slots (
    run_id        INTEGER NOT NULL REFERENCES runs(id),
    repo          TEXT,
    slot_path     TEXT NOT NULL,
    lease_id      TEXT NOT NULL,
    lease_holder  TEXT NOT NULL,
    base_branch   TEXT,
    UNIQUE (run_id, repo)
);
CREATE INDEX run_slots_lease ON run_slots(lease_id);

-- Split tickets (DESIGN §18). A split run creates one child ticket per repository in the tracker; `_run` records each
-- child it reported, after validating the result, with the repository it covers. A child is dispatched only in that
-- repository. The child is an ordinary ticket of the tracker's and may never appear in `tickets`, so it has no foreign
-- key; the parent does, since its dispatch recorded it.
CREATE TABLE split_children (
    child_key   TEXT PRIMARY KEY,
    parent_key  TEXT NOT NULL REFERENCES tickets(key),
    repo        TEXT NOT NULL,
    run_id      INTEGER NOT NULL REFERENCES runs(id)
);
CREATE INDEX split_children_parent ON split_children(parent_key);

-- Chores (DESIGN §19): recurring agent runs the operator defines and the overseer delegates. A chore run holds no slot
-- and works on no ticket, so it is not a `runs` row. Its result is a summary and findings, kept as the validated result
-- in `result_json`.
CREATE TABLE chore_runs (
    id           INTEGER PRIMARY KEY,
    tick_id      INTEGER NOT NULL REFERENCES ticks(id),
    chore        TEXT NOT NULL,
    pid          INTEGER,           -- canopy _chore
    agent_pid    INTEGER,           -- the chore's agent, which leads its own process group
    started_at   TEXT NOT NULL,
    ended_at     TEXT,
    status       TEXT NOT NULL DEFAULT 'running',  -- running | ok | failed | unknown | timeout | crashed
    result_json  TEXT,
    log_path     TEXT NOT NULL
);
CREATE INDEX chore_runs_chore ON chore_runs(chore, started_at);
CREATE INDEX chore_runs_running ON chore_runs(status) WHERE status = 'running';

-- Notification sinks (DESIGN §20). Point events go to an outbox, written in the transaction that records the fact, and
-- each sink has a cursor: the newest event it delivered. AUTOINCREMENT keeps ids rising after old events are pruned,
-- so an event never gets an id a cursor already passed.
CREATE TABLE notify_events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    grp     TEXT NOT NULL,   -- loop | runs | chores
    kind    TEXT NOT NULL,
        -- run.started | run.ended | chore.ended | loop.failing | loop.recovered | loop.sink_failing
    at      TEXT NOT NULL,
    fields  TEXT NOT NULL    -- JSON object; text cut to its limits, one line
);

CREATE TABLE notify_sinks (
    name              TEXT PRIMARY KEY,
    cursor            INTEGER NOT NULL,   -- the newest notify_events id delivered, or passed over
    created_at        TEXT NOT NULL,
    last_delivery_at  TEXT,
    last_digest_at    TEXT,
    failures          INTEGER NOT NULL DEFAULT 0,  -- consecutive failed deliveries
    last_error        TEXT
);

-- Reviews (DESIGN §21): an adversarial read of one PR at one commit by a fresh reviewer run, in a slot checked out at
-- that commit. A review is keyed by its PR, not a ticket, so it is not a `runs` row. `ticket_key` links one of the
-- loop's own PRs to its ticket.
CREATE TABLE review_runs (
    id            INTEGER PRIMARY KEY,
    tick_id       INTEGER NOT NULL REFERENCES ticks(id),
    pr_url        TEXT NOT NULL,
    sha           TEXT NOT NULL,
    ticket_key    TEXT,
    repo          TEXT,             -- the repository whose pool the slot came from; NULL in a workspace of one
    slot_path     TEXT,
    lease_id      TEXT,
    lease_holder  TEXT,
    pid           INTEGER,           -- canopy _review
    agent_pid     INTEGER,           -- the reviewer agent, which leads its own process group
    started_at    TEXT NOT NULL,
    ended_at      TEXT,
    status        TEXT NOT NULL DEFAULT 'running',  -- running | done | failed | unknown | timeout | crashed
    result_json   TEXT,
    log_path      TEXT NOT NULL
);
CREATE INDEX review_runs_pr ON review_runs(pr_url, started_at);
CREATE INDEX review_runs_running ON review_runs(status) WHERE status = 'running';

INSERT INTO schema_migrations (version, name) VALUES (1, 'init');
