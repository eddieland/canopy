-- sha256 of 0022_upkeep_runs.sql: 3f16bd332aabec20652c8f3b78d024ddcb5561e97bcef59afcafd18a4b815e4b

INSERT INTO upkeep_runs (id, tick_id, kind, repo, slot_path, started_at, ended_at, status, detail)
VALUES (1, NULL, 'pack', 'api', NULL, '2026-11-17T10:00:00Z', '2026-11-17T10:01:00Z', 'done',
    '120 loose objects (480 KiB) and 60 packs before, 0 loose objects (0 KiB) and 2 packs after');
