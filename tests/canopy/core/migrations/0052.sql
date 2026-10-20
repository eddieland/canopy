-- sha256 of 0052_connectors.sql: 29df3f6e3a6df6f8d0242ac3542065352307ff2f3a2aa173cb87e199d518e346

INSERT INTO observed_tickets (key, title, body, state, labels, updated_at, blockers, observed_at)
VALUES ('OLD-1', 'Fix the build', 'It fails.', 'open', '[{"name": "agent", "added_at": null}]', 'x', '[]', 'x');
INSERT INTO observed_comments (ticket, id, author, commented_at, body, truncated, source, observed_at)
VALUES ('OLD-1', '10001', 'acc-1', 'x', 'Looks good.', 0, 'tracker', 'x');
INSERT INTO observed_branches (repository, name, head_sha, observed_at) VALUES ('api', 'agent/old-1', 'abc1234', 'x');
INSERT INTO observed_checks (pr_url, name, head_sha, status, conclusion, run_id, url, observed_at)
VALUES ('https://e.test/pr/7', 'build', 'abc1234', 'completed', 'success', 11, 'https://e.test/c/11', 'x');
INSERT INTO connector_runs (tick_id, source, kind, started_at, ended_at, status, request, recorded, refused, stderr)
VALUES (1, 'github', 'vcs', 'x', 'x', 'ok', '{"prs": []}', '{}', '{}', '');
