-- sha256 of 0071_gc_passes.sql: 4776156287b7da292be5649eb8fbf474b383413fe55789d8a010154ba2777fbc

INSERT INTO gc_passes (
    tick_id, started_at, ended_at, status, run_files_days, tick_files_days, run_cutoff, tick_cutoff, removed, failures,
    error
)
VALUES (1, 'x', 'x', 'ok', 30, 7, 'w', 'w', '{"run files": {"files": 2, "bytes": 110}}', 0, NULL);
