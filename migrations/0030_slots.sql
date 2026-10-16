-- canopy's own worktree pools (DESIGN §18, ROADMAP M45): one row per slot of a repository's pool, idle or leased.
-- Written only by `core/pool.py`, under the pool's lock. A slot is leased while `lease_holder` is set; a lease a
-- failed seed left has a holder but no id, so no conditional return can clear it. `base` is the branch the slot was
-- last leased on by name, empty for the default branch; a return parks the slot there. `seeded` is a JSON array of the
-- paths seeding wrote in the slot, relative to it, which the next reset removes. A pool made by treehouse has no rows.

CREATE TABLE slots (
    repo          TEXT NOT NULL,
    name          TEXT NOT NULL,
    path          TEXT NOT NULL UNIQUE,
    lease_id      TEXT,
    lease_holder  TEXT,
    leased_at     TEXT,
    base          TEXT NOT NULL DEFAULT '',
    seeded        TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (repo, name),
    CHECK ((lease_holder IS NULL) = (leased_at IS NULL)),
    CHECK (lease_id IS NULL OR lease_holder IS NOT NULL)
);
