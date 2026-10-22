-- sha256 of 0076_feedback_plan_snapshots.sql: 21f6341faef114b2f60665915d9c3ae136c32d7509b67ae1627e0b369e7fdc02

INSERT INTO feedback_plan_prs (plan_id, pr_url, head_sha) VALUES (1, 'https://github.com/acme/api/pull/7', 'abc1234');
INSERT INTO feedback_plan_checks (plan_id, pr_url, name, conclusion)
VALUES (1, 'https://github.com/acme/api/pull/7', 'test', 'failure');
INSERT INTO feedback_plan_seen (plan_id, pr_url, item, item_id, thread_id, author, body_sha256, answers)
VALUES (1, 'https://github.com/acme/api/pull/7', 'comment', 502, 'PRRT_1', 'bob', 'b', 501);
INSERT INTO feedback_plan_moves (plan_id, pr_url, kind, name, value, seen_at)
VALUES (1, 'https://github.com/acme/api/pull/7', 'head', '', 'def5678', 'x');
