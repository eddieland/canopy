-- sha256 of 0001_init.sql: 29a6d9dc889e6665b59c3275c33cef6b110c91e5e91012bbeb54128ee247dfcc

INSERT INTO ticks (id, started_at, ended_at, status) VALUES (1, 'x', 'y', 'ok');
INSERT INTO tickets (key, repo, first_seen_at, last_seen_at, phase) VALUES ('OLD-1', '/r', 'x', 'y', 'ci_red');
INSERT INTO runs (id, tick_id, ticket_key, kind, branch, started_at, ended_at, log_path, status, result_json)
VALUES (1, 1, 'OLD-1', 'implement', 'agent/OLD-1-a', 'x', 'y', 'l', 'done', '{"summary": "did it"}');
INSERT INTO decisions (tick_id, ticket_key, action, rationale) VALUES (1, 'OLD-1', 'wait', 'r');
INSERT INTO notifications (sink, fingerprint, ticket_key, reason, sent_at) VALUES ('log', 'f', 'OLD-1', 'r', 'x');
INSERT INTO ticket_units (ticket_key, repo, branch, phase) VALUES ('OLD-1', 'api', 'b', 'ci_red');
INSERT INTO run_slots (run_id, repo, slot_path, lease_id, lease_holder) VALUES (1, 'api', '/s', 'l', 'h');
INSERT INTO split_children (child_key, parent_key, repo, run_id) VALUES ('OLD-2', 'OLD-1', 'api', 1);
INSERT INTO chore_runs (tick_id, chore, started_at, status, log_path) VALUES (1, 'nightly', 'x', 'ok', 'l');
INSERT INTO notify_events (grp, kind, at, fields) VALUES ('runs', 'run.ended', 'x', '{}');
INSERT INTO notify_sinks (name, cursor, created_at) VALUES ('log', 1, 'x');
INSERT INTO review_runs (tick_id, pr_url, sha, started_at, status, log_path)
VALUES (1, 'https://e.test/pr/7', 'abc', 'x', 'done', 'l');
