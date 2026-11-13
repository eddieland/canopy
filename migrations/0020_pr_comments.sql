-- A comment on a PR's conversation, on no line of its diff, is observed as a review item of its own, `pr_comment`
-- (DESIGN §29, §30): GitHub keeps it apart from a review and from a review thread's comment, with ids of its own, so
-- it is keyed by its kind as they are. It has no thread, no review, and no state. It takes a journal number when first
-- observed (§35), as each review item does, its kind `pr_comment`; a feedback plan may cover it (§32) and a `review`
-- cursor may pass it (§7), so the tables that name a review item's kind take the new one. SQLite cannot change a
-- CHECK, so each of the five is rebuilt with every row and index it had. No table references any of them.

CREATE TABLE observed_reviews_new (
    pr_url       TEXT NOT NULL,
    item         TEXT NOT NULL CHECK (item IN ('review', 'comment', 'pr_comment')),
    id           INTEGER NOT NULL,
    author       TEXT,
    bot          INTEGER NOT NULL,
    -- A review's state; NULL for a comment.
    state        TEXT CHECK (state IN ('pending', 'commented', 'approved', 'changes_requested', 'dismissed')),
    created_at   TEXT,
    body         TEXT NOT NULL,
    url          TEXT,
    -- A comment's review, and its thread: GitHub's node id, where it is, and whether it is outdated or resolved.
    review_id    INTEGER,
    thread_id    TEXT,
    path         TEXT,
    line         INTEGER,
    side         TEXT CHECK (side IN ('left', 'right')),
    outdated     INTEGER,
    resolved     INTEGER,
    observed_at  TEXT NOT NULL,
    number       INTEGER,
    PRIMARY KEY (pr_url, item, id),
    CHECK ((item = 'comment') = (thread_id IS NOT NULL)),
    CHECK (item = 'review' OR state IS NULL),
    CHECK (item <> 'pr_comment' OR review_id IS NULL)
);
INSERT INTO observed_reviews_new SELECT * FROM observed_reviews;
DROP TABLE observed_reviews;
ALTER TABLE observed_reviews_new RENAME TO observed_reviews;
CREATE INDEX observed_reviews_thread ON observed_reviews(thread_id);

CREATE TABLE item_numbers_new (
    number         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind           TEXT NOT NULL CHECK (
        kind IN ('comment', 'review', 'review_comment', 'pr_comment', 'check_run', 'review_run')
    ),
    subject        TEXT NOT NULL,
    id             TEXT NOT NULL,
    numbered_at    TEXT NOT NULL,
    shown_tick_id  INTEGER REFERENCES ticks(id),
    UNIQUE (subject, kind, id)
);
INSERT INTO item_numbers_new (number, kind, subject, id, numbered_at, shown_tick_id)
SELECT number, kind, subject, id, numbered_at, shown_tick_id FROM item_numbers;
-- A number is never given twice: the new table goes on from the highest the old one ever gave, not the highest kept.
DELETE FROM sqlite_sequence WHERE name = 'item_numbers_new';
INSERT INTO sqlite_sequence (name, seq) SELECT 'item_numbers_new', seq FROM sqlite_sequence WHERE name = 'item_numbers';
DROP TABLE item_numbers;
ALTER TABLE item_numbers_new RENAME TO item_numbers;

CREATE TABLE passed_reviews_new (
    pr_url      TEXT NOT NULL,
    item        TEXT NOT NULL CHECK (item IN ('review', 'comment', 'pr_comment')),
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
INSERT INTO passed_reviews_new SELECT * FROM passed_reviews;
DROP TABLE passed_reviews;
ALTER TABLE passed_reviews_new RENAME TO passed_reviews;
CREATE INDEX passed_reviews_ticket ON passed_reviews(ticket_key);

-- A comment on the PR's conversation may carry a reply, as a review may: the plan's words for the PR's comment.
CREATE TABLE feedback_plan_items_new (
    plan_id   INTEGER NOT NULL REFERENCES feedback_plans(id),
    number    INTEGER NOT NULL CHECK (number > 0),
    pr_url    TEXT NOT NULL,
    item      TEXT NOT NULL CHECK (item IN ('review', 'comment', 'pr_comment', 'check', 'conflict', 'blocker')),
    item_id   INTEGER NOT NULL,
    proposal  TEXT NOT NULL CHECK (proposal IN ('change', 'decline', 'ask', 'leave')),
    reply     TEXT,
    -- Approval by item (DESIGN §32, Approving): the operator may approve a feedback plan with some of its items left
    -- out, which its `resume` must not act on and the next plan is offered again. `left_out` is 1 for such an item of
    -- an approved plan, 0 otherwise; approving again sets it afresh, and approving whole clears it.
    left_out  INTEGER NOT NULL DEFAULT 0 CHECK (left_out IN (0, 1)),
    PRIMARY KEY (plan_id, number),
    UNIQUE (plan_id, pr_url, item, item_id),
    CHECK ((item IN ('check', 'conflict', 'blocker')) = (item_id < 0)),
    CHECK (item IN ('review', 'comment', 'pr_comment') OR reply IS NULL)
);
INSERT INTO feedback_plan_items_new SELECT * FROM feedback_plan_items;
DROP TABLE feedback_plan_items;
ALTER TABLE feedback_plan_items_new RENAME TO feedback_plan_items;

CREATE TABLE feedback_plan_seen_new (
    plan_id      INTEGER NOT NULL REFERENCES feedback_plans(id),
    pr_url       TEXT NOT NULL,
    item         TEXT NOT NULL CHECK (item IN ('review', 'comment', 'pr_comment')),
    item_id      INTEGER NOT NULL,
    thread_id    TEXT,
    author       TEXT,
    body_sha256  TEXT NOT NULL,
    answers      INTEGER,
    PRIMARY KEY (plan_id, pr_url, item, item_id),
    CHECK ((item = 'comment') = (thread_id IS NOT NULL)),
    CHECK (answers IS NULL OR item = 'comment')
);
INSERT INTO feedback_plan_seen_new SELECT * FROM feedback_plan_seen;
DROP TABLE feedback_plan_seen;
ALTER TABLE feedback_plan_seen_new RENAME TO feedback_plan_seen;
