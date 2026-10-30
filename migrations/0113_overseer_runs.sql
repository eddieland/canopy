-- A tick's runs of the overseer (DESIGN §40, ROADMAP M40): the subject each was given, how it ended, its session, the
-- model canopy asked for, and what it cost, as `ticks` keeps them for its one run. A tick makes one run today, given
-- the whole state block, its subject NULL; `ticks` still keeps that run's session, cost, and model, and the models that
-- served it are `run_models`' under the tick.
--
-- `status`: `running` until the run ends; `ok`, its done line printed and every duty done; `failed`, it did not start,
-- timed out, exited non-zero, or printed no done line, or its tick raised while it ran, `failure` saying why; `undone`,
-- it ended well and left a duty undone, `failure` naming them; `abandoned`, its tick's process died while it ran.
-- `failure` is NULL for any other status.
CREATE TABLE overseer_runs (
    id                        INTEGER PRIMARY KEY,
    tick_id                   INTEGER NOT NULL REFERENCES ticks(id),
    subject                   TEXT,
    started_at                TEXT NOT NULL,
    ended_at                  TEXT,
    status                    TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'ok', 'failed', 'undone', 'abandoned')),
    failure                   TEXT,
    session_id                TEXT,
    model                     TEXT,
    cost_usd                  REAL,
    tokens_input              INTEGER,
    tokens_output             INTEGER,
    tokens_reasoning          INTEGER,
    tokens_cache_read         INTEGER,
    tokens_cache_write        INTEGER,
    tokens_peak_context       INTEGER,
    tokens_first_call         INTEGER,
    tokens_first_cache_write  INTEGER,
    tokens_first_cache_read   INTEGER
);
CREATE INDEX overseer_runs_tick ON overseer_runs(tick_id);

-- A run for each past tick that ran its overseer: one 0090 marked so, or, before it, one that got that far, closing
-- `ok`, `skipped`, or `overseer_failed`, or keeping a session or a cost. Started as its tick did. How it ended is read
-- from its tick: an `ok` or `skipped` tick's ran well, a duty left undone is in an `overseer_failed` tick's summary,
-- a tick left `running` or `abandoned` died, and any other, `overseer_failed` or `error`, failed, its summary why.
INSERT INTO overseer_runs (
    tick_id, started_at, ended_at, status, failure, session_id, model, cost_usd, tokens_input, tokens_output,
    tokens_reasoning, tokens_cache_read, tokens_cache_write, tokens_peak_context, tokens_first_call,
    tokens_first_cache_write, tokens_first_cache_read
)
SELECT
    id,
    started_at,
    coalesce(ended_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CASE
        WHEN status IN ('ok', 'skipped') THEN 'ok'
        WHEN status IN ('running', 'abandoned') THEN 'abandoned'
        WHEN status = 'overseer_failed' AND summary LIKE '%overseer left duties undone%' THEN 'undone'
        ELSE 'failed'
    END,
    CASE WHEN status IN ('ok', 'skipped', 'running', 'abandoned') THEN NULL ELSE summary END,
    session_id,
    model,
    cost_usd,
    tokens_input,
    tokens_output,
    tokens_reasoning,
    tokens_cache_read,
    tokens_cache_write,
    tokens_peak_context,
    tokens_first_call,
    tokens_first_cache_write,
    tokens_first_cache_read
FROM ticks
WHERE overseer_ran = 1
    OR (
        overseer_ran IS NULL
        AND (status IN ('ok', 'skipped', 'overseer_failed') OR session_id IS NOT NULL OR cost_usd IS NOT NULL)
    )
ORDER BY id;
