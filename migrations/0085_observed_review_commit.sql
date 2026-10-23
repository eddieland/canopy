-- The commit a review was given on, as canopy's reader last read it (DESIGN §7, §30), so an approval counts only at
-- the PR's head: a push after it, the loop's own included, needs approving again. NULL on a review comment, on a review
-- read before canopy read commits, and on one GitHub no longer ties to a commit, such as after a force push.
ALTER TABLE observed_reviews ADD COLUMN commit_sha TEXT;
