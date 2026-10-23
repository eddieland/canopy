-- sha256 of 0083_artifact_comments.sql: 63e94a79f34d186f5a0f99331e31df562cc75070ce2dee4344dcf8562e36e3fa

INSERT INTO connector_runs (tick_id, source, kind, started_at, ended_at, status, request, recorded, refused, stderr)
VALUES (NULL, 'artifacts', 'artifacts', 'x', 'x', 'ok', '{"since": 0}', '{"comment_created": 1}', '{}', '');
INSERT INTO observed_feeds (source, through, read_at) VALUES ('artifacts', 3, 'x');
INSERT INTO observed_artifact_threads (
    id, artifact_id, origin, ticket, exact, prefix, suffix, anchored_version, state, anchor_status, seq, observed_at
)
VALUES (
    'thread_1', 'art_1', '{"canopy.ticket": "OLD-1"}', 'OLD-1', 'shard it', 'should ', '.', 1, 'open', 'found', 3, 'x'
);
INSERT INTO observed_artifact_comments (
    id, thread_id, author, author_name, author_kind, on_behalf_of, via, body, truncated, marked, created_at, edited_at,
    deleted_at, seq, observed_at
)
VALUES ('comment_1', 'thread_1', 'u_ana', 'Ana', 'person', NULL, 'web', 'Why?', 0, 0, 'x', NULL, NULL, 3, 'x');
