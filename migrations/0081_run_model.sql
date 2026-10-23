-- The model canopy chose for a worker run's agent, from `runtime.models` (DESIGN §13, Each agent's model): what it
-- asked the runtime for, written into the agent's definition, as `provider/model`. NULL when it chose none and the run
-- went to the runtime's default, and on every run from before canopy chose one. What served it is `run_models`'.
ALTER TABLE runs ADD COLUMN model TEXT;
