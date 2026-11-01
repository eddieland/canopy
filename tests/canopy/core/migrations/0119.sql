-- sha256 of 0119_plan_metrics.sql: 5ac28eafe0887144f80889f9909277dcafef4cf19df76eff31152871e1db5e36

INSERT INTO plan_metrics (plan_id, version, measured_at, problem, words, lines, code_blocks, tables, diagrams)
VALUES ((SELECT min(id) FROM plans), 1, 'x', NULL, 120, 14, 1, 0, 0);
