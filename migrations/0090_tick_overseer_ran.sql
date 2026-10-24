-- Whether the tick ran its overseer (DESIGN §39): 0 for one the harness's decisions left nothing to judge, which
-- closed without it and cost nothing, and for one halted before it (§6 step 5); NULL on a tick from before that was
-- recorded, every one of which that got that far ran it.
ALTER TABLE ticks ADD COLUMN overseer_ran INTEGER;
