-- Feedback on a unit's PR that its `review` cursor passed with no worker sent to it (DESIGN §7): which item, by
-- GitHub's id and its journal number (§35), the tick that passed it, and why. The overseer names each feedback item its
-- `ticket-set` passes; the harness names one on a resolved thread, `resolved`. A cursor never moves back, so an item is
-- passed once; one passed again, after a forget, keeps its newest reason. Kept when its PR is read again: the reader
-- rewrites `observed_reviews`, but what was decided of an item stays decided.
CREATE TABLE passed_reviews (
    pr_url      TEXT NOT NULL,
    item        TEXT NOT NULL CHECK (item IN ('review', 'comment')),
    id          INTEGER NOT NULL,
    number      INTEGER NOT NULL,
    ticket_key  TEXT NOT NULL REFERENCES tickets(key),
    repo        TEXT,
    tick_id     INTEGER NOT NULL REFERENCES ticks(id),
    reason      TEXT NOT NULL CHECK (
        reason IN (
            'optional', 'would_reset_approval', 'question', 'already_done', 'out_of_scope', 'operator_said', 'resolved'
        )
    ),
    decider     TEXT NOT NULL CHECK (decider IN ('overseer', 'harness')),
    passed_at   TEXT NOT NULL,
    PRIMARY KEY (pr_url, item, id),
    CHECK (decider = 'harness' OR reason <> 'resolved')
);
CREATE INDEX passed_reviews_ticket ON passed_reviews(ticket_key);
