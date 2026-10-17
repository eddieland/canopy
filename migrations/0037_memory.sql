-- Agent memory (DESIGN §28, ROADMAP M50): ticket notes a ticket's runs write for its later runs, proposals workers make
-- for the whole workspace, and the lessons the operator promotes from them. Empty while `memory.ticket_notes` and
-- `memory.proposals` are both off, as they are by default. `body` is NULL once the operator forgot or purged the row:
-- a tombstone that keeps who wrote it and when. Nothing is edited in place: a newer note under a key supersedes the
-- one before it, which stays.

CREATE TABLE memories (
    id              INTEGER PRIMARY KEY,
    scope           TEXT NOT NULL CHECK (scope IN ('ticket', 'proposal', 'lesson')),
    -- A note's ticket, a proposal's source ticket; NULL for a lesson, which is the workspace's.
    ticket_key      TEXT REFERENCES tickets(key),
    -- The repository a proposal or a lesson is about; NULL for every repository, and for a note.
    repo            TEXT,
    key             TEXT NOT NULL,
    body            TEXT,
    status          TEXT NOT NULL CHECK (status IN ('active', 'pending', 'superseded', 'invalid')),
    -- The harness's words for the latest change of status, such as `superseded by note 41`.
    why             TEXT,
    author          TEXT NOT NULL CHECK (author IN ('worker', 'operator')),
    run_id          INTEGER REFERENCES runs(id),
    tick_id         INTEGER REFERENCES ticks(id),
    -- The commit the run's branch was at when its worker ended, `repo@sha` per repository for a joint run.
    head            TEXT,
    supersedes      INTEGER REFERENCES memories(id),
    promoted_from   INTEGER REFERENCES memories(id),
    created_at      TEXT NOT NULL,
    approved_at     TEXT,
    last_used_at    TEXT,
    use_count       INTEGER NOT NULL DEFAULT 0,
    review_at       TEXT,
    invalidated_at  TEXT,
    -- A lesson's latest `memory_wrong` report, and the run that made it, until the operator renews it.
    wrong_at        TEXT,
    wrong_run_id    INTEGER REFERENCES runs(id),
    CHECK ((scope = 'lesson') = (author = 'operator')),
    CHECK ((scope = 'lesson') = (ticket_key IS NULL)),
    CHECK (scope != 'ticket' OR repo IS NULL),
    CHECK ((scope = 'lesson') = (run_id IS NULL)),
    CHECK (status != 'pending' OR scope = 'proposal'),
    CHECK (status != 'active' OR scope != 'proposal'),
    CHECK ((wrong_at IS NULL) = (wrong_run_id IS NULL))
);
CREATE UNIQUE INDEX memories_active ON memories(scope, ifnull(ticket_key, ''), key) WHERE status = 'active';
CREATE INDEX memories_ticket ON memories(ticket_key, status);
CREATE INDEX memories_run ON memories(run_id);

-- What a run's prompt was rendered under, for each run of a kind a tier reaches dispatched while either tier was not
-- off: each tier's mode (`off` for one that does not reach the run's kind), and the entries `_run` refused from its
-- result, as a JSON list. A run with no row was rendered with both tiers off.
CREATE TABLE run_memory (
    run_id        INTEGER PRIMARY KEY REFERENCES runs(id),
    ticket_notes  TEXT NOT NULL CHECK (ticket_notes IN ('off', 'record', 'use')),
    proposals     TEXT NOT NULL CHECK (proposals IN ('off', 'record', 'use')),
    refused       TEXT NOT NULL DEFAULT '[]'
);

-- Each memory rendered into a run's prompt. Only these count in that run's `memory_used` and `memory_wrong`, and only
-- these notes' keys in its `drop_notes`.
CREATE TABLE memory_reads (
    run_id     INTEGER NOT NULL REFERENCES runs(id),
    memory_id  INTEGER NOT NULL REFERENCES memories(id),
    PRIMARY KEY (run_id, memory_id)
);
CREATE INDEX memory_reads_memory ON memory_reads(memory_id);
