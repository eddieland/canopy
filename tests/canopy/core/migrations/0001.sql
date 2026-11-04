-- sha256 of 0001_init.sql: dfee70599bb47a9d6509a277e3ac1cddd29be8ffd6986f49f16beaf50b72f1b2

INSERT INTO ticks (id, started_at, ended_at, status) VALUES (1, 'x', 'y', 'ok');
INSERT INTO tickets (key, repo, first_seen_at, last_seen_at, phase) VALUES ('OLD-1', '/r', 'x', 'y', 'ci_red');
INSERT INTO runs (id, tick_id, ticket_key, kind, branch, started_at, ended_at, log_path, status, result_json)
VALUES (1, 1, 'OLD-1', 'implement', 'agent/OLD-1-a', 'x', 'y', 'l', 'done', '{"summary": "did it"}');
INSERT INTO decisions (tick_id, ticket_key, action, rationale) VALUES (1, 'OLD-1', 'wait', 'r');
INSERT INTO notifications (sink, fingerprint, ticket_key, reason, sent_at) VALUES ('log', 'f', 'OLD-1', 'r', 'x');
INSERT INTO ticket_units (ticket_key, repo, branch, phase) VALUES ('OLD-1', 'api', 'b', 'ci_red');
INSERT INTO run_slots (run_id, repo, slot_path, lease_id, lease_holder) VALUES (1, 'api', '/s', 'l', 'h');
INSERT INTO split_children (child_key, parent_key, repo, run_id) VALUES ('OLD-2', 'OLD-1', 'api', 1);
INSERT INTO chore_runs (tick_id, chore, started_at, status, log_path) VALUES (1, 'nightly', 'x', 'ok', 'l');
INSERT INTO notify_events (grp, kind, at, fields) VALUES ('runs', 'run.ended', 'x', '{}');
INSERT INTO notify_sinks (name, cursor, created_at) VALUES ('log', 1, 'x');
INSERT INTO review_runs (tick_id, pr_url, sha, started_at, status, log_path)
VALUES (1, 'https://e.test/pr/7', 'abc', 'x', 'done', 'l');
INSERT INTO messages (subject_kind, subject_id, at, source, kind, channel, body)
VALUES ('ticket', 'OLD-1', 'x', 'operator', 'reply', 'cli', 'Blue.');
INSERT INTO starts (subject_kind, subject_id, status, started_at, channel)
VALUES ('ticket', 'OLD-1', 'started', 'x', 'cli');
INSERT INTO pause (id, paused_at, channel) VALUES (1, 'x', 'cli');
INSERT INTO attempt_grants (ticket_key, repo, kind, runs, granted_at) VALUES ('OLD-1', 'api', 'resume', 1, 'x');
INSERT INTO finding_dismissals (chore, finding_id, dismissed_at, channel) VALUES ('nightly', 'f/1', 'x', 'cli');
INSERT INTO review_dismissals (review_run_id, finding, dismissed_at, channel) VALUES (1, 1, 'x', 'cli');
INSERT INTO review_grants (pr_url, runs, granted_at) VALUES ('https://e.test/pr/7', 1, 'x');
INSERT INTO notices (body, set_at, channel, lapses_at, ended_at, ended_channel)
VALUES ('CI is down.', 'x', 'cli', 'y', 'z', 'web');
INSERT INTO review_requests (pr_url, created_at, channel) VALUES ('https://e.test/pr/7', 'x', 'cli');
INSERT INTO slots (repo, name, path) VALUES ('api', '1', '/w/pools/api/1/api');
INSERT INTO run_tools (run_table, run_id, tool, calls, errors, result_chars) VALUES ('runs', 1, 'bash', 2, 0, 9);
INSERT INTO plans (ticket_key, run_id, created_at, status, sha256, size, approved_sha256, approved_at, approved_channel)
VALUES ('OLD-1', 1, 'x', 'approved', 'a', 9, 'b', 'y', 'cli');
INSERT INTO ticket_grants (ticket_key, kind, runs, granted_at) VALUES ('OLD-1', 'plan', 1, 'x');
INSERT INTO plan_threads (ticket_key, quote, prefix, suffix, body, created_at, resolved_at)
VALUES ('OLD-1', 'the route', 'Add ', ' to it', 'Why here?', 'x', NULL);
INSERT INTO plan_replies (thread_id, body, created_at) VALUES (1, 'Because.', 'y');
INSERT INTO memories (scope, ticket_key, key, body, status, author, run_id, tick_id, head, created_at)
VALUES ('ticket', 'OLD-1', 'ci-flake', 'The lint job fails on a cold cache.', 'active', 'worker', 1, 1, 'abc1234', 'x');
INSERT INTO run_memory (run_id, ticket_notes, proposals) VALUES (1, 'use', 'off');
INSERT INTO memory_reads (run_id, memory_id) VALUES (1, 1);
INSERT INTO pr_titles (pr_url, title, updated_at) VALUES ('https://e.test/pr/7', 'Fix it', 'x');
INSERT INTO run_reasons (run_id, reason) VALUES (1, 'ci');
INSERT INTO observed_prs (url, repository, number, head_sha, base_ref, state, draft, mergeable, author, observed_at)
VALUES ('https://e.test/pr/7', 'acme/api', 7, 'abc1234', 'main', 'open', 0, 'mergeable', 'me', 'x');
INSERT INTO observed_reviews (pr_url, item, id, author, bot, state, created_at, body, url, observed_at)
VALUES ('https://e.test/pr/7', 'review', 101, 'alice', 0, 'commented', 'x', 'A few things.', 'https://e.test/r', 'x');
INSERT INTO drafts (run_id, number, ticket_key, kind, repo, pr_url, comment_id, stance, status, basis, created_at)
VALUES (1, 1, 'OLD-1', 'thread', 'api', 'https://e.test/pr/7', 501, 'changed', 'unchecked', 'x', 'x');
INSERT INTO draft_versions (draft_id, version, body, author, created_at) VALUES (1, 1, 'Renamed.', 'worker', 'x');
INSERT INTO run_replies (run_id, mode, ticket_drafts) VALUES (1, 'approve', 0);
INSERT INTO forgets (ticket_key, at, channel, run_id, message_id, branch, prs)
VALUES ('OLD-1', 'x', 'web', 1, 1, 'agent/OLD-1-work', '["https://e.test/pr/7"]');
INSERT INTO run_reads (run_id, repo) VALUES (1, 'repo');
INSERT INTO plan_waivers (ticket_key, run_id, reason, at) VALUES ('OLD-1', 1, 'A typo in a comment.', 'x');
INSERT INTO follow_ups (key, parent_key, run_id, repo, at) VALUES ('OLD-3', 'OLD-1', 1, 'api', 'x');
INSERT INTO observed_tickets (key, title, body, state, labels, updated_at, blockers, observed_at)
VALUES ('OLD-1', 'Fix the build', 'It fails.', 'open', '[{"name": "agent", "added_at": null}]', 'x', '[]', 'x');
INSERT INTO observed_comments (ticket, id, author, commented_at, body, truncated, source, observed_at)
VALUES ('OLD-1', '10001', 'acc-1', 'x', 'Looks good.', 0, 'tracker', 'x');
INSERT INTO observed_branches (repository, name, head_sha, observed_at) VALUES ('api', 'agent/old-1', 'abc1234', 'x');
INSERT INTO observed_checks (pr_url, name, head_sha, status, conclusion, run_id, url, observed_at)
VALUES ('https://e.test/pr/7', 'build', 'abc1234', 'completed', 'success', 11, 'https://e.test/c/11', 'x');
INSERT INTO connector_runs (tick_id, source, kind, started_at, ended_at, status, request, recorded, refused, stderr)
VALUES (1, 'github', 'vcs', 'x', 'x', 'ok', '{"prs": []}', '{}', '{}', '');
INSERT INTO feedback_plans (ticket_key, run_id, created_at, status, sha256, size, approved_sha256, approved_at,
    approved_channel, spent_run_id)
