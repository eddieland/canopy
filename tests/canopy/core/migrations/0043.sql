-- sha256 of 0043_review_replies.sql: 1b033e3cb09d87e6efa91a4e725ccd860b5dc675a1671c57d2ddd3ddba7977ad

INSERT INTO observed_prs (url, repository, number, head_sha, base_ref, state, draft, mergeable, author, observed_at)
VALUES ('https://e.test/pr/7', 'acme/api', 7, 'abc1234', 'main', 'open', 0, 'mergeable', 'me', 'x');
INSERT INTO observed_reviews (pr_url, item, id, author, bot, state, created_at, body, url, observed_at)
VALUES ('https://e.test/pr/7', 'review', 101, 'alice', 0, 'commented', 'x', 'A few things.', 'https://e.test/r', 'x');
INSERT INTO drafts (run_id, number, ticket_key, kind, repo, pr_url, comment_id, stance, status, basis, created_at)
VALUES (1, 1, 'OLD-1', 'thread', 'api', 'https://e.test/pr/7', 501, 'changed', 'unchecked', 'x', 'x');
INSERT INTO draft_versions (draft_id, version, body, author, created_at) VALUES (1, 1, 'Renamed.', 'worker', 'x');
INSERT INTO run_replies (run_id, mode, ticket_drafts) VALUES (1, 'approve', 0);
