-- sha256 of 0053_feedback_plans.sql: ab5dc7c342afc374f95ca4542904a0fe1efec20ce26c9e6514521a8abe0babf9

INSERT INTO feedback_plans (ticket_key, run_id, created_at, status, sha256, size, approved_sha256, approved_at,
    approved_channel, spent_run_id)
VALUES ('OLD-1', 1, 'x', 'approved', 'a', 9, 'a', 'y', 'cli', 1);
INSERT INTO feedback_plan_items (plan_id, number, pr_url, item, item_id, proposal, reply)
VALUES (1, 1, 'https://github.com/acme/api/pull/7', 'comment', 501, 'change', 'Renamed.');
