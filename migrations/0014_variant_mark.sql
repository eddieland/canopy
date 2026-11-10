-- The models that served a run or a session, named as canopy's config spells a model run at a variant,
-- `provider/model@variant` (DESIGN §13, Each agent's model). canopy recorded OpenCode 2's as its sessions spell them,
-- `provider/model#variant`, so one variant counted as two models, by the runtime that ran it. A name with one `#`,
-- after its provider, takes `@` for it. A run or session that would then name one model twice, which canopy never
-- recorded, keeps one row of it, its replies and cost summed.
INSERT INTO run_models (run_table, run_id, model, replies, cost_usd)
SELECT run_table, run_id, replace(model, '#', '@'), sum(replies), sum(cost_usd)
FROM run_models
WHERE model GLOB '*/*#*' AND model NOT GLOB '*#*#*'
GROUP BY run_table, run_id, replace(model, '#', '@')
ON CONFLICT (run_table, run_id, model) DO UPDATE SET
    replies = replies + excluded.replies,
    cost_usd = cost_usd + excluded.cost_usd;

DELETE FROM run_models WHERE model GLOB '*/*#*' AND model NOT GLOB '*#*#*';

INSERT INTO runtime_session_models (session_id, model, replies, cost_usd)
SELECT session_id, replace(model, '#', '@'), sum(replies), sum(cost_usd)
FROM runtime_session_models
WHERE model GLOB '*/*#*' AND model NOT GLOB '*#*#*'
GROUP BY session_id, replace(model, '#', '@')
ON CONFLICT (session_id, model) DO UPDATE SET
    replies = replies + excluded.replies,
    cost_usd = cost_usd + excluded.cost_usd;

DELETE FROM runtime_session_models WHERE model GLOB '*/*#*' AND model NOT GLOB '*#*#*';

UPDATE run_reply_models SET model = replace(model, '#', '@') WHERE model GLOB '*/*#*' AND model NOT GLOB '*#*#*';
