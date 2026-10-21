-- Each pass of garbage collection (DESIGN §26): when it ran, the retention it ran with, and what it removed. A file of
-- a row that ended before a pass's cutoff for its kind, and is gone, went by retention, which is how the web UI says
-- so. A cutoff is NULL when its kind is kept forever. `removed` counts, by the kind `canopy gc --dry-run` names, the
-- files removed and their bytes, as a JSON object of `{"files", "bytes"}`; `failures` the files it could not remove.
-- `tick_id` is NULL for a pass run by hand.
CREATE TABLE gc_passes (
    id               INTEGER PRIMARY KEY,
    tick_id          INTEGER REFERENCES ticks(id),
    started_at       TEXT NOT NULL,
    ended_at         TEXT NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('ok', 'failed')),
    run_files_days   INTEGER NOT NULL,
    tick_files_days  INTEGER NOT NULL,
    run_cutoff       TEXT,
    tick_cutoff      TEXT,
    removed          TEXT NOT NULL,
    failures         INTEGER NOT NULL,
    error            TEXT,
    CHECK ((status = 'ok') = (error IS NULL))
);
