-- How much work a plan is for the worker that follows it, as its planner judged (DESIGN §25): `small`, `medium`, or
-- `large`. NULL when the planner gave no estimate, as for every plan written before this, or one outside those.
ALTER TABLE plans ADD COLUMN effort TEXT CHECK (effort IN ('small', 'medium', 'large'));
ALTER TABLE feedback_plans ADD COLUMN effort TEXT CHECK (effort IN ('small', 'medium', 'large'));
