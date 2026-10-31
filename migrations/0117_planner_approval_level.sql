-- The `policy.planner_may_approve` level a plan was approved under on its planner's word (DESIGN §25): `strict`,
-- `normal`, or `lenient`, as the harness read it when it recorded the plan approved, with `approved_channel`
-- 'planner'. NULL for every plan the operator approved, for one not approved, and for a planner's approval from
-- before this migration, whose level was not recorded.
ALTER TABLE plans
    ADD COLUMN approved_level TEXT
        CHECK (approved_level IN ('strict', 'normal', 'lenient'))
        CHECK (approved_level IS NULL OR approved_channel IS 'planner');
ALTER TABLE feedback_plans
    ADD COLUMN approved_level TEXT
        CHECK (approved_level IN ('strict', 'normal', 'lenient'))
        CHECK (approved_level IS NULL OR approved_channel IS 'planner');
