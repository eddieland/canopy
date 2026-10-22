-- sha256 of 0073_task_conversation.sql: b722b1b8428f19a0d83fd26bf72ea840f44f4f23107b52292036b5663dc01eb4

INSERT INTO messages (subject_kind, subject_id, at, source, kind, channel, task_run_id, body)
VALUES ('task', '1', 'x', 'worker', 'report', 'run', (SELECT min(id) FROM task_runs), 'found it');
UPDATE task_runs SET message_id = (SELECT max(id) FROM messages) WHERE id = (SELECT min(id) FROM task_runs);
