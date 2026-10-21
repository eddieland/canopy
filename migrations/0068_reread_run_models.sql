-- Read again each run whose session's models were found, now that a model's name carries the variant it served at
-- (DESIGN §13, Each agent's model). The runs' models stay, and are shown, till a read that finds the session replaces
-- them; one that fails or finds the session gone keeps them. A missing session is not asked about again, and a failed
-- read is retried as before.
DELETE FROM run_model_reads WHERE status = 'found';
