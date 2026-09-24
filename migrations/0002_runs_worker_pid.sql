-- The worker agent's pid, recorded by `canopy _run` when it starts the worker. The worker leads its own process group,
-- so if `_run` is killed outright, reconcile can still stop the worker before returning its slot.
ALTER TABLE runs ADD COLUMN worker_pid INTEGER;
