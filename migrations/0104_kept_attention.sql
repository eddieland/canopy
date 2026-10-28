-- The attention items the overseer keeps, `needs_author`, `multi_repo`, and `notice_rerun` (DESIGN §14, §37), are
-- recorded once, naming what each is about, and held until that ends it, where the overseer recorded one every tick
-- its cause held. `kept` is 1 on such a record; 0 on every other decision, and on an item the overseer recorded every
-- tick before this, which the list still reads that way. `item` is the journal number (§35) of what it names: the
-- comment, review item, or review run a `needs_author` waits on, or the check run a `notice_rerun` holds; NULL for one
-- about its ticket alone.
ALTER TABLE decisions ADD COLUMN kept INTEGER NOT NULL DEFAULT 0 CHECK (kept IN (0, 1));
ALTER TABLE decisions ADD COLUMN item INTEGER;

-- The list reads every kept record however old it is, so each is found by index.
CREATE INDEX decisions_kept ON decisions(id) WHERE kept = 1;
