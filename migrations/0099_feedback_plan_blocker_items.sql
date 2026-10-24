-- A merged blocker as a feedback plan's item (DESIGN §32, What a plan covers): a PR stacked on another ticket's PR
-- that merged (§10) is planned, approved, and left out by number, as a failed check and a conflict are, by an id canopy
-- gives it, below zero (`feedback_items.blocker_id`); it has no author, so no reply. SQLite cannot change a CHECK in
-- place, so `feedback_plan_items` is rebuilt with every row it had, as 0092 rebuilt it; nothing references it.
CREATE TABLE feedback_plan_items_0099 (
    plan_id   INTEGER NOT NULL REFERENCES feedback_plans(id),
    number    INTEGER NOT NULL CHECK (number > 0),
    pr_url    TEXT NOT NULL,
    item      TEXT NOT NULL CHECK (item IN ('review', 'comment', 'check', 'conflict', 'blocker')),
    item_id   INTEGER NOT NULL,
    proposal  TEXT NOT NULL CHECK (proposal IN ('change', 'decline', 'ask', 'leave')),
    reply     TEXT,
    left_out  INTEGER NOT NULL DEFAULT 0 CHECK (left_out IN (0, 1)),
    PRIMARY KEY (plan_id, number),
    UNIQUE (plan_id, pr_url, item, item_id),
    CHECK ((item IN ('check', 'conflict', 'blocker')) = (item_id < 0)),
    CHECK (item IN ('review', 'comment') OR reply IS NULL)
);
INSERT INTO feedback_plan_items_0099 (plan_id, number, pr_url, item, item_id, proposal, reply, left_out)
    SELECT plan_id, number, pr_url, item, item_id, proposal, reply, left_out FROM feedback_plan_items;
DROP TABLE feedback_plan_items;
ALTER TABLE feedback_plan_items_0099 RENAME TO feedback_plan_items;

-- The merged PR each PR a plan read was stacked on then, by URL: NULL when it was on none, or for a plan recorded
-- before this, which was offered no merged blocker, so that a blocker merging under its PR since makes it stale.
ALTER TABLE feedback_plan_prs ADD COLUMN merged_blocker TEXT;
