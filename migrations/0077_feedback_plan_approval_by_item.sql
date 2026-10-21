-- Approval by item (DESIGN §32, Approving): the operator may approve a feedback plan with some of its items left out,
-- which its `resume` must not act on and the next plan is offered again. `left_out` is 1 for such an item of an
-- approved plan, 0 otherwise; approving again sets it afresh, and approving whole clears it.
ALTER TABLE feedback_plan_items ADD COLUMN left_out INTEGER NOT NULL DEFAULT 0 CHECK (left_out IN (0, 1));

-- The operator message the approval wrote on the ticket, naming the plan and its items by number, with the
-- operator's own words when they gave some: the instruction its `resume` reads beside the plan. NULL for a plan not
-- approved, and for one its planner approved, which writes no message.
ALTER TABLE feedback_plans ADD COLUMN approved_message_id INTEGER REFERENCES messages(id);
