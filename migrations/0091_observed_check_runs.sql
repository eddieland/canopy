-- Each completed check run a `vcs` source has observed, by its run id, kept across later reads of its PR (DESIGN
-- §35). A read replaces `observed_checks` with the newest run of each context, so a re-run at the same head would
-- leave no trace of the run it repeats; this keeps it, so a `resume` for CI alone is refused `handled` when every
-- failure repeats, at the same head and context, one behind the unit's `ci` cursor. A commit status has no run and is
-- not kept. Seeded from the completed runs `observed_checks` holds now.
CREATE TABLE observed_check_runs (
    pr_url       TEXT NOT NULL,
    run_id       INTEGER NOT NULL,
    name         TEXT NOT NULL,
    head_sha     TEXT NOT NULL,
    conclusion   TEXT NOT NULL CHECK (
        conclusion IN (
            'success', 'failure', 'error', 'neutral', 'cancelled', 'skipped', 'timed_out', 'action_required',
            'startup_failure', 'stale'
        )
    ),
    observed_at  TEXT NOT NULL,
    PRIMARY KEY (pr_url, run_id)
);

INSERT INTO observed_check_runs (pr_url, run_id, name, head_sha, conclusion, observed_at)
SELECT pr_url, run_id, name, head_sha, conclusion, observed_at
FROM observed_checks
WHERE status = 'completed' AND run_id IS NOT NULL AND conclusion IS NOT NULL;
