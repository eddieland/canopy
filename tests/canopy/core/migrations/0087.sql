-- sha256 of 0087_review_answers.sql: 4e97215fc19beec71d987d29d39044fb729c41ccf02c19814bdda19849115fbb

INSERT INTO review_answers (run_id, review_run_id, finding, answer, reason)
VALUES ((SELECT min(id) FROM runs), (SELECT min(id) FROM review_runs), 1, 'declined', 'The retry is bounded.');
INSERT INTO review_holds (review_run_id, finding, kind, rebuts_run_id, rebuts_finding, held_at)
VALUES ((SELECT max(id) FROM review_runs), 1, 'rebuttal', (SELECT min(id) FROM review_runs), 1, 'x');
