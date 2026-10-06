-- Split runs (DESIGN §18, ROADMAP M8). A split run leases no worktree and pushes no branch: until joint runs (M7) it
-- reads the workspace's primary clones from the workspace root. SQLite cannot drop NOT NULL in place, so `runs` is
-- rebuilt with its slot, lease, and branch columns nullable. Nothing references `runs` yet, so the rebuild is safe with
-- foreign keys on; existing rows keep their ids.
CREATE TABLE runs_new (
    id            INTEGER PRIMARY KEY,
    tick_id       INTEGER NOT NULL REFERENCES ticks(id),
    ticket_key    TEXT NOT NULL REFERENCES tickets(key),
    kind          TEXT NOT NULL,                  -- implement | fix-ci | resume | split
    slot_path     TEXT,                           -- null for a split run, which leases nothing
    lease_id      TEXT,
    lease_holder  TEXT,
    pid           INTEGER,
    base_branch   TEXT,
    branch        TEXT,                           -- null for a split run, which pushes nothing
    started_at    TEXT NOT NULL,
    ended_at      TEXT,
    status        TEXT NOT NULL DEFAULT 'running',
        -- running | done | blocked | failed | unknown | unpushed | crashed | timeout
    result_json   TEXT,                           -- summary only; never raw logs
    log_path      TEXT NOT NULL,
    worker_pid    INTEGER,
    repo          TEXT                            -- null for a split run; its repositories are in run_repos
);
INSERT INTO runs_new (id, tick_id, ticket_key, kind, slot_path, lease_id, lease_holder, pid, base_branch, branch,
                      started_at, ended_at, status, result_json, log_path, worker_pid, repo)
    SELECT id, tick_id, ticket_key, kind, slot_path, lease_id, lease_holder, pid, base_branch, branch,
           started_at, ended_at, status, result_json, log_path, worker_pid, repo
    FROM runs;
DROP TABLE runs;
ALTER TABLE runs_new RENAME TO runs;
CREATE INDEX runs_running ON runs(status) WHERE status = 'running';
CREATE INDEX runs_ticket  ON runs(ticket_key, started_at);

-- The repositories a split run was dispatched with: the only ones its children may name. M7's run_slots supersedes it.
CREATE TABLE run_repos (
    run_id  INTEGER NOT NULL REFERENCES runs(id),
    repo    TEXT NOT NULL,
    PRIMARY KEY (run_id, repo)
);

-- The tickets a split run created, each with the one repository it is worked in. Written only by `canopy _run` from a
-- validated split result; `canopy dispatch` refuses any other repository for a child.
CREATE TABLE split_children (
    child_key   TEXT PRIMARY KEY,
    parent_key  TEXT NOT NULL,
    repo        TEXT NOT NULL,
    run_id      INTEGER NOT NULL REFERENCES runs(id)
);
CREATE INDEX split_children_parent ON split_children(parent_key);
