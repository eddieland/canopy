-- Initiatives are named epics (DESIGN §43), the operator's word for them; the tracker key whose children are put to
-- the operator as suggestions becomes `tracker_epic`, so canopy's epic and the tracker's are never the same word. Each
-- table keeps its rows, and the tables naming them follow the rename; the indexes are made again under the new names.
ALTER TABLE initiatives RENAME TO epics;
ALTER TABLE epics RENAME COLUMN epic TO tracker_epic;
ALTER TABLE initiative_repos RENAME TO epic_repos;
ALTER TABLE epic_repos RENAME COLUMN initiative_id TO epic_id;
ALTER TABLE initiative_members RENAME TO epic_members;
ALTER TABLE epic_members RENAME COLUMN initiative_id TO epic_id;
DROP INDEX initiative_members_current;
DROP INDEX initiative_members_of;
CREATE UNIQUE INDEX epic_members_current ON epic_members(ticket_key) WHERE removed_at IS NULL;
CREATE INDEX epic_members_of ON epic_members(epic_id, id);
