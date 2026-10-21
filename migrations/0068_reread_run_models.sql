-- Read again each run whose session's models were found, now that a model's name carries the variant it served at
-- (DESIGN §13, Each agent's model). The runs' models stay: a read that finds the session gone keeps them, and one that
-- finds it replaces them. A missing session is not asked about again, and a failed read is retried as before.
DELETE FROM run_model_reads WHERE status = 'found';
