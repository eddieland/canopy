-- sha256 of 0021_ignored_comments.sql: f5557109830179ed303b723e1e6f253ef81cb24774954a46f3ed1cfc981738b6

-- Creates no table; an ignored comment on a PR's conversation, with no number, shows the new column is taken.
INSERT INTO observed_reviews (pr_url, item, id, author, bot, created_at, body, observed_at, number, ignored)
VALUES ('https://github.com/acme/api/pull/7', 'pr_comment', 9102, 'carol', 0, '2026-11-17T10:00:00Z',
    'I looked at this', '2026-11-17T10:01:00Z', NULL, 1);
