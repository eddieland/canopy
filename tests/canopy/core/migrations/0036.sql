-- sha256 of 0036_plan_threads.sql: bd963d5fa78e9ce18716c7c9c9094773283f68d172fc9ae89cea4d88e2d85da7

INSERT INTO plan_threads (ticket_key, quote, prefix, suffix, body, created_at, resolved_at)
VALUES ('OLD-1', 'the route', 'Add ', ' to it', 'Why here?', 'x', NULL);
INSERT INTO plan_replies (thread_id, body, created_at) VALUES (1, 'Because.', 'y');
