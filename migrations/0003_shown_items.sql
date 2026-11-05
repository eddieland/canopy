-- The live tick, closed `ok`, whose overseer was first shown an item's text and decided its ticket (DESIGN §30): a
-- review item's body is in the state block once, on that tick, and later ticks list the item by its number and marks
-- alone. NULL for an item never shown so, and for every kind but a review or a review comment, whose text is the only
-- one shown this way.
ALTER TABLE item_numbers ADD COLUMN shown_tick_id INTEGER REFERENCES ticks(id);
