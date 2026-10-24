-- sha256 of 0090_late_review_holds.sql: cdd24ad662e761c6fa32585220a3c3e7ab8a4d0ff2d4ea496f5be94300e385c5

INSERT INTO review_holds (review_run_id, finding, kind, held_at)
VALUES ((SELECT max(id) FROM review_runs), 2, 'late', 'x');
