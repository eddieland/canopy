-- sha256 of 0003_conversations.sql: 2c6304b3bbd58ae42d99a556d89ce45f92a918a5928938eae6f0e03d4d82d077

INSERT INTO messages (subject_kind, subject_id, at, source, kind, channel, body)
VALUES ('ticket', 'OLD-1', 'x', 'operator', 'reply', 'cli', 'Blue.');
INSERT INTO starts (subject_kind, subject_id, status, started_at, channel)
VALUES ('ticket', 'OLD-1', 'started', 'x', 'cli');
