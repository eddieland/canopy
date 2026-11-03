-- The merged blocker an open PR is stacked on (DESIGN §10): the unit whose branch the PR targets, found by its branch.
-- Without it, each open PR the tickets list and the event stream weigh scanned every unit ever recorded, and SQLite
-- from 3.53 no longer finds a cheaper plan on its own.
CREATE INDEX ticket_units_branch ON ticket_units(branch);
