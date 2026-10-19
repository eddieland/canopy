-- Triage before a plan (DESIGN §25, ROADMAP M55). `run_reads` holds the repositories a run that leases no slot reads,
-- by name, as dispatch named them: a `triage-plan` run reads each one's primary clone through a link in its desk, and
-- `run_slots` holds only leases. `plan_waivers` holds each plan a triage waived: the triage run, and the reason its
-- validated `done` `trivial` result gave, written by `_run` in the transaction that closes the run, never by an agent
-- and by no command. A waiver is in force while its ticket's own plan setting is unset and no forget came after its
-- run; rows are never deleted.

CREATE TABLE run_reads (
    run_id  INTEGER NOT NULL REFERENCES runs(id),
    repo    TEXT NOT NULL,
    PRIMARY KEY (run_id, repo)
);

CREATE TABLE plan_waivers (
    id          INTEGER PRIMARY KEY,
    ticket_key  TEXT NOT NULL REFERENCES tickets(key),
    run_id      INTEGER NOT NULL UNIQUE REFERENCES runs(id),
    reason      TEXT NOT NULL,
    at          TEXT NOT NULL
);
CREATE INDEX plan_waivers_ticket ON plan_waivers(ticket_key, id);
