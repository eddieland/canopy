-- Drafts that start from a feedback plan (DESIGN §32, On the PR, and the drafts after): a `resume` that follows an
-- approved feedback plan starts each thread's draft from the reply the plan proposed for its item. `plan_item` is the
-- number of that item in its run's feedback plan (`runs.feedback_plan_id`), recorded by `_run` as it writes the draft,
-- or by the read that checks it when only that read places the draft's comment on the item's thread. Whether the draft
-- departs from the proposal is computed from the two texts, never said by the worker. NULL for a draft whose run
-- followed no feedback plan, and for one answering no thread the plan covers.
ALTER TABLE drafts ADD COLUMN plan_item INTEGER CHECK (plan_item > 0);
