-- When canopy first saw each head commit of a PR it may review (`review.settle_minutes`, DESIGN §21). A review of that
-- commit waits until it has been seen for the settle time, so a push that follows soon after starts the wait over and
-- the earlier commit is never reviewed. Written by `canopy review run` in a live tick only.
-- Keyed by the PR's URL, as `review_runs.pr_url` is.

CREATE TABLE review_heads (
    pr_url   TEXT NOT NULL,
    sha      TEXT NOT NULL,
    seen_at  TEXT NOT NULL,
    PRIMARY KEY (pr_url, sha)
);
