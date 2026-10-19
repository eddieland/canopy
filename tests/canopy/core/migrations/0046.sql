-- sha256 of 0046_plan_triage.sql: 0d9f5ae2e94fac3be36fffe58cf2460d4ff1d9fdb839224db98402828755ef9e

INSERT INTO run_reads (run_id, repo) VALUES (1, 'repo');
INSERT INTO plan_waivers (ticket_key, run_id, reason, at) VALUES ('OLD-1', 1, 'A typo in a comment.', 'x');
