-- sha256 of 0082_observed_pr_title.sql: 60077f3b14db74bf3f96e928820bca53188d76c07094256a7bebe7bc845dbc42

UPDATE observed_prs SET title = 'Retry the upstream on a 503' WHERE url = (SELECT min(url) FROM observed_prs);
