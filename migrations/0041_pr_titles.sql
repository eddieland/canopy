-- A PR's own title (DESIGN §8, §22), which need not be its ticket's: the one the worker that opened or last updated it
-- reported in its result's `pr_titles`. For display; never read as truth. Keyed by the PR's URL, as
-- `review_runs.pr_url` is, so it outlives `canopy forget`, which drops the unit but not the PR or its reviews.

CREATE TABLE pr_titles (
    pr_url      TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
