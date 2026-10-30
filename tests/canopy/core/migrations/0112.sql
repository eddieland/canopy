-- sha256 of 0112_checklist_answers.sql: c1200b5dcab9c8cbabb566488ac721585adedbdf041732306605909a2c8690dc

INSERT INTO checklist_answers (run_id, repo, item, answer, reason)
VALUES ((SELECT min(id) FROM runs), 'repo', 'general-types', 'held', 'The callers pass a list.');
