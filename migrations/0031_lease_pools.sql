-- Which pool made each lease (DESIGN §18, ROADMAP M45 stage 3): a slot always goes back to the pool that leased it,
-- whichever `pools.backend` names now, so switching with runs in flight is safe. Leases from before are treehouse's.

ALTER TABLE run_slots ADD COLUMN pool TEXT NOT NULL DEFAULT 'treehouse' CHECK (pool IN ('treehouse', 'canopy'));
ALTER TABLE review_runs ADD COLUMN pool TEXT NOT NULL DEFAULT 'treehouse' CHECK (pool IN ('treehouse', 'canopy'));
