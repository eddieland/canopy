-- Each run of a commit status a `vcs` source has observed, kept across later reads of its PR (DESIGN §35), for the CI
-- page. A status has no run id, and a read replaces `observed_checks` with its newest state, so a run is told from
-- what canopy saw of its context at one head: one seen pending again, or done with another conclusion, is a new run.
-- `conclusion` is NULL while it runs; `observed_at` is when it was first seen in the state the row holds. Seeded from
-- the completed statuses `observed_checks` holds now.
CREATE TABLE observed_status_runs (
    id           INTEGER PRIMARY KEY,
    pr_url       TEXT NOT NULL,
    name         TEXT NOT NULL,
    head_sha     TEXT NOT NULL,
    conclusion   TEXT CHECK (
        conclusion IN (
            'success', 'failure', 'error', 'neutral', 'cancelled', 'skipped', 'timed_out', 'action_required',
            'startup_failure', 'stale'
        )
    ),
    observed_at  TEXT NOT NULL
);
CREATE INDEX observed_status_runs_context ON observed_status_runs(pr_url, name, head_sha);
CREATE INDEX observed_status_runs_observed ON observed_status_runs(observed_at);

INSERT INTO observed_status_runs (pr_url, name, head_sha, conclusion, observed_at)
SELECT pr_url, name, head_sha, conclusion, observed_at
FROM observed_checks
WHERE status = 'completed' AND run_id IS NULL AND conclusion IS NOT NULL;
