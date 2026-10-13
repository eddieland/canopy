-- Review runs the operator granted a PR beyond `policy.max_reviews_per_pr` (`canopy grant <PR> review`, DESIGN §21,
-- §22). Rows are only added: a PR's limit is the policy's plus the sum of its grants, and every review run still
-- counts (D030). Keyed by the PR's URL, as `review_runs.pr_url` is. No agent canopy runs can add one.

CREATE TABLE review_grants (
    id          INTEGER PRIMARY KEY,
    pr_url      TEXT NOT NULL,
    runs        INTEGER NOT NULL CHECK (runs > 0),
    granted_at  TEXT NOT NULL
);
CREATE INDEX review_grants_pr ON review_grants(pr_url);
