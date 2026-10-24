-- sha256 of 0094_late_review_holds.sql: 1e2b9abe99d2582646bae8e0fdb45a5c4bd0f25c21f596493b6ccc821b446871

INSERT INTO review_holds (review_run_id, finding, kind, held_at)
VALUES ((SELECT max(id) FROM review_runs), 2, 'late', 'x');
