-- sha256 of 0037_memory.sql: 3c0ed312175a51a89e4ea452d2c725eafc521fae3582d73ad7462cccd83930cd

INSERT INTO memories (scope, ticket_key, key, body, status, author, run_id, tick_id, head, created_at)
VALUES ('ticket', 'OLD-1', 'ci-flake', 'The lint job fails on a cold cache.', 'active', 'worker', 1, 1, 'abc1234', 'x');
INSERT INTO run_memory (run_id, ticket_notes, proposals) VALUES (1, 'use', 'off');
INSERT INTO memory_reads (run_id, memory_id) VALUES (1, 1);
