-- Reviews (DESIGN §21, ROADMAP M11): an adversarial read of one PR at one commit by a fresh reviewer run, in a slot
-- checked out at that commit. A review is keyed by its PR, not a ticket, so it is not a `runs` row. `ticket_key` links
-- one of the loop's own PRs to its ticket.
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

-- A decision about a PR the loop reviews carries its URL: `dispatch:review`, `wait`, `refused:<guard>`, and
-- `attention:<reason>`. An agent PR's decisions also carry its ticket key.
ALTER TABLE decisions ADD COLUMN pr TEXT;
