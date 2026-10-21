-- sha256 of 0063_run_offered_tools.sql: 75bf7db3609c3b0169a0cfd279bb19d49416ded397ddb975f05c972b399f4f03

INSERT INTO run_offered_tools (run_table, run_id, tool) VALUES ('runs', 1, 'bash');
INSERT INTO run_offered_server_rules (run_table, run_id, server, position, rule)
VALUES ('runs', 1, 'github', 0, 'offer github_issue_read');
