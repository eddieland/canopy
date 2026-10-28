-- sha256 of 0100_review_dismissal_out_of_scope.sql: 7a76f6ceeb8692d91a2f252b3bfa918123573893e3228d484ecdbb6d99fc89d5

-- Rebuilds review_dismissals, which keeps the row 0020 seeded; this one is dismissed for the reason it adds.
INSERT INTO review_dismissals (review_run_id, finding, dismissed_at, channel, reason)
VALUES (1, 2, 'x', 'web', 'out_of_scope');
