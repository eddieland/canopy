-- Why a review run was run (DESIGN §21): `own`, one of the loop's own PRs, named by the ticket whose unit opened it, or
-- `query`, a PR `review.query` matched. `canopy review run` sets it, and refuses a ticket whose unit in the run's
-- repository did not open the PR, so the overseer's ticket link is checked once, when the review starts. Only an `own`
-- review's findings go to a worker. ROADMAP M42 adds `request`. Runs from before are `own` where their ticket's unit
-- has their PR now, and `query` otherwise.

ALTER TABLE review_runs ADD COLUMN purpose TEXT NOT NULL DEFAULT 'query';
UPDATE review_runs SET purpose = 'own'
WHERE ticket_key IS NOT NULL AND EXISTS (
    SELECT 1 FROM ticket_units u WHERE u.ticket_key = review_runs.ticket_key AND u.pr_url = review_runs.pr_url
);
