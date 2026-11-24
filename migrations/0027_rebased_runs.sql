-- Whether a worker's or a task's run rewrote its branch (DESIGN §45): 1 when the commit it started from is not an
-- ancestor of the one its diffs are of, as a rebase leaves it; 0 when it is; NULL when canopy could not tell, the run
-- left no commit to read, or it was recorded before this column.
ALTER TABLE run_changes ADD COLUMN rebased INTEGER CHECK (rebased IN (0, 1));
