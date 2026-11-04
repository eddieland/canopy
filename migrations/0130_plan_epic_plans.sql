-- The epic plan a member ticket's plan was written against (DESIGN §43): the plan the operator had approved for the
-- member's epic when its planner ran, whose approved copy the planner read. NULL for a ticket of no epic, one whose
-- epic had no approved plan then, and every plan from before this migration. What reaches a member when its epic's
-- plan changes is judged against this plan.
ALTER TABLE plans ADD COLUMN epic_plan_id INTEGER REFERENCES epic_plans(id);
