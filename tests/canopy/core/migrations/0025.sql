-- sha256 of 0025_severity_holds.sql: 6713bd330abfe1b596fa6a60f0afe432f91e88dc85ea41dc7d1117084a8c3e3f

-- Rebuilds `review_holds` and creates no table; a finding held for its severity shows the new kind is taken.
INSERT INTO review_holds (review_run_id, finding, kind, held_at)
VALUES ((SELECT max(id) FROM review_runs), 3, 'severity', '2026-11-24T10:00:00Z');
