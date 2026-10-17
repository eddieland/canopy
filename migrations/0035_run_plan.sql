-- The approved plan an `implement` or `resume` was dispatched to follow (DESIGN §25, The worker's copy): the plan its
-- prompt's `{{PLAN}}` names. `_run` writes the worker's copy of that plan alone, and refuses to start the worker when
-- it is no longer the approved plan, or its file no longer has the approved hash. NULL for a run that follows none.

ALTER TABLE runs ADD COLUMN plan_id INTEGER REFERENCES plans(id);
