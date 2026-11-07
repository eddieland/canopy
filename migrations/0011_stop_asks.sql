-- When the operator asked to end a running run now (`canopy stop --now`, or a stop from the web UI that ends its run),
-- written before its processes are killed (DESIGN §22). Reconcile closes a run it finds gone with this set `stopped`,
-- not `crashed`: the stop that killed it did not live to close it. NULL for every other run, and for every run from
-- before this migration.
ALTER TABLE runs ADD COLUMN stop_asked_at TEXT;
ALTER TABLE task_runs ADD COLUMN stop_asked_at TEXT;
ALTER TABLE epic_runs ADD COLUMN stop_asked_at TEXT;
