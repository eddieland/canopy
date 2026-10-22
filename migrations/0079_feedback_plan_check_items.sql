-- Failed checks and conflicts as a feedback plan's items (DESIGN §32, What a plan covers): a failed check at a PR's
-- head, and the PR's conflict with its base, are items as its reviews and threads are, planned, approved, and left out
-- by number. Neither has an id the `vcs` source observed, so canopy gives each one, always below zero, where no
-- observed id is (`feedback_items.check_id`, `feedback_items.conflict_id`); neither has an author, so neither has a
-- reply. SQLite cannot change a CHECK in place, so `feedback_plan_items` is rebuilt with every row it had; nothing
-- references it.
CREATE TABLE feedback_plan_items_0078 (
    plan_id   INTEGER NOT NULL REFERENCES feedback_plans(id),
    number    INTEGER NOT NULL CHECK (number > 0),
    pr_url    TEXT NOT NULL,
    item      TEXT NOT NULL CHECK (item IN ('review', 'comment', 'check', 'conflict')),
    item_id   INTEGER NOT NULL,
    proposal  TEXT NOT NULL CHECK (proposal IN ('change', 'decline', 'ask', 'leave')),
    reply     TEXT,
    left_out  INTEGER NOT NULL DEFAULT 0 CHECK (left_out IN (0, 1)),
    PRIMARY KEY (plan_id, number),
    UNIQUE (plan_id, pr_url, item, item_id),
    CHECK ((item IN ('check', 'conflict')) = (item_id < 0)),
    CHECK (item IN ('review', 'comment') OR reply IS NULL)
);
INSERT INTO feedback_plan_items_0078 (plan_id, number, pr_url, item, item_id, proposal, reply, left_out)
    SELECT plan_id, number, pr_url, item, item_id, proposal, reply, left_out FROM feedback_plan_items;
DROP TABLE feedback_plan_items;
ALTER TABLE feedback_plan_items_0078 RENAME TO feedback_plan_items;

-- Whether each PR a plan read conflicted with its base then: 1 or 0 as its host said, and NULL while it had not said,
-- or for a plan recorded before this, so that a conflict on its PR since makes it stale only once both are known.
ALTER TABLE feedback_plan_prs ADD COLUMN conflicted INTEGER CHECK (conflicted IN (0, 1));
