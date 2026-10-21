-- sha256 of 0057_review_drafts.sql: fde8c7bc8622a4262f5fd70da6b6cb64defd54479ae5eac855ce78741de4ee27

INSERT INTO review_drafts (review_run_id, pr_url, sha, status, created_at)
VALUES (1, 'https://e.test/pr/8', 'abc1234', 'waiting', 'x');
INSERT INTO review_draft_versions (draft_id, version, body, comments, author, change, created_at)
VALUES (1, 1, 'One defect.', '[{"path": "a.py", "line": 2, "text": "Wrong.", "finding": 1}]', 'reviewer', 'made', 'x');
