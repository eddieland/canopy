-- The level of `policy.planner_may_approve` a plan run's prompt offered its planner (DESIGN §25): `off` where it was
-- asked nothing, under the key's `off` or a plan the planner's word cannot approve, and `strict`, `normal`, or
-- `lenient` where it was asked whether its plan needs review. So a report can split the plans approved by the level
-- they were written under. Set as a `plan` or `feedback_plan` run starts; NULL on every other kind, and on every plan
-- run from before this migration.
ALTER TABLE runs ADD COLUMN plan_review TEXT CHECK (plan_review IN ('off', 'strict', 'normal', 'lenient'));
