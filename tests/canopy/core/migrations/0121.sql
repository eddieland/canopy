-- sha256 of 0121_observed_status_runs.sql: e1fbaf28d422da3d3a2389f39667f94bf0f3c4627f9bb07abf0184851468ef51

INSERT INTO observed_status_runs (pr_url, name, head_sha, conclusion, observed_at)
VALUES ('https://e.test/pr/7', 'jenkins', 'abc1234', 'failure', 'x');
