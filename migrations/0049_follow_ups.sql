-- Follow-up tickets (DESIGN §18, ROADMAP M46). An `implement` or `resume` worker that files tickets outside its own
-- reports them in its result, and `_run` records each one its checks pass, in the transaction that closes the run: the
-- follow-up's key, its parent (the run's ticket), the run, the repository it is for or NULL, and when. A recorded
-- follow-up authorizes nothing: canopy asks the operator about it until a queue label or a start authorizes it, as any
-- ticket. Written only from a validated result, never by a command; rows are never deleted. The follow-up is a ticket
-- of the tracker's and may never appear in `tickets`, so it has no foreign key; the parent does, since its dispatch
-- recorded it.
CREATE TABLE follow_ups (
    key         TEXT PRIMARY KEY,
    parent_key  TEXT NOT NULL REFERENCES tickets(key),
    run_id      INTEGER NOT NULL REFERENCES runs(id),
    repo        TEXT,
    at          TEXT NOT NULL
);
CREATE INDEX follow_ups_parent ON follow_ups(parent_key);
