-- sha256 of 0114_observed_pr_times.sql: 44080223e6474aafbb007683d5eeb2a7d9a4df7dcbce7eb0e1fe6d9e5b5b1448

UPDATE observed_prs SET created_at = '2026-10-17T09:00:00.000Z', ready_at = '2026-10-17T09:00:00.000Z',
    review_requested_at = '2026-10-17T10:00:00.000Z', merged_at = '2026-10-19T15:00:00.000Z',
    closed_at = '2026-10-19T15:00:00.000Z'
WHERE url = (SELECT min(url) FROM observed_prs);
