-- sha256 of 0013_proposal_seconds.sql: 97136ea89da679897cf68e9fd4a23f79acca37569bb595e120f3dcac901555a9

INSERT INTO proposal_seconds (memory_id, ticket_key, run_id)
VALUES ((SELECT min(id) FROM memories), (SELECT min(key) FROM tickets), (SELECT min(id) FROM runs));
