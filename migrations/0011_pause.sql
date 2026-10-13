-- Whether the operator paused the loop (DESIGN §6, The loop): a row means paused, since `paused_at`, through
-- `channel` (`loop`, the loop's own terminal; `cli`; or `web`). At most one row. `canopy loop` starts no tick while
-- it is there; a hand-run `canopy tick` still runs. Resuming deletes it.

CREATE TABLE pause (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    paused_at  TEXT NOT NULL,
    channel    TEXT NOT NULL
);
