-- The operator's requests to review a PR the loop does not own (DESIGN §21, ROADMAP M42): `canopy start URL --review`,
-- or the web UI's pull requests page. A request authorizes one review of its PR at its head, as `review.query` would;
-- the overseer names the repository it is in when it runs the review. It ends when a review of it ends `done`, when the
-- overseer reads that the PR merged or closed first or is in none of the workspace's repositories, or when the operator
-- stops it. At most one open request per PR. Rows are kept once ended, so a PR's page shows who ended its request and
-- why. No agent canopy runs can add one.

CREATE TABLE review_requests (
    id          INTEGER PRIMARY KEY,
    pr_url      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    channel     TEXT NOT NULL,
    ended_at    TEXT,
    end_reason  TEXT CHECK (end_reason IN ('reviewed', 'merged', 'closed', 'unknown_repo', 'stopped')),
    CHECK ((ended_at IS NULL) = (end_reason IS NULL))
);
CREATE UNIQUE INDEX review_requests_open ON review_requests(pr_url) WHERE ended_at IS NULL;
CREATE INDEX review_requests_pr ON review_requests(pr_url, id);
