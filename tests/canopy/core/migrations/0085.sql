-- sha256 of 0085_observed_review_commit.sql: 2ac59148ab8caef8004691a93f7b275090c71342c67ddcf2c34a9d7273485a03

UPDATE observed_reviews SET commit_sha = 'abc1234' WHERE id = (SELECT min(id) FROM observed_reviews);
