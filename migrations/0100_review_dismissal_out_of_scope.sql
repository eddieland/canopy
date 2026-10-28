-- `out_of_scope`, a fourth reason the operator dismisses a review's finding for (DESIGN §21): it holds and is worth
-- fixing, but belongs in another PR. Like `intentional` and `not_worth_it`, it is a finding that held, not the
-- reviewer's noise. SQLite cannot change a CHECK in place, so `review_dismissals` is rebuilt with every row it had, as
-- 0086 rebuilt `connector_runs`; nothing references it, and it has no index.
CREATE TABLE review_dismissals_0100 (
    review_run_id  INTEGER NOT NULL REFERENCES review_runs(id),
    finding        INTEGER NOT NULL CHECK (finding > 0),
    dismissed_at   TEXT NOT NULL,
    channel        TEXT NOT NULL CHECK (channel IN ('cli', 'web')),
    reason         TEXT CHECK (reason IN ('wrong', 'intentional', 'not_worth_it', 'out_of_scope')),
    PRIMARY KEY (review_run_id, finding)
);
INSERT INTO review_dismissals_0100 (review_run_id, finding, dismissed_at, channel, reason)
    SELECT review_run_id, finding, dismissed_at, channel, reason FROM review_dismissals;
DROP TABLE review_dismissals;
ALTER TABLE review_dismissals_0100 RENAME TO review_dismissals;
