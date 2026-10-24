-- sha256 of 0089_late_review_holds.sql: 9ae8771f7eb3fceb2d8e6fd8a5a0b0d471e9043270fd24dc821d22cf835280cd

INSERT INTO review_holds (review_run_id, finding, kind, held_at)
VALUES ((SELECT max(id) FROM review_runs), 2, 'late', 'x');
