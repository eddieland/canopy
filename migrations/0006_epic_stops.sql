-- When the operator stopped an epic (DESIGN §43): no tick starts a plan run of it again, and its members are left as
-- they are. NULL while it is not stopped, and for every epic from before this migration.
ALTER TABLE epics ADD COLUMN stopped_at TEXT;
