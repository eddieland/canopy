-- The ids of its epic's approved plan a member ticket's plan departs from, as its planner's result named them (DESIGN
-- §43): a comma-separated list of requirements and contracts, each one the epic plan it was written against holds.
-- NULL for a plan that departs from none, a plan of no epic, and every plan from before this migration. The harness
-- raises `epic_drift` on the member while such a plan waits on the operator.
ALTER TABLE plans ADD COLUMN epic_drift TEXT;
