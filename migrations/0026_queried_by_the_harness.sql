-- A `queried` decision records what the tracker query a source read returned, which the harness records on its own
-- before the overseer runs (DESIGN §37). canopy recorded each as the overseer's, so every split of decisions by who
-- made them counted the overseer one decision too many for each tick that ran the query. Each is the harness's.
UPDATE decisions SET decider = 'harness' WHERE action = 'queried';
