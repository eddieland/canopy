-- Every session the agent runtime keeps (DESIGN §13, Every session's spend), canopy's runs' and the operator's own
-- alike, read from the runtime's own record while `canopy loop` waits between ticks, so that the journal tells spend in
-- canopy from spend outside it. A session is read again each time the runtime updates it, its row replaced.

-- Each session as the runtime last recorded it: the session it ran for as a subagent, where it ran, when it started and
-- was last updated, what its replies cost in US dollars as the runtime priced them, and their tokens by kind.
-- `updated_ms` is the runtime's own stamp of the update, in milliseconds, which the reading's cursor names.
CREATE TABLE runtime_sessions (
    session_id          TEXT PRIMARY KEY,
    parent_id           TEXT,
    directory           TEXT NOT NULL,
    started_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    updated_ms          INTEGER NOT NULL,
    cost_usd            REAL NOT NULL,
    tokens_input        INTEGER NOT NULL,
    tokens_output       INTEGER NOT NULL,
    tokens_reasoning    INTEGER NOT NULL,
    tokens_cache_read   INTEGER NOT NULL,
    tokens_cache_write  INTEGER NOT NULL,
    read_at             TEXT NOT NULL
) WITHOUT ROWID;
CREATE INDEX runtime_sessions_started ON runtime_sessions (started_at);
CREATE INDEX runtime_sessions_parent ON runtime_sessions (parent_id);

-- Each model a session's replies name: how many it wrote, and what they cost. None for a session that made no call.
CREATE TABLE runtime_session_models (
    session_id  TEXT NOT NULL REFERENCES runtime_sessions (session_id) ON DELETE CASCADE,
    model       TEXT NOT NULL,
    replies     INTEGER NOT NULL,
    cost_usd    REAL NOT NULL,
    PRIMARY KEY (session_id, model)
) WITHOUT ROWID;

-- How reading the runtime's record stands, in one row: where the next read starts, after the last session read, and
-- how the last read ended, `found`, `missing` (the runtime has kept no session yet), or `failed`, with canopy's words
-- for why. `skipped` counts the sessions every read so far passed over as ones canopy cannot read.
CREATE TABLE runtime_session_reads (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    cursor_updated_ms   INTEGER,
    cursor_session_id   TEXT,
    status              TEXT NOT NULL CHECK (status IN ('found', 'missing', 'failed')),
    error               TEXT,
    skipped             INTEGER NOT NULL,
    read_at             TEXT NOT NULL,
    CHECK ((status = 'failed') = (error IS NOT NULL)),
    CHECK ((cursor_updated_ms IS NULL) = (cursor_session_id IS NULL))
);
