-- sha256 of 0068_reread_run_models.sql: ea5fb92796249947c7fcbdd0c75bb4a152601bdb5ea5ef71d10a176adf9df150

-- Creates no table. It deletes the read 0054 seeds, so a read is seeded again for the migrations after it.
INSERT INTO run_model_reads (run_table, run_id, status, error, attempts, read_at)
VALUES ('runs', 1, 'found', NULL, 1, 'x');
