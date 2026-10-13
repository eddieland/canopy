-- The branch a review run's slot was leased on, its pool's base (DESIGN §21): `_review` diffs the reviewed commit
-- against where it leaves that branch, for the web UI's review page. NULL on every review run from before this
-- migration, which has no diff.

ALTER TABLE review_runs ADD COLUMN base_branch TEXT;
