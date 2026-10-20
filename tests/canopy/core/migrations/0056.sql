-- sha256 of 0056_review_notes.sql: aaf62c8219fa4d7818a1ed5b2111b9135cc96f28669efaa52dc08509a891b6d1

INSERT INTO review_notes (ticket_key, key, body, status, review_run_id, sha, created_at)
VALUES ('OLD-1', 'checked-retry-path', 'The retry path drops the last error.', 'active', 1, 'abc', 'x');
INSERT INTO review_memory (review_run_id, review_notes) VALUES (1, 'use');
INSERT INTO review_note_reads (review_run_id, note_id) VALUES (1, 1);
