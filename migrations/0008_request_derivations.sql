-- What a tick derived in shadow for each of the operator's open review requests (DESIGN §21, §30): what the harness
-- would do with it, read from the `vcs` source's observation of its PR and the journal's review runs. `action` is
-- `start` its review at `head_sha`, `wait` for `reason`, or `end` the request with `reason`, an end reason of
-- `review_requests`. `stale` is the observation stale or missing that the request rests on, and the action is then
-- `wait`; NULL when it was derived. `head_sha` is the PR's head as observed, NULL when no fresh read gave one.
-- Recorded beside `derivations`, and read only to compare with the overseer's decisions about the PR in that tick
-- (`canopy agreement`); nothing the overseer, a worker, or a guard reads changes.
CREATE TABLE request_derivations (
    id          INTEGER PRIMARY KEY,
    tick_id     INTEGER NOT NULL REFERENCES ticks(id),
    request_id  INTEGER NOT NULL REFERENCES review_requests(id),
    pr_url      TEXT NOT NULL,
    action      TEXT NOT NULL CHECK (action IN ('start', 'wait', 'end')),
    reason      TEXT,
    head_sha    TEXT,
    stale       TEXT,
    CHECK (stale IS NULL OR action = 'wait')
);

CREATE INDEX request_derivations_tick ON request_derivations(tick_id);
