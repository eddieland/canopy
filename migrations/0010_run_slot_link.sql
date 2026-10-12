-- What each slot's `.git` file held when `_run` started, before any git step (DESIGN §8, D108). Reconcile reads it to
-- check a slot whose `_run` died before putting a changed link back. NULL for a slot whose `.git` is not a file, and on
-- every slot from before this migration.

ALTER TABLE run_slots ADD COLUMN git_link BLOB;
