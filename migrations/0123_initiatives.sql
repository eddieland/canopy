-- Initiatives (DESIGN §43): work spanning several tickets, the operator's own subject, `init:N`. Only the operator's
-- channels write these rows, refused inside a tick or any run: the submission is what authorizes the initiative's plan
-- runs, and its text their instruction. `project` is the tracker project its breakdown's tickets are filed in, NULL for
-- none; `epic` a tracker key whose children are put to the operator as suggestions, NULL for none.
CREATE TABLE initiatives (
    id            INTEGER PRIMARY KEY,
    text          TEXT NOT NULL,
    project       TEXT,
    epic          TEXT,
    channel       TEXT NOT NULL CHECK (channel IN ('cli', 'web')),
    submitted_at  TEXT NOT NULL
);

-- The repositories an initiative's plan reads, by their names in the map, at least one each.
CREATE TABLE initiative_repos (
    initiative_id  INTEGER NOT NULL REFERENCES initiatives(id),
    repo           TEXT NOT NULL,
    PRIMARY KEY (initiative_id, repo)
);

-- An initiative's member tickets, as the operator added and removed them. A removal ends the row rather than deleting
-- it, so what was a member stays to read. A ticket is a member of at most one initiative at a time. `ticket_key` names
-- no `tickets` row: a ticket may be a member before canopy has seen it, and membership authorizes no work on it.
CREATE TABLE initiative_members (
    id               INTEGER PRIMARY KEY,
    initiative_id    INTEGER NOT NULL REFERENCES initiatives(id),
    ticket_key       TEXT NOT NULL,
    added_at         TEXT NOT NULL,
    added_channel    TEXT NOT NULL CHECK (added_channel IN ('cli', 'web')),
    removed_at       TEXT,
    removed_channel  TEXT CHECK (removed_channel IN ('cli', 'web')),
    CHECK ((removed_at IS NULL) = (removed_channel IS NULL))
);
CREATE UNIQUE INDEX initiative_members_current ON initiative_members(ticket_key) WHERE removed_at IS NULL;
CREATE INDEX initiative_members_of ON initiative_members(initiative_id, id);