VALUES ('OLD-1', 1, 'x', 'approved', 'a', 9, 'a', 'y', 'cli', 1);
INSERT INTO feedback_plan_items (plan_id, number, pr_url, item, item_id, proposal, reply)
VALUES (1, 1, 'https://github.com/acme/api/pull/7', 'comment', 501, 'change', 'Renamed.');
INSERT INTO run_model_reads (run_table, run_id, status, error, attempts, read_at)
VALUES ('runs', 1, 'found', NULL, 1, 'x');
INSERT INTO run_models (run_table, run_id, model, replies, cost_usd) VALUES ('runs', 1, 'anthropic/claude-x', 4, 0.5);
INSERT INTO seen (kind, subject, at, channel) VALUES ('review', '2', 'x', 'web');
INSERT INTO web_writes (at, method, path, code, client, session)
VALUES ('x', 'POST', '/api/tickets/OLD-1/stop', 200, '127.0.0.1', 'f');
INSERT INTO derivations (tick_id, ticket_key, repo, candidate, closed, phases, stale, overseer_phase)
VALUES (1, 'OLD-1', NULL, 1, 0, '["ready"]', NULL, 'ready');
INSERT INTO review_drafts (review_run_id, pr_url, sha, status, created_at)
VALUES (1, 'https://e.test/pr/8', 'abc1234', 'waiting', 'x');
INSERT INTO review_draft_versions (draft_id, version, body, comments, author, change, created_at)
VALUES (1, 1, 'One defect.', '[{"path": "a.py", "line": 2, "text": "Wrong.", "finding": 1}]', 'reviewer', 'made', 'x');
INSERT INTO run_offers (run_table, run_id, agent, error, asked_at) VALUES ('runs', 1, 'canopy-worker', NULL, 'x');
INSERT INTO run_offered_servers (run_table, run_id, server, reach) VALUES ('runs', 1, 'github', 'some');
INSERT INTO run_offered_skills (run_table, run_id, skill) VALUES ('runs', 1, 'pdf');
INSERT INTO run_offered_tools (run_table, run_id, tool) VALUES ('runs', 1, 'bash');
INSERT INTO run_offered_server_rules (run_table, run_id, server, position, rule)
VALUES ('runs', 1, 'github', 0, 'offer github_issue_read');
INSERT INTO ticket_overrides (ticket_key, agent, kind, value, channel, set_at)
VALUES ('PROJ-1', 'reviewer', 'persona', 'skeptic', 'cli', 'x');
INSERT INTO review_request_personas (request_id, persona)
VALUES ((SELECT min(id) FROM review_requests), 'skeptic');
INSERT INTO next_run_personas (ticket_key, agent, persona, channel, set_at)
VALUES ('PROJ-1', 'worker', 'minimalist', 'cli', 'x');
INSERT INTO persona_texts (digest, text, recorded_at)
VALUES ('c4a0f1e2d3b4a5968778695a4b3c2d1e0f1a2b3c4d5e6f708192a3b4c5d6e7f8', 'Reply briefly.', 'x');
INSERT INTO tasks (text, repo, project, channel, submitted_at)
VALUES ('Find out why the build is slow.', 'repo', 'PROJ', 'cli', 'x');
INSERT INTO task_runs (
    task_id, tick_id, branch, repo, slot_path, lease_id, lease_holder, base_branch, pool, started_at, status, log_path
)
VALUES (
    (SELECT min(id) FROM tasks), (SELECT min(id) FROM ticks), 'agent/task/1', 'repo', '/pool/1/repo', 'l1',
    'canopy:task:1', 'main', 'treehouse', 'x', 'done', 'l'
);
INSERT INTO run_model_reads (run_table, run_id, status, error, attempts, read_at)
VALUES ('task_runs', 1, 'found', NULL, 1, 'x');
INSERT INTO run_models (run_table, run_id, model, replies, cost_usd)
VALUES ('task_runs', 1, 'anthropic/claude-x', 2, 0.25);
INSERT INTO gc_passes (
    tick_id, started_at, ended_at, status, run_files_days, tick_files_days, run_cutoff, tick_cutoff, removed, failures,
    error
)
VALUES (1, 'x', 'x', 'ok', 30, 7, 'w', 'w', '{"run files": {"files": 2, "bytes": 110}}', 0, NULL);
INSERT INTO run_tools (run_table, run_id, tool, calls, errors, result_chars)
VALUES ('task_runs', 1, 'bash', 2, 0, 120);
INSERT INTO messages (subject_kind, subject_id, at, source, kind, channel, task_run_id, body)
VALUES ('task', '1', 'x', 'worker', 'report', 'run', (SELECT min(id) FROM task_runs), 'found it');
UPDATE task_runs SET message_id = (SELECT max(id) FROM messages) WHERE id = (SELECT min(id) FROM task_runs);
INSERT INTO review_draft_notes (draft_id, after_version, body, channel, created_at)
VALUES ((SELECT min(id) FROM review_drafts), 1, 'Say it more gently.', 'cli', 'x');
INSERT INTO review_draft_grants (draft_id, runs, granted_at)
VALUES ((SELECT min(id) FROM review_drafts), 1, 'x');
UPDATE task_runs SET report_sha256 = 'abc' WHERE id = (SELECT min(id) FROM task_runs);
INSERT INTO task_tickets (task_id, task_run_id, key, at)
VALUES ((SELECT min(id) FROM tasks), (SELECT min(id) FROM task_runs), 'PROJ-9', 'x');
INSERT INTO feedback_plan_prs (plan_id, pr_url, head_sha) VALUES (1, 'https://github.com/acme/api/pull/7', 'abc1234');
INSERT INTO feedback_plan_checks (plan_id, pr_url, name, conclusion)
VALUES (1, 'https://github.com/acme/api/pull/7', 'test', 'failure');
INSERT INTO feedback_plan_seen (plan_id, pr_url, item, item_id, thread_id, author, body_sha256, answers)
VALUES (1, 'https://github.com/acme/api/pull/7', 'comment', 502, 'PRRT_1', 'bob', 'b', 501);
INSERT INTO feedback_plan_moves (plan_id, pr_url, kind, name, value, seen_at)
VALUES (1, 'https://github.com/acme/api/pull/7', 'head', '', 'def5678', 'x');
INSERT INTO decisions (tick_id, ticket_key, action, rationale, decider) VALUES (1, 'OLD-1', 'wait', 'r', 'harness');
INSERT INTO memories (scope, key, body, status, author, created_at, approved_at, pinned_at)
VALUES ('lesson', 'tests-need-docker', 'Start Docker before the tests.', 'active', 'operator', 'x', 'x', 'x');
UPDATE runs SET model = 'acme/fake-model' WHERE id = (SELECT min(id) FROM runs);
UPDATE observed_prs SET title = 'Retry the upstream on a 503' WHERE url = (SELECT min(url) FROM observed_prs);
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
INSERT INTO attachments (subject_kind, subject_id, name, size, sha256, channel, added_at, removed_at, removed_channel)
VALUES ('task', '1', 'design.md', 12, 'aa', 'cli', 'x', 'x', 'web');
UPDATE review_dismissals SET reason = 'wrong';
INSERT INTO connector_runs (tick_id, source, kind, started_at, ended_at, status, request, recorded, refused, stderr)
VALUES (NULL, 'slack', 'slack', 'x', 'x', 'ok', '{"repo": "/r/api"}', '{"reply": 1}', '{}', '');
INSERT INTO review_answers (run_id, review_run_id, finding, answer, reason)
VALUES ((SELECT min(id) FROM runs), (SELECT min(id) FROM review_runs), 1, 'declined', 'The retry is bounded.');
INSERT INTO review_holds (review_run_id, finding, kind, rebuts_run_id, rebuts_finding, held_at)
VALUES ((SELECT max(id) FROM review_runs), 1, 'rebuttal', (SELECT min(id) FROM review_runs), 1, 'x');
INSERT INTO run_reply_models (run_table, run_id, message, model)
VALUES ('runs', 1, 'msg_1', 'anthropic/claude-x');
INSERT INTO review_heads (pr_url, sha, seen_at) VALUES ('https://e.test/pr/7', 'abc', 'x');
UPDATE ticks SET overseer_ran = 0 WHERE id = (SELECT min(id) FROM ticks);
INSERT INTO observed_check_runs (pr_url, run_id, name, head_sha, conclusion, observed_at)
VALUES ('https://e.test/pr/7', 10, 'build', 'abc1234', 'failure', 'x');
INSERT INTO feedback_plan_items (plan_id, number, pr_url, item, item_id, proposal, reply, left_out)
VALUES (1, 2, 'https://github.com/acme/api/pull/7', 'check', -281474976710656, 'change', NULL, 1);
INSERT INTO review_holds (review_run_id, finding, kind, held_at)
VALUES ((SELECT max(id) FROM review_runs), 2, 'late', 'x');
INSERT INTO runtime_sessions (
    session_id, parent_id, directory, started_at, updated_at, updated_ms, cost_usd, tokens_input, tokens_output,
    tokens_reasoning, tokens_cache_read, tokens_cache_write, read_at
) VALUES ('ses_1', NULL, '/work/api', 'x', 'x', 1, 0.5, 1, 2, 3, 4, 5, 'x');
INSERT INTO runtime_session_models (session_id, model, replies, cost_usd)
VALUES ('ses_1', 'anthropic/claude-x', 2, 0.5);
INSERT INTO runtime_session_reads (id, cursor_updated_ms, cursor_session_id, status, error, skipped, read_at)
VALUES (1, 1, 'ses_1', 'found', NULL, 0, 'x');
INSERT INTO feedback_plan_items (plan_id, number, pr_url, item, item_id, proposal, reply, left_out)
VALUES (1, 3, 'https://github.com/acme/api/pull/7', 'blocker', -140737488355328, 'change', NULL, 0);
INSERT INTO item_numbers (kind, subject, id, numbered_at) VALUES ('comment', 'PROJ-1', '10001', 'x');
INSERT INTO recorded_runs (
    id, tick_id, kind, request, ticket_key, pr_url, persona, chore, status, run_id, recorded_at, closed_at
) VALUES (1, 1, 'dispatch', '{}', 'PROJ-1', NULL, NULL, NULL, 'started', 1, 'x', 'y');
INSERT INTO review_dismissals (review_run_id, finding, dismissed_at, channel, reason)
VALUES (1, 2, 'x', 'web', 'out_of_scope');
INSERT INTO flaky_kicks (run_id, repo, branch, from_head, to_head, kicked_at)
VALUES (1, 'repo', 'agent/PROJ-1-work', 'a1', 'b2', 'x');
INSERT INTO decisions (tick_id, ticket_key, action, rationale, kept, item)
VALUES (1, 'OLD-1', 'attention:needs_author', 'r', 1, 1);
INSERT INTO checklist_answers (run_id, repo, item, answer, reason)
VALUES ((SELECT min(id) FROM runs), 'repo', 'general-types', 'held', 'The function stores the list it is given.');
INSERT INTO overseer_runs (tick_id, subject, started_at, ended_at, status, failure, session_id, cost_usd)
VALUES ((SELECT min(id) FROM ticks), NULL, 'x', 'y', 'failed', 'overseer exited 1', 'ses_o1', 0.25);
UPDATE observed_prs SET created_at = '2026-10-17T09:00:00.000Z', ready_at = '2026-10-17T09:00:00.000Z',
    review_requested_at = '2026-10-17T10:00:00.000Z', merged_at = '2026-10-19T15:00:00.000Z',
    closed_at = '2026-10-19T15:00:00.000Z'
