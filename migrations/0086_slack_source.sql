-- The `slack` source (DESIGN §22, §30, ROADMAP M64 stage 2): the replies people wrote in the Slack sink's ticket
-- threads, a listed operator's recorded as their message. It keeps no observations of its own: what it records is the
-- operator's messages, in `messages`, so only `connector_runs` changes.

-- SQLite cannot change a CHECK in place, so `connector_runs` is rebuilt with every row it had, its `kind` naming
-- `slack` too; nothing references it.
CREATE TABLE connector_runs_0086 (
    id                   INTEGER PRIMARY KEY,
    tick_id              INTEGER REFERENCES ticks(id),
    source               TEXT NOT NULL,
    kind                 TEXT NOT NULL CHECK (kind IN ('tracker', 'vcs', 'artifacts', 'slack')),
    started_at           TEXT NOT NULL,
    ended_at             TEXT NOT NULL,
    status               TEXT NOT NULL CHECK (status IN ('ok', 'partial', 'failed')),
    request              TEXT NOT NULL,
    recorded             TEXT NOT NULL,
    refused              TEXT NOT NULL,
    missed               TEXT,
    stderr               TEXT NOT NULL,
    query_result         TEXT,
    review_query_result  TEXT,
    CHECK ((status = 'ok') = (missed IS NULL))
);
INSERT INTO connector_runs_0086 (
    id, tick_id, source, kind, started_at, ended_at, status, request, recorded, refused, missed, stderr, query_result,
    review_query_result
)
SELECT
    id, tick_id, source, kind, started_at, ended_at, status, request, recorded, refused, missed, stderr, query_result,
    review_query_result
FROM connector_runs;
DROP TABLE connector_runs;
ALTER TABLE connector_runs_0086 RENAME TO connector_runs;
CREATE INDEX connector_runs_source ON connector_runs(source, id);
CREATE INDEX connector_runs_tick ON connector_runs(tick_id);
