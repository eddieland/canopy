-- The pushes canopy made to rerun a PR's checks a worker judged flaky (DESIGN §23): its branch rebased onto its base
-- and pushed with a lease, under `trust.max_flaky_kicks`. Each kick's head is the next one's `from_head`, so the
-- chain back from a branch's head counts the kicks spent on it since a push of work, which starts a new chain.
CREATE TABLE flaky_kicks (
    run_id     INTEGER NOT NULL REFERENCES runs(id),
    repo       TEXT NOT NULL,
    branch     TEXT NOT NULL,
    -- The commit origin's branch held before the kick, and the rebased commit the kick pushed in its place.
    from_head  TEXT NOT NULL,
    to_head    TEXT NOT NULL,
    kicked_at  TEXT NOT NULL,
    PRIMARY KEY (run_id, repo)
);
CREATE INDEX flaky_kicks_by_branch ON flaky_kicks (repo, branch);