WHERE url = (SELECT min(url) FROM observed_prs);
INSERT INTO checklist_answers (repo, item, answer, reason, task_run_id)
VALUES ('repo', 'newspaper', 'fixed', NULL, (SELECT min(id) FROM task_runs));
INSERT INTO plan_metrics (plan_id, version, measured_at, problem, words, lines, code_blocks, tables, diagrams)
VALUES ((SELECT min(id) FROM plans), 1, 'x', NULL, 120, 14, 1, 0, 0);
INSERT INTO passed_reviews (pr_url, item, id, number, ticket_key, repo, tick_id, reason, decider, passed_at)
VALUES ('https://e.test/pr/7', 'comment', 501, 12, 'OLD-1', 'api', 1, 'optional', 'overseer', 'x');
INSERT INTO observed_status_runs (pr_url, name, head_sha, conclusion, observed_at)
VALUES ('https://e.test/pr/7', 'jenkins', 'abc1234', 'failure', 'x');
INSERT INTO epics (id, text, project, tracker_epic, channel, submitted_at)
VALUES (1, 'Move sessions to the new store', 'PROJ', 'PROJ-1', 'cli', 'x');
INSERT INTO epic_repos (epic_id, repo) VALUES (1, 'api');
INSERT INTO epic_members (epic_id, ticket_key, added_at, added_channel, removed_at, removed_channel)
VALUES (1, 'PROJ-2', 'x', 'cli', NULL, NULL);
INSERT INTO epic_runs (id, epic_id, tick_id, desk_path, started_at, status, log_path)
VALUES (1, 1, 1, '/w/desks/init-1', 'x', 'done', '/s/epic-runs/1.log');
INSERT INTO epic_run_slots (run_id, repo, slot_path, lease_id, lease_holder, base_branch, pool)
VALUES (1, 'api', '/w/slots/api-1', 'l1', 'canopy:epic:1', 'main', 'canopy');
INSERT INTO run_model_reads (run_table, run_id, status, error, attempts, read_at, runtime_version)
VALUES ('epic_runs', 1, 'found', NULL, 1, 'x', NULL);
INSERT INTO run_models (run_table, run_id, model, replies, cost_usd)
VALUES ('epic_runs', 1, 'anthropic/claude-x', 2, 0.25);
INSERT INTO run_tools (run_table, run_id, tool, calls, errors, result_chars)
VALUES ('epic_runs', 1, 'read', 2, 0, 120);
INSERT INTO run_reply_models (run_table, run_id, message, model)
VALUES ('epic_runs', 1, 'msg_1', 'anthropic/claude-x');
INSERT INTO epic_plans (epic_id, run_id, created_at, status, sha256, size)
VALUES (1, 1, 'x', 'proposed', 'abc', 120);
INSERT INTO epic_member_entries (member_id, entry) VALUES (1, 'B1');
