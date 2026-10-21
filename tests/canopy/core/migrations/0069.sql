-- sha256 of 0069_reread_run_models.sql: 9ff2264de5b2711e4f3ce7559f165ebfbb4d29469f5f7413a6f0aa6660123159

-- Creates no table. It deletes the read 0054 seeds, so a read is seeded again for the migrations after it.
INSERT INTO run_model_reads (run_table, run_id, status, error, attempts, read_at)
VALUES ('runs', 1, 'found', NULL, 1, 'x');
