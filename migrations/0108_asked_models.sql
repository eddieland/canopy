-- The model canopy chose for a review's, a chore's, and a task's agent, and for a tick's overseer (DESIGN §13, Each
-- agent's model), as a worker run records it in `runs.model`: what it asked the runtime for, written into the agent's
-- definition, as `provider/model[@variant]`. NULL when it chose none and the runtime's default served it, on a tick
-- whose overseer did not run, and on every run and tick from before this migration. What served it is `run_models`'.
ALTER TABLE ticks ADD COLUMN model TEXT;
ALTER TABLE review_runs ADD COLUMN model TEXT;
ALTER TABLE chore_runs ADD COLUMN model TEXT;
ALTER TABLE task_runs ADD COLUMN model TEXT;
