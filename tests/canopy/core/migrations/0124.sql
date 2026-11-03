-- sha256 of 0124_initiatives.sql: d7123dd811d563e7664a325993c6f493ea2d7eb4fa5c71f523cc83e7077f4045

INSERT INTO initiatives (id, text, project, epic, channel, submitted_at)
VALUES (1, 'Move sessions to the new store', 'PROJ', 'PROJ-1', 'cli', 'x');
INSERT INTO initiative_repos (initiative_id, repo) VALUES (1, 'api');
INSERT INTO initiative_members (initiative_id, ticket_key, added_at, added_channel, removed_at, removed_channel)
VALUES (1, 'PROJ-2', 'x', 'cli', NULL, NULL);
