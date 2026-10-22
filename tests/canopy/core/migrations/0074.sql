-- sha256 of 0074_review_revisions.sql: bf1c2a2a4f42e0e508c40ff462e7d8e650342317aad7c0ca63141b4b4fc067e4

INSERT INTO review_draft_notes (draft_id, after_version, body, channel, created_at)
VALUES ((SELECT min(id) FROM review_drafts), 1, 'Say it more gently.', 'cli', 'x');
INSERT INTO review_draft_grants (draft_id, runs, granted_at)
VALUES ((SELECT min(id) FROM review_drafts), 1, 'x');
