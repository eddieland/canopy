-- Each PR's head commit as canopy last saw it, and since when (`review.settle_minutes`, DESIGN §21, Settling). A review
-- of that commit waits until it has been the head for the settle time. A push, or a force push back to an earlier
-- commit, replaces the row and starts the wait over, so a commit pushed over soon after is never reviewed. Written by
-- `canopy review run` in a live tick only. Keyed by the PR's URL, as `review_runs.pr_url` is.

CREATE TABLE review_heads (
    pr_url   TEXT PRIMARY KEY,
    sha      TEXT NOT NULL,
    seen_at  TEXT NOT NULL
);
