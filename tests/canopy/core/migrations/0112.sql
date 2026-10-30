-- sha256 of 0112_checklist_answers.sql: 8bc01de1796abc343f0482c4d199c0698819c159531791e9753e67c85a728cac

INSERT INTO checklist_answers (run_id, repo, item, answer, reason)
VALUES ((SELECT min(id) FROM runs), 'repo', 'general-types', 'held', 'The function stores the list it is given.');
