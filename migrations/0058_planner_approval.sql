-- A plan the planner said needs no review (DESIGN §25, §32): under `policy.planner_may_approve`, the harness approves
-- it as the planner wrote it, with `approved_channel` 'planner', and keeps the planner's one-line reason here, which
-- every such approval has. NULL for every plan the operator approved, and for one not approved.
ALTER TABLE plans
    ADD COLUMN approved_reason TEXT CHECK ((approved_channel IS 'planner') = (approved_reason IS NOT NULL));
ALTER TABLE feedback_plans
    ADD COLUMN approved_reason TEXT CHECK ((approved_channel IS 'planner') = (approved_reason IS NOT NULL));
