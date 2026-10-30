-- The model the operator chose for a review request's reviews (DESIGN §13, Each agent's model; §21): every review the
-- request makes runs its reviewer on it, in place of the PR's ticket's override and `runtime.models.reviewer`, as
-- `provider/model[@variant]`. NULL when the request chose none. Set only by the operator, with
-- `canopy start URL --review --model` or the web UI; asking again with a model replaces it on the open request.
ALTER TABLE review_requests ADD COLUMN model TEXT;
