-- sha256 of 0080_observed_check_runs.sql: 7fee17ebd4afb195c7d2d0cb6c2363858b3fa8f0142bb50197dec3030468d425

INSERT INTO observed_check_runs (pr_url, run_id, name, head_sha, conclusion, observed_at)
VALUES ('https://e.test/pr/7', 10, 'build', 'abc1234', 'failure', 'x');
