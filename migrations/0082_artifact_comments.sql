-- The `artifacts` source (DESIGN §30, §38, ROADMAP M62 stage 3): what it read of an artifact store's comment feed.
-- Unlike a ticket or a PR, the feed is read past a cursor, each change once: a thread and a comment are each kept as
-- the newest change the source read of it, by the store's `seq`. Nothing here is authority, and none of it reaches a
-- conversation: an observation says what the source saw and when.

-- SQLite cannot change a CHECK in place, so `connector_runs` is rebuilt with every row it had, its `kind` naming
-- `artifacts` too; nothing references it.
CREATE TABLE connector_runs_0082 (
    id                   INTEGER PRIMARY KEY,
    tick_id              INTEGER REFERENCES ticks(id),
    source               TEXT NOT NULL,
    kind                 TEXT NOT NULL CHECK (kind IN ('tracker', 'vcs', 'artifacts')),
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
INSERT INTO connector_runs_0082 (
    id, tick_id, source, kind, started_at, ended_at, status, request, recorded, refused, missed, stderr, query_result,
    review_query_result
)
SELECT
    id, tick_id, source, kind, started_at, ended_at, status, request, recorded, refused, missed, stderr, query_result,
    review_query_result
FROM connector_runs;
DROP TABLE connector_runs;
ALTER TABLE connector_runs_0082 RENAME TO connector_runs;
CREATE INDEX connector_runs_source ON connector_runs(source, id);
CREATE INDEX connector_runs_tick ON connector_runs(tick_id);

-- How far each `artifacts` source has read its feed: `through` is the cursor its next run reads from, which only goes
-- up; `read_at` is when a run last read the feed to its `end` line with nothing refused, NULL until one has.
CREATE TABLE observed_feeds (
    source   TEXT PRIMARY KEY,
    through  INTEGER NOT NULL CHECK (through >= 0),
    read_at  TEXT
);

-- Each thread on an artifact, as the newest change read of it left it. `origin` is the artifact's origin pairs, as a
-- JSON object; `ticket` its `canopy.ticket` where that is a ticket's key. `exact`, `prefix`, and `suffix` are its
-- anchor, all NULL for a thread on the whole artifact, and `anchor_status` whether the passage was in the artifact's
-- latest version when the store printed the change, NULL with no anchor or when the store does not say.
CREATE TABLE observed_artifact_threads (
    id                TEXT PRIMARY KEY,
    artifact_id       TEXT NOT NULL,
    origin            TEXT NOT NULL,
    ticket            TEXT,
    exact             TEXT,
    prefix            TEXT,
    suffix            TEXT,
    anchored_version  INTEGER NOT NULL,
    state             TEXT NOT NULL CHECK (state IN ('open', 'resolved')),
    anchor_status     TEXT CHECK (anchor_status IN ('found', 'passage_gone')),
    seq               INTEGER NOT NULL,
    observed_at       TEXT NOT NULL
);
CREATE INDEX observed_artifact_threads_ticket ON observed_artifact_threads(ticket);

-- Each comment on an artifact, as the newest change read of it left it: an edit or a deletion replaces it, and a
-- deleted comment keeps its row with its body empty. `author` is the store's id for who wrote it; `body` is cut at the
-- mirror's length, `truncated` saying so; `marked` is whether it carries every one of the workers' marks (D069).
CREATE TABLE observed_artifact_comments (
    id            TEXT PRIMARY KEY,
    thread_id     TEXT NOT NULL REFERENCES observed_artifact_threads(id),
    author        TEXT NOT NULL,
    author_name   TEXT NOT NULL,
    author_kind   TEXT NOT NULL CHECK (author_kind IN ('person', 'agent')),
    on_behalf_of  TEXT,
    via           TEXT NOT NULL CHECK (via IN ('web', 'mcp')),
    body          TEXT NOT NULL,
    truncated     INTEGER NOT NULL CHECK (truncated IN (0, 1)),
    marked        INTEGER NOT NULL CHECK (marked IN (0, 1)),
    created_at    TEXT NOT NULL,
    edited_at     TEXT,
    deleted_at    TEXT,
    seq           INTEGER NOT NULL,
    observed_at   TEXT NOT NULL
);
CREATE INDEX observed_artifact_comments_thread ON observed_artifact_comments(thread_id);
