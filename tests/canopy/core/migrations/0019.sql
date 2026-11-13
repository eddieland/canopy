-- sha256 of 0019_pr_comments.sql: 202491b8ee8699a2ee3c8d5a975289b40b7e66aca9a9826007a9b53eeabc9daa

-- Rebuilds five tables and creates none; a comment on a PR's conversation, numbered, shows the new kind is taken.
INSERT INTO observed_reviews (pr_url, item, id, author, bot, created_at, body, observed_at, number)
VALUES ('https://github.com/acme/api/pull/7', 'pr_comment', 9101, 'carol', 0, '2026-11-13T10:00:00Z',
    'Does this cover the retry path?', '2026-11-13T10:01:00Z', NULL);
INSERT INTO item_numbers (kind, subject, id, numbered_at)
VALUES ('pr_comment', 'https://github.com/acme/api/pull/7', '9101', '2026-11-13T10:01:00Z');
