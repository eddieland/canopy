-- sha256 of 0062_run_offers.sql: 8e45e47f0e3755a9dabd92407c1d7969f295cc2aa5d87f46bae2f47d8950ff29

INSERT INTO run_offers (run_table, run_id, agent, error, asked_at) VALUES ('runs', 1, 'canopy-worker', NULL, 'x');
INSERT INTO run_offered_servers (run_table, run_id, server, reach) VALUES ('runs', 1, 'github', 'some');
INSERT INTO run_offered_skills (run_table, run_id, skill) VALUES ('runs', 1, 'pdf');
