-- A lesson the operator pinned (DESIGN §28): never due for review, so its `review_at` is NULL while pinned, and served
-- before every other lesson when the digest's cap leaves some out. NULL on every lesson not pinned, and on every note
-- and proposal.
ALTER TABLE memories ADD COLUMN pinned_at TEXT;
