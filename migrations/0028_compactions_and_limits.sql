-- How many times the runtime compacted an agent run's session, summing what it had said so far in place of it
-- (DESIGN §13): read with the run's models, as many as its record holds `compaction` messages. NULL where the record
-- says none (OpenCode 1's), for a read that did not find the session, and for every run read before this column.
ALTER TABLE run_model_reads ADD COLUMN compactions INTEGER CHECK (compactions >= 0);

-- The window of a model that served a run, in tokens, as the runtime listed it before the run (DESIGN §13): the input
-- it takes, and its whole context, input and output. Copied from `model_limits` when the run's models are recorded,
-- so a later listing changes no run's. NULL where the runtime lists no such limit, canopy had not listed the model, or
-- the run was read before these columns.
ALTER TABLE run_models ADD COLUMN input_limit INTEGER CHECK (input_limit > 0);
ALTER TABLE run_models ADD COLUMN context_limit INTEGER CHECK (context_limit > 0);

-- Each model's window as the runtime last listed it, by `provider/model`, kept from the list canopy reads to check a
-- run's model before the run starts: a row per listed model that has a limit, replaced by each later listing.
CREATE TABLE model_limits (
    model          TEXT PRIMARY KEY,
    input_limit    INTEGER CHECK (input_limit > 0),
    context_limit  INTEGER CHECK (context_limit > 0),
    listed_at      TEXT NOT NULL,
    CHECK (input_limit IS NOT NULL OR context_limit IS NOT NULL)
) WITHOUT ROWID;
