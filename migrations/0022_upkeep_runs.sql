-- The pools' upkeep (DESIGN §26): git's maintenance in a repository's primary clone, by a live tick while its pool is
-- idle or by `canopy gc --git`, and the operator's `pools.idle_cmd` in a slot long unleased. One row per attempt; the
-- newest of each tells when the next is due, and one that failed raises `upkeep_failed` until a newer one does not.
CREATE TABLE upkeep_runs (
    id          INTEGER PRIMARY KEY,
    -- The tick that ran it; NULL for `canopy gc --git` by hand.
    tick_id     INTEGER REFERENCES ticks(id),
    kind        TEXT NOT NULL CHECK (kind IN ('pack', 'idle')),
    repo        TEXT NOT NULL,
    -- The slot an `idle` run ran in; NULL for `pack`, git's maintenance in the primary clone.
    slot_path   TEXT,
    started_at  TEXT NOT NULL,
    ended_at    TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('done', 'skipped', 'failed')),
    -- The harness's words for the operator: the objects before and after, why it was skipped, or why it failed.
    detail      TEXT NOT NULL,
    CHECK ((kind = 'idle') = (slot_path IS NOT NULL))
);

CREATE INDEX upkeep_runs_of ON upkeep_runs(kind, repo, slot_path, id);
