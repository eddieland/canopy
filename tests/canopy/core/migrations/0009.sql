-- sha256 of 0009_request_derivations.sql: dfae96a4bf85ff6fee650861ea736d5a0c986027d5a9d10de8b8b52f7b96a034

INSERT INTO request_derivations (tick_id, request_id, pr_url, action, reason, head_sha, stale)
VALUES (
    (SELECT min(id) FROM ticks), (SELECT min(id) FROM review_requests), 'https://e.test/pr/7', 'start', NULL, 'abc1234',
    NULL
);
